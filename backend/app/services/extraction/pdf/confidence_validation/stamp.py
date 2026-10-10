"""Attach PyMuPDF structure to LLM tables; recover missing grids."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import openai
import pandas as pd
import pymupdf

from app.services.extraction.pdf.confidence_validation.alignment import (
    _apply_column_alignment_guard,
    _cell_is_empty,
    _cell_is_numeric,
    _dataframe_numeric_fill_ratio,
    _row_is_column_index_strip,
    _stamp_bbox_from_candidate,
    _strip_ungrounded_direction_columns,
)
from app.services.extraction.pdf.confidence_validation.normalize import (
    _llm_title_is_id_only,
    _normalize_table,
    _prefer_descriptive_llm_title,
    derive_human_review_needed,
)
from app.services.extraction.pdf.utils.pymupdf import (
    _best_matching_ruled_candidate,
    _bbox_iou,
    _distinct_ruled_candidates,
    _llm_missing_identity_stubs,
    _llm_starts_at_sex_column,
    dedupe_candidates_by_bbox,
)
from app.services.extraction.pdf.confidence_validation.table_confidence import (
    dedupe_column_names,
    table_dict_from_df,
)

def _norm_header_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


# Trailing unit tokens that pymupdf often flattens onto a leaf name
# ("North DMC\n%" → "North DMC %") and then get re-attached as phantom cols.
_UNIT_SUFFIX_RE = re.compile(
    r"(?:\s*%|\s+(?:pct|percent(?:age)?|\bin\s+(?:lakhs?|thousands?|crores?|millions?)))$",
    re.IGNORECASE,
)
_UNIT_LEAF_RE = re.compile(
    r"^(?:%|pct|percent(?:age)?|(?:in\s+)?(?:lakhs?|thousands?|crores?|millions?))$",
    re.IGNORECASE,
)


def _strip_unit_suffix(value: Any) -> str:
    """'north dmc %' / 'north dmc percent' → 'north dmc'."""
    s = _norm_header_key(value)
    if not s:
        return ""
    stripped = _UNIT_SUFFIX_RE.sub("", s).strip()
    return stripped or s


def _header_alias_keys(value: Any, path: Any = None) -> set:
    """Match keys for a header, including unit-suffix and parent/leaf variants."""
    keys: set = set()
    leaf = _norm_header_key(value)
    if leaf:
        keys.add(leaf)
        keys.add(_strip_unit_suffix(leaf))

    path_clean: List[str] = []
    if isinstance(path, (list, tuple)):
        path_clean = [str(p).strip() for p in path if str(p).strip()]
    if path_clean:
        last = path_clean[-1]
        keys.add(_norm_header_key(last))
        keys.add(_strip_unit_suffix(last))
        # Leaf is only "%" / "percent" → identity is the parent agency name.
        if len(path_clean) >= 2 and _UNIT_LEAF_RE.match(last):
            keys.add(_norm_header_key(path_clean[-2]))
        if len(path_clean) >= 2:
            joined = f"{path_clean[-2]} {path_clean[-1]}"
            dashed = f"{path_clean[-2]} - {path_clean[-1]}"
            keys.add(_norm_header_key(joined))
            keys.add(_strip_unit_suffix(joined))
            keys.add(_norm_header_key(dashed))
            keys.add(_strip_unit_suffix(dashed))
            keys.add(_norm_header_key(" / ".join(path_clean)))
    return {k for k in keys if k}


def _candidate_is_duplicate_of_columns(
    m: Dict[str, Any],
    fallback_name: str,
    columns: List[Dict[str, Any]],
) -> bool:
    """True when candidate header is a unit-suffixed clone of an LLM column."""
    path = _header_path_from_meta(m, fallback_name)
    leaf = str(m.get("name") or fallback_name or "").strip()
    cand_keys = _header_alias_keys(leaf, path)
    if not cand_keys:
        return False
    for col in columns:
        existing = _header_alias_keys(col.get("name"), col.get("header_path"))
        if cand_keys & existing:
            return True
    return False


def _candidate_column_meta(df: pd.DataFrame) -> List[Dict[str, Any]]:
    try:
        meta = list(getattr(df, "attrs", {}).get("dhara_column_meta") or [])
    except Exception:
        meta = []
    if meta:
        return [m if isinstance(m, dict) else {} for m in meta]
    # Fallback: single-level leaves from column names only.
    return [
        {"name": str(c), "header_group": None, "header_path": [str(c)]}
        for c in df.columns
    ]


def _header_path_from_meta(m: Dict[str, Any], fallback_name: str) -> List[str]:
    raw = m.get("header_path")
    if isinstance(raw, (list, tuple)):
        path = [str(p).strip() for p in raw if str(p).strip()]
        if path:
            return path
    leaf = str(m.get("name") or fallback_name).strip() or fallback_name
    group = m.get("header_group")
    group_s = str(group).strip() if group is not None else ""
    if group_s and group_s.lower() != leaf.lower():
        return [group_s, leaf]
    return [leaf] if leaf else [fallback_name or ""]


def _table_already_has_multilevel_headers(table: Dict[str, Any]) -> bool:
    for col in table.get("columns") or []:
        path = col.get("header_path")
        if isinstance(path, (list, tuple)) and len([p for p in path if str(p).strip()]) >= 2:
            return True
        if col.get("header_group"):
            return True
    return False


def _score_candidate_for_llm_table(table: Dict[str, Any], cand: Dict[str, Any]) -> float:
    df = cand.get("df")
    if df is None:
        return float("-inf")
    llm_cols = table.get("columns") or []
    meta = _candidate_column_meta(df)
    n_llm = len(llm_cols)
    n_cand = int(df.shape[1])
    score = 0.0
    delta = n_cand - n_llm
    if delta >= 2 and (
        _llm_starts_at_sex_column(llm_cols) or _llm_missing_identity_stubs(table, cand)
    ):
        # Reward recovering dropped S.No./Name stubs instead of matching width.
        score -= abs(delta) * 1.0
        score += float(delta) * 4.0
    else:
        score -= abs(delta) * 3.0
        if n_llm == n_cand:
            score += 12.0
    llm_keys = {_norm_header_key(c.get("name")) for c in llm_cols if c.get("name")}
    cand_keys: set = set()
    for i, name in enumerate(df.columns):
        cand_keys.add(_norm_header_key(name))
        m = meta[i] if i < len(meta) else {}
        if m.get("name"):
            cand_keys.add(_norm_header_key(m.get("name")))
        path = m.get("header_path") or []
        if isinstance(path, (list, tuple)) and path:
            cand_keys.add(_norm_header_key(path[-1]))
            # Flattened "Parent - Leaf" style LLM names.
            if len(path) >= 2:
                cand_keys.add(_norm_header_key(f"{path[-2]} - {path[-1]}"))
                cand_keys.add(_norm_header_key(f"{path[-2]} {path[-1]}"))
    overlap = len(llm_keys & cand_keys)
    score += overlap * 2.5
    if cand.get("method") in ("pymupdf_lines_strict", "pymupdf_lines"):
        score += 1.5
    # Prefer richer numeric fill when otherwise tied.
    score += min(2.0, _dataframe_numeric_fill_ratio(df))
    return score


def _pick_candidate_for_llm_table(
    table: Dict[str, Any],
    candidates: Optional[List[Dict[str, Any]]],
    used: Optional[set] = None,
) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None
    used = used if used is not None else set()
    pool = [
        (i, c) for i, c in enumerate(candidates)
        if i not in used and c.get("df") is not None and not getattr(c["df"], "empty", True)
    ]
    if not pool:
        # Allow reuse if every candidate was already claimed (multi-table pages
        # with fewer candidates than LLM tables).
        pool = [
            (i, c) for i, c in enumerate(candidates)
            if c.get("df") is not None and not getattr(c["df"], "empty", True)
        ]
    if not pool:
        return None
    best_i, best = max(pool, key=lambda ic: _score_candidate_for_llm_table(table, ic[1]))
    if _score_candidate_for_llm_table(table, best) < -20:
        return None
    used.add(best_i)
    return best



def _header_leaves_fuzzy_match(a: Any, b: Any) -> bool:
    """True when leaves are the same or one is a prefixed variant of the other.

    Structural only: 'Age <1' ↔ '<1', 'Birth Weight M' ↔ 'M'. Avoids treating
    LLM renames as distinct columns during candidate↔LLM alignment.
    """
    aa = _norm_header_key(a)
    bb = _norm_header_key(b)
    if not aa or not bb:
        return False
    if aa == bb:
        return True
    # Prefer longer containment with a word/token boundary so '1' does not
    # match '15-24', but 'age <1' / '<1' and 'age 1-4' / '1-4' do.
    if len(aa) >= len(bb):
        longer, shorter = aa, bb
    else:
        longer, shorter = bb, aa
    if len(shorter) < 1:
        return False
    if longer.endswith(" " + shorter) or longer.startswith(shorter + " "):
        return True
    # Tight codes like '<1', '>=70', '1-4' often appear after a dimension word
    # with no extra punctuation: 'age<1' after aggressive normalize is rare,
    # but 'age 1-4' already handled above.
    return False


def _map_meta_indices_to_llm_columns(
    columns: List[Dict[str, Any]],
    meta: List[Dict[str, Any]],
    df: pd.DataFrame,
) -> List[Optional[int]]:
    """For each LLM column, index into candidate meta (or None)."""
    n_llm = len(columns)
    n_meta = len(meta)
    if n_llm == n_meta:
        return list(range(n_llm))

    # Build lookup from normalized leaf / flattened / unit-stripped keys -> meta index.
    # Prefer earlier meta columns when aliases collide (e.g. "North DMC" before "North DMC %").
    key_to_meta: Dict[str, int] = {}
    meta_leaves: List[str] = []
    for i, m in enumerate(meta):
        leaf = str(m.get("name") or (df.columns[i] if i < len(df.columns) else "")).strip()
        meta_leaves.append(leaf)
        path = _header_path_from_meta(m, leaf)
        for k in _header_alias_keys(leaf, path):
            if k and k not in key_to_meta:
                key_to_meta[k] = i

    mapping: List[Optional[int]] = [None] * n_llm
    used_meta: set = set()
    for i, col in enumerate(columns):
        aliases = _header_alias_keys(col.get("name"), col.get("header_path"))
        mi = None
        for k in aliases:
            cand = key_to_meta.get(k)
            if cand is not None and cand not in used_meta:
                mi = cand
                break
        if mi is None:
            # Fuzzy: LLM often prefixes dimension words ('Age <1' vs '<1').
            llm_leaf = str(col.get("name") or "").strip()
            for cand_i, cand_leaf in enumerate(meta_leaves):
                if cand_i in used_meta:
                    continue
                if _header_leaves_fuzzy_match(llm_leaf, cand_leaf):
                    mi = cand_i
                    break
        if mi is not None:
            mapping[i] = mi
            used_meta.add(mi)

    matched = sum(1 for m in mapping if m is not None)
    # Widths nearly equal but names diverged → positional identity beats a
    # failed name map that would later splice two full grids together.
    if (
        abs(n_llm - n_meta) <= 2
        and matched < max(2, int(min(n_llm, n_meta) * 0.5))
        and min(n_llm, n_meta) >= 4
    ):
        return [i if i < n_meta else None for i in range(n_llm)]

    # Residual pairing: after exact/fuzzy hits, map leftover LLM columns onto
    # leftover meta columns in order (e.g. 'Cause of Death' ↔ 'NAME OF THE DISEASE'
    # when age bands already matched). Prevents restore+append doubling.
    unmatched_llm = [i for i, m in enumerate(mapping) if m is None]
    unused_meta = [i for i in range(n_meta) if i not in used_meta]
    if unmatched_llm and unused_meta and abs(len(unmatched_llm) - len(unused_meta)) <= 2:
        for llm_i, meta_i in zip(unmatched_llm, unused_meta):
            mapping[llm_i] = meta_i
            used_meta.add(meta_i)

    # Fill remaining by position when widths match after partial matches.
    if n_llm == n_meta:
        for i in range(n_llm):
            if mapping[i] is None and i not in used_meta:
                mapping[i] = i
                used_meta.add(i)
    return mapping


def _restore_body_merge_empties_from_df(table: Dict[str, Any], df: pd.DataFrame) -> None:
    """Re-introduce empty continuation cells so Preview can rowspan/colspan.

    The ruled pymupdf grid is the source of truth for merge structure. LLM
    reconstruction often fills those holes by forward-filling the parent value
    or inventing placeholders (0). Clear any LLM value where the candidate cell
    is empty inside a sparse (merge-bearing) column.

    Row counts may differ (LLM drops a '(1)(2)(3)' index row, etc.) — align by
    row key before comparing cells.
    """
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    if not rows or df.shape[1] != len(columns):
        return

    cand_vals = df.values.tolist()
    if df.shape[0] == len(rows):
        cand = [list(r) for r in cand_vals]
    else:
        row_map = _align_llm_rows_to_candidate(rows, df)
        cand = []
        width = df.shape[1]
        for r_i in range(len(rows)):
            ci = row_map[r_i] if r_i < len(row_map) else None
            if ci is None or ci >= len(cand_vals):
                cand.append([None] * width)
            else:
                cand.append(list(cand_vals[ci]))

    nrows = len(rows)
    sparse_cols: List[int] = []
    for c in range(df.shape[1]):
        empty = sum(
            1 for r in range(nrows)
            if _cell_is_empty(cand[r][c] if c < len(cand[r]) else None)
        )
        if empty >= 1 and empty >= nrows * 0.12 and empty < nrows:
            sparse_cols.append(c)
    if not sparse_cols:
        return

    for r in range(nrows):
        row = list(rows[r])
        changed = False
        for c in sparse_cols:
            if c >= len(cand[r]) or c >= len(row):
                continue
            if not _cell_is_empty(cand[r][c]):
                continue
            if _cell_is_empty(row[c]):
                continue
            # Candidate empty ⇒ rowspan continuation; drop LLM fill/placeholder.
            row[c] = None
            changed = True
        if changed:
            rows[r] = row
    table["rows"] = rows


_COL_INDEX_STRIP_RE = re.compile(r"^\(\d+\)$")
_BARE_COL_INDEX_RE = re.compile(r"^\d{1,2}$")


def _row_is_column_index_strip(row: Sequence[Any]) -> bool:
    """True for header '(1)(2)(3)' or bare 1..N index strips — not data rows.

    Birth-order / count rows like ``1, 0, 633, 6322, …`` must stay False.
    """
    non_empty = [v for v in row if not _cell_is_empty(v)]
    if len(non_empty) < 2:
        return False
    paren_hits = sum(
        1 for v in non_empty
        if _COL_INDEX_STRIP_RE.match(str(v).strip())
    )
    if paren_hits > len(non_empty) * 0.5:
        return True
    # Bare 1,2,3,…,N under headers (common in CRS PDFs). Require almost-full
    # coverage so a real data row with small integers is never treated as an index.
    if len(non_empty) < 3:
        return False
    if not all(_BARE_COL_INDEX_RE.match(str(v).strip()) for v in non_empty):
        return False
    try:
        nums = [int(str(v).strip()) for v in non_empty]
    except ValueError:
        return False
    return bool(nums) and nums == list(range(1, len(nums) + 1))


def _row_has_measure_like_values(row: Sequence[Any]) -> bool:
    non_empty = [v for v in row if not _cell_is_empty(v)]
    if len(non_empty) < 2:
        return False
    nums = sum(1 for v in non_empty if _cell_is_numeric(v) is True)
    return nums >= max(2, int(len(non_empty) * 0.5))


def _row_content_fingerprint(row: Sequence[Any]) -> Tuple[str, ...]:
    return tuple(
        _norm_header_key(v)
        for v in row
        if not _cell_is_empty(v)
    )


def _restore_missing_data_rows_from_candidate(
    table: Dict[str, Any],
    df: pd.DataFrame,
) -> None:
    """Re-insert blank-stub / column-number rows the LLM dropped.

    Ruled candidates often keep alternating Year / blank-Year percentage rows,
    and CRS-style 1..N / (1)(2)(3) reference strips under headers. Prefer
    candidate order when reconstructing.
    """
    columns = table.get("columns") or []
    llm_rows = [list(r) if isinstance(r, list) else [] for r in (table.get("rows") or [])]
    if not columns or not llm_rows or df is None or getattr(df, "empty", True):
        return

    ncol = len(columns)
    cand_width = int(df.shape[1])
    # Pad/trim at most one phantom leaf; larger width mismatches are unsafe.
    if abs(cand_width - ncol) > 1:
        return

    def _pad(row: Sequence[Any]) -> List[Any]:
        cells = list(row[:ncol]) + [None] * max(0, ncol - len(row))
        return cells[:ncol]

    cand_rows = [_pad(r) for r in df.values.tolist()]
    llm_rows = [_pad(r) for r in llm_rows]
    if len(cand_rows) <= len(llm_rows):
        return

    used_cand: set = set()
    llm_to_cand: List[Optional[int]] = [None] * len(llm_rows)

    # Stub-key match: skip 1..N index strips — their first cell is also "1",
    # which would steal the real birth-order / category row keyed "1".
    cand_by_key: Dict[str, int] = {}
    for i, row in enumerate(cand_rows):
        if _row_is_column_index_strip(row):
            continue
        key = _norm_header_key(row[0] if row else "")
        if key and key not in cand_by_key:
            cand_by_key[key] = i
    for li, row in enumerate(llm_rows):
        if _row_is_column_index_strip(row):
            continue
        key = _norm_header_key(row[0] if row else "")
        if not key:
            continue
        ci = cand_by_key.get(key)
        if ci is not None and ci not in used_cand:
            llm_to_cand[li] = ci
            used_cand.add(ci)

    cand_by_fp: Dict[Tuple[str, ...], int] = {}
    for i, row in enumerate(cand_rows):
        if i in used_cand:
            continue
        fp = _row_content_fingerprint(row)
        if fp and fp not in cand_by_fp:
            cand_by_fp[fp] = i
    for li, row in enumerate(llm_rows):
        if llm_to_cand[li] is not None:
            continue
        fp = _row_content_fingerprint(row)
        if not fp:
            continue
        ci = cand_by_fp.get(fp)
        if ci is not None and ci not in used_cand:
            llm_to_cand[li] = ci
            used_cand.add(ci)

    # Keep leading 1..N / (1)(2)(3) reference strips under headers, and any
    # blank-stub measure rows the LLM dropped. Mid-table index strips (between
    # year rows) stay dropped — those are not body data.
    def _is_leading_index_strip(idx: int) -> bool:
        if not _row_is_column_index_strip(cand_rows[idx]):
            return False
        for j in range(idx):
            if not _row_is_column_index_strip(cand_rows[j]):
                return False
        return True

    insert_idxs = {
        i
        for i, row in enumerate(cand_rows)
        if i not in used_cand
        and (
            _is_leading_index_strip(i)
            or (
                _row_has_measure_like_values(row)
                and not _row_is_column_index_strip(row)
            )
        )
    }
    if not insert_idxs:
        return

    cand_to_llm = {ci: li for li, ci in enumerate(llm_to_cand) if ci is not None}
    new_rows: List[List[Any]] = []
    for ci, crow in enumerate(cand_rows):
        if ci in cand_to_llm:
            new_rows.append(llm_rows[cand_to_llm[ci]])
        elif ci in insert_idxs:
            new_rows.append([
                None if _cell_is_empty(v) else str(v)
                for v in crow
            ])
    for li, row in enumerate(llm_rows):
        if llm_to_cand[li] is None:
            new_rows.append(row)

    if len(new_rows) <= len(llm_rows):
        return

    table["rows"] = new_rows
    notes = list(table.get("notes") or [])
    note = (
        "ADDED: restored blank-stub data row(s) from pymupdf candidate "
        "that the LLM reconstruction omitted (e.g. parenthetical percentage rows)."
    )
    if note not in notes:
        notes.append(note)
    table["notes"] = notes


def _stamp_header_meta_on_column(col: Dict[str, Any], m: Dict[str, Any]) -> None:
    fallback = str(col.get("name") or "")
    path = _header_path_from_meta(m, fallback)
    if not path:
        return
    col["header_path"] = path
    col["header_group"] = path[-2] if len(path) >= 2 else None
    leaf = path[-1]
    llm_name = str(col.get("name") or "").strip()
    if leaf and (not llm_name or _norm_header_key(llm_name) != _norm_header_key(leaf)):
        if len(path) >= 2 and (
            " - " in llm_name
            or _norm_header_key(llm_name) == _norm_header_key(f"{path[-2]} {leaf}")
            or _norm_header_key(path[-2]) in _norm_header_key(llm_name)
        ):
            col["name"] = leaf


def _column_from_candidate_meta(m: Dict[str, Any], fallback_name: str = "") -> Dict[str, Any]:
    path = _header_path_from_meta(m, fallback_name or str(m.get("name") or "Col"))
    leaf = path[-1] if path else (fallback_name or "Col")
    return {
        "name": leaf,
        "header_group": path[-2] if len(path) >= 2 else None,
        "header_path": path,
        "role": "unknown",
        "concept": None,
        "description": None,
        "data_type": "unknown",
        "unit": None,
        "category": None,
        "human_review_needed": False,
        "input_type": None,
        "input_options": None,
        "human_review_reason": None,
    }


def _align_llm_rows_to_candidate(
    llm_rows: List[List[Any]],
    df: pd.DataFrame,
) -> List[Optional[int]]:
    """Map each LLM row index -> candidate row index (or None)."""
    cand_rows = df.values.tolist()
    n_llm, n_cand = len(llm_rows), len(cand_rows)
    if n_llm == n_cand:
        return list(range(n_llm))
    if n_cand == 0:
        return [None] * n_llm

    cand_by_key: Dict[str, int] = {}
    for i, row in enumerate(cand_rows):
        if not row:
            continue
        key = _norm_header_key(row[0])
        if key and key not in cand_by_key:
            cand_by_key[key] = i

    aligned: List[Optional[int]] = []
    matched = 0
    for row in llm_rows:
        key = _norm_header_key(row[0] if row else "")
        ci = cand_by_key.get(key)
        if ci is not None:
            matched += 1
        aligned.append(ci)
    if matched >= max(1, int(n_llm * 0.6)):
        return aligned
    return [i if i < n_cand else None for i in range(n_llm)]


def _merge_missing_candidate_columns(
    table: Dict[str, Any],
    df: pd.DataFrame,
    meta: List[Dict[str, Any]],
    mapping: List[Optional[int]],
) -> None:
    """Insert candidate columns the LLM dropped (e.g. trailing rowspan header).

    Walks candidate columns in order; keeps LLM semantics for matched columns
    and synthesizes missing ones from the pymupdf grid + dhara_column_meta.

    Must NOT splice a full candidate grid onto a renamed LLM grid when name
    matching failed — that doubles columns (e.g. '<1…TOTAL' + 'Age <1…').
    """
    columns = list(table.get("columns") or [])
    rows = [list(r) if isinstance(r, list) else [] for r in (table.get("rows") or [])]
    if not columns or not meta:
        return

    meta_to_llm = {
        meta_i: llm_i
        for llm_i, meta_i in enumerate(mapping)
        if meta_i is not None
    }
    matched = len(meta_to_llm)
    match_ratio = matched / max(len(columns), 1)

    missing_meta = []
    for i in range(len(meta)):
        if i in meta_to_llm:
            continue
        fallback = str(df.columns[i]) if i < len(df.columns) else ""
        # pymupdf often emits a second leaf like "North DMC %" beside "North DMC"
        # after flattening a multiline unit. The LLM already kept the real column —
        # do not restore the unit-suffixed clone.
        if _candidate_is_duplicate_of_columns(meta[i], fallback, columns):
            continue
        missing_meta.append(i)
    if not missing_meta:
        return

    # Only restore when the candidate is at least as wide (LLM skipped a col).
    if len(meta) < len(columns):
        return

    # Mapping failure (renames / prefixing), not real omissions: abort rather
    # than restore every candidate column and then append every LLM column.
    if matched == 0:
        return
    if len(missing_meta) > max(2, int(len(meta) * 0.5)) and match_ratio < 0.5:
        return

    cand_vals = df.values.tolist()
    row_map = _align_llm_rows_to_candidate(rows, df)
    missing_set = set(missing_meta)

    new_columns: List[Dict[str, Any]] = []
    sources: List[Tuple[str, int]] = []
    used_llm: set = set()

    for meta_i in range(len(meta)):
        if meta_i in meta_to_llm:
            llm_i = meta_to_llm[meta_i]
            used_llm.add(llm_i)
            new_columns.append(dict(columns[llm_i]))
            sources.append(("llm", llm_i))
        elif meta_i in missing_set:
            m = meta[meta_i]
            fallback = str(df.columns[meta_i]) if meta_i < len(df.columns) else ""
            new_columns.append(_column_from_candidate_meta(m, fallback))
            sources.append(("cand", meta_i))
        # else: unit-suffixed duplicate of an LLM column — drop it

    # Append LLM-only extras only when most LLM columns already mapped onto
    # the candidate (true additions). Low match rate ⇒ leftovers are renames
    # of columns we already restored — appending them doubles the table.
    append_unmatched = match_ratio >= 0.5
    for llm_i, col in enumerate(columns):
        if llm_i not in used_llm and append_unmatched:
            new_columns.append(dict(col))
            sources.append(("llm", llm_i))

    new_rows: List[List[Any]] = []
    for r_i, row in enumerate(rows):
        built: List[Any] = []
        cand_i = row_map[r_i] if r_i < len(row_map) else None
        for kind, idx in sources:
            if kind == "llm":
                built.append(row[idx] if idx < len(row) else None)
            else:
                if cand_i is None or cand_i >= len(cand_vals):
                    built.append(None)
                else:
                    crow = cand_vals[cand_i]
                    val = crow[idx] if idx < len(crow) else None
                    if _cell_is_empty(val):
                        built.append(None)
                    else:
                        built.append(None if isinstance(val, float) and val != val else val)
        new_rows.append(built)

    table["columns"] = new_columns
    table["rows"] = new_rows
    notes = list(table.get("notes") or [])
    note = (
        f"ADDED: restored {len(missing_meta)} column(s) from pymupdf candidate "
        "that the LLM reconstruction omitted (often a trailing rowspan header)."
    )
    if note not in notes:
        notes.append(note)
    table["notes"] = notes



def _attach_structure_from_candidates(
    table: Dict[str, Any],
    candidates: Optional[List[Dict[str, Any]]],
    used: Optional[set] = None,
) -> Dict[str, Any]:
    """Copy multi-level headers / merge empties from pymupdf, and restore any
    columns the LLM dropped (e.g. last rowspan measure). Does not change the
    extraction prompt or overwrite existing LLM cell values for matched cols."""
    cand = _pick_candidate_for_llm_table(table, candidates, used)
    if cand is None:
        return table
    _stamp_bbox_from_candidate(table, cand)
    df = cand["df"]
    meta = _candidate_column_meta(df)
    columns = table.get("columns") or []
    if not columns or not meta:
        return table

    mapping = _map_meta_indices_to_llm_columns(columns, meta, df)
    _merge_missing_candidate_columns(table, df, meta, mapping)

    columns = table.get("columns") or []
    mapping = _map_meta_indices_to_llm_columns(columns, meta, df)

    for llm_i, meta_i in enumerate(mapping):
        if meta_i is None or meta_i >= len(meta):
            continue
        col = columns[llm_i]
        existing = col.get("header_path")
        if isinstance(existing, (list, tuple)) and [p for p in existing if str(p).strip()]:
            if not col.get("header_group") and len(existing) >= 2:
                col["header_group"] = str(existing[-2]).strip() or None
            continue
        _stamp_header_meta_on_column(col, meta[meta_i])
    table["columns"] = columns

    # Prefer candidate body geometry: re-insert blank-stub percentage rows the
    # LLM omitted, then clear forward-filled merge empties on sparse stubs.
    _restore_missing_data_rows_from_candidate(table, df)
    _restore_body_merge_empties_from_df(table, df)
    return table



def _recover_missing_ruled_tables(
    tables: List[Dict[str, Any]],
    candidates: Optional[List[Dict[str, Any]]],
    page_num: int,
    page_text: str,
    used_candidate_idxs: set,
) -> List[Dict[str, Any]]:
    """If the LLM collapsed/omitted distinct ruled tables, restore them.

    When the page has multiple non-overlapping ruled regions but fewer LLM
    tables, rebuild from those ruled candidates (preserving LLM title /
    classification by reading order when available). Does not change how
    cells are extracted — only which physical tables are kept.
    """
    ruled = _distinct_ruled_candidates(candidates)
    if len(ruled) <= 1 or len(tables) >= len(ruled):
        return tables

    cand_list = list(candidates or [])
    out: List[Dict[str, Any]] = []
    for i, rc in enumerate(ruled):
        extra = table_dict_from_df(
            rc["df"],
            page_text=page_text,
            page_num=page_num,
            method=str(rc.get("method") or "pymupdf_lines_strict"),
        )
        extra["page"] = page_num
        if rc.get("bbox") and len(rc["bbox"]) >= 4:
            extra["bbox"] = [float(x) for x in rc["bbox"][:4]]
        # Prefer LLM semantics for the same ordinal when present.
        if i < len(tables):
            src = tables[i]
            llm_title = (src.get("title") or "").strip()
            # Keep heuristic in-grid caption when the LLM only returned a
            # TABLE/STATEMENT id (e.g. "TABLE: B-22").
            if llm_title and not _llm_title_is_id_only(llm_title):
                extra["title"] = src.get("title")
                if src.get("title_source"):
                    extra["title_source"] = src.get("title_source")
            elif llm_title and not (extra.get("title") or "").strip():
                extra["title"] = llm_title
                if src.get("title_source"):
                    extra["title_source"] = src.get("title_source")
            if src.get("description"):
                extra["description"] = src.get("description")
            if isinstance(src.get("classification"), dict) and src.get("classification"):
                extra["classification"] = src.get("classification")
                extra["semantic_status"] = src.get("semantic_status") or "classified"
            else:
                extra["semantic_status"] = "not_classified"
            # Carry column-level semantics when widths match.
            src_cols = src.get("columns") or []
            if len(src_cols) == len(extra.get("columns") or []):
                for j, col in enumerate(extra["columns"]):
                    sc = src_cols[j]
                    for key in (
                        "role", "concept", "description", "data_type", "unit",
                        "category", "human_review_needed", "input_type",
                        "input_options", "human_review_reason",
                    ):
                        if sc.get(key) is not None:
                            col[key] = sc.get(key)
        else:
            extra["semantic_status"] = "not_classified"
            extra["notes"] = list(extra.get("notes") or []) + [
                "ADDED: recovered ruled-border table omitted/collapsed by LLM reconstruction."
            ]

        if (tables and any(
            (t.get("extraction") or {}).get("confidence") == "alignment_guard_fallback"
            for t in tables
        )):
            extra["extraction"] = {
                "method": f"pymupdf_recovered<{rc.get('method')}>",
                "confidence": "alignment_guard_fallback",
            }
        extra = _prefer_descriptive_llm_title(extra, candidates)
        extra["human_review_needed"], extra["human_review_reason"] = derive_human_review_needed(extra)
        out.append(extra)

        for idx, c in enumerate(cand_list):
            if c is rc or _bbox_iou(c.get("bbox"), rc.get("bbox")) >= 0.9:
                used_candidate_idxs.add(idx)
    return out


def _stamp_llm_metadata(
    page_result: Dict[str, Any],
    page_num: int,
    candidates: Optional[List[Dict[str, Any]]] = None,
    page_text: str = "",
) -> Dict[str, Any]:
    """Adds the pipeline-level bookkeeping fields (which extraction path
    produced this, whether it's been semantically classified, whether a
    human needs to review it and why, which page) that we already know
    deterministically -- not something we trust the LLM to self-report.

    ADDED: strips ungrounded Direction/Trend columns, then runs
    _apply_column_alignment_guard, then attaches pymupdf multi-level header
    meta / merge empties, before derive_human_review_needed."""
    # Dedupe strategy clones so attach/guard/recover see one grid per region.
    candidates = dedupe_candidates_by_bbox(list(candidates or []))
    tables = []
    used_candidates: set = set()
    for t in page_result.get("tables", []):
        normalized = _normalize_table(t)
        normalized = _strip_ungrounded_direction_columns(normalized, candidates, page_text)
        normalized = _apply_column_alignment_guard(normalized, candidates, used_candidates)
        if normalized.pop("_skip_structure_attach", False):
            pass
        else:
            normalized = _attach_structure_from_candidates(normalized, candidates, used_candidates)
            normalized["columns"] = dedupe_column_names(normalized.get("columns") or [])
        normalized["semantic_status"] = "classified"
        if not (isinstance(normalized.get("extraction"), dict) and normalized["extraction"].get("confidence") == "alignment_guard_fallback"):
            normalized["extraction"] = {"method": "pymupdf+llm", "confidence": "llm_validated"}
        normalized["page"] = page_num
        if not normalized.get("bbox"):
            matched, _ = _best_matching_ruled_candidate(normalized, candidates, used_candidates)
            _stamp_bbox_from_candidate(
                normalized,
                matched or _best_lines_strict_candidate(candidates),
            )
        normalized = _prefer_descriptive_llm_title(normalized, candidates)
        normalized["human_review_needed"], normalized["human_review_reason"] = derive_human_review_needed(normalized)
        tables.append(normalized)

    tables = _recover_missing_ruled_tables(
        tables, candidates, page_num, page_text, used_candidates
    )
    return {"tables": tables}
