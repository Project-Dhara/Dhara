"""Build pandas DataFrames from extracted PDF table row grids."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, Tuple

from app.services.extraction.pdf.utils.caption import (
    _blank,
    _cell_str,
    _is_descriptive_in_grid_title,
    _is_leaf_header_token,
    _is_measurement_number,
    _is_table_id_only,
    _pad_row,
    _row_is_column_number_strip,
    _row_is_full_width_banner,
    extract_in_grid_caption,
)

from app.services.extraction.pdf.utils.header_detect import (
    _fill_blank_leading_serial_header,
    _recover_placeholder_column_headers,
    _row_is_header_metadata_strip,
    _row_is_section_label,
    _row_is_subheader,
    _row_is_text_header,
    _row_looks_like_data,
    _split_hybrid_leaf_data_row,
    _uniquify_columns,
    detect_header_rows,
    resolve_column_headers,
)

from app.services.extraction.pdf.utils.grid_repair import (
    _find_sex_column,
    coalesce_phantom_grid_columns,
    collapse_split_grid_columns,
    expand_collapsed_sex_pair_rows,
    fold_header_label_wrap_rows,
    fold_label_wrap_continuation_rows,
    fold_orphan_parenthetical_share_rows,
    repair_glued_numeric_cells,
    repair_sex_pair_next_row_label_bleed,
)

_ORDER_LEAF_TOKEN_RE = re.compile(
    r"^(?:\d+|>\s*\d+|≥\s*\d+|\d+\+|not\s*stated|ns|total|all)$",
    re.I,
)
_BAND_LEAF_TOKEN_RE = re.compile(
    r"^(?:<\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?|\d+\+|"
    r"not\s*stated|total|13\s*&\s*above)$",
    re.I,
)
_DURATION_OF_PREFIX_RE = re.compile(r"^Duration\s+of\s+", re.I)
_UNIT_PHRASE_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9/.\-]*(?:\s+[A-Za-z][A-Za-z0-9/.\-]*){0,4})\s*(\([^)]{1,24}\))",
)
# Orphan crumbs left when multi-word leaves are split across lines in the mash.
_ORPHAN_LEAF_CRUMB_RE = re.compile(
    r"(?i)(?<![A-Za-z])(?:\d+\s*&\s*|above|stated|not(?=\s|$))(?![A-Za-z])",
)


def _is_order_band_or_short_leaf(v: str) -> bool:
    """True for birth-order / band codes and short leaves (Wet, Male), not axis titles."""
    flat = re.sub(r"\s+", " ", _cell_str(v)).strip()
    if not flat:
        return False
    if _ORDER_LEAF_TOKEN_RE.match(flat) or _BAND_LEAF_TOKEN_RE.match(flat):
        return True
    # ``_is_leaf_header_token`` accepts any short text (Crop, Area (Ha), …).
    # Order strips only use very short leaf words under a spanning group.
    if len(flat) > 12 or len(flat.split()) > 2:
        return False
    return bool(_is_leaf_header_token(v))


def _looks_like_order_leaf_strip(row: Sequence[Any], n_cols: int) -> bool:
    """Leaf strip under a spanning group: short codes / bands + Not stated / Total.

    Reject real column-header rows (Sl.No. | Crop | Area (Ha) | …) and
    parent/group headers (Block | Panchayat | Autumn | …). Those must not
    drive jammed-caption unmash of the table title banner.
    """
    padded = _pad_row(row, n_cols)
    non_empty = [_cell_str(v) for v in padded if _cell_str(v)]
    if len(non_empty) < max(3, int(n_cols * 0.4)):
        return False
    if sum(1 for v in non_empty if _is_measurement_number(v)) >= 2:
        return False
    # Unit-bearing headers (Area (Ha), Production (Tonnes)) are measure columns.
    if any(re.search(r"\([^)]{1,20}\)", v) for v in non_empty):
        return False
    # Long non-code labels are stub/group headers, not birth-order leaves.
    for v in non_empty:
        flat = re.sub(r"\s+", " ", v).strip()
        if len(flat) <= 24:
            continue
        if _is_order_band_or_short_leaf(v):
            continue
        return False
    leafish = sum(1 for v in non_empty if _is_order_band_or_short_leaf(v))
    return leafish >= max(3, int(len(non_empty) * 0.55))


def _raw_mash_text(text: Any) -> str:
    """Keep newlines in corner-mash cells (``_cell_str`` flattens them)."""
    if text is None:
        return ""
    return str(text).replace("\r\n", "\n").replace("\r", "\n").strip()


def _corner_mash_text(row: Sequence[Any], n_cols: int) -> Optional[str]:
    """Return cell-0 text when it is the only non-empty cell (corner mash)."""
    padded = _pad_row(row, n_cols)
    nonempty_idxs = [i for i, v in enumerate(padded) if _cell_str(v)]
    if len(nonempty_idxs) != 1 or nonempty_idxs[0] != 0:
        return None
    text = _raw_mash_text(padded[0])
    flat = re.sub(r"\s+", " ", text).strip()
    if len(flat) < 10:
        return None
    if "\n" not in text and len(flat.split()) < 4 and len(flat) < 24:
        return None
    return text


def _leaf_labels_from_strip(row: Sequence[Any], n_cols: int) -> List[str]:
    padded = _pad_row(row, n_cols)
    return [_cell_str(v) for v in padded if _cell_str(v)]


def _looks_like_leaf_pack_fragment(text: str) -> bool:
    """True for residual crumbs like ``1 2 3 4+`` (not prose such as ``Age of``)."""
    toks = [t for t in re.split(r"\s+", text.strip()) if t]
    if len(toks) < 2:
        return False
    codeish = sum(
        1
        for t in toks
        if _ORDER_LEAF_TOKEN_RE.match(t) or _BAND_LEAF_TOKEN_RE.match(t)
    )
    return codeish >= max(2, int(len(toks) * 0.75))


def _strip_leaf_labels_from_text(text: str, leaf_labels: Sequence[str]) -> str:
    """Remove sibling leaf labels (and split crumbs) that leaked into the mash."""
    out = re.sub(r"\n+", "\n", _raw_mash_text(text))
    ordered = sorted((_cell_str(x) for x in leaf_labels), key=len, reverse=True)
    for lab in ordered:
        if not lab:
            continue
        esc = re.escape(lab).replace(r"\ ", r"\s+")
        pat = re.compile(rf"(?<![\w.]){esc}(?![\w.])", re.I)
        out = pat.sub(" ", out)
    # Dense integer packs dumped into the corner cell (1 2 3 … 12).
    out = re.sub(r"(?m)(?:^|\s)(?:\d{1,2}\s+){3,}\d{1,2}(?:\s|&)*(?=\s|$)", " ", out)
    out = _ORPHAN_LEAF_CRUMB_RE.sub(" ", out)
    lines: List[str] = []
    for line in out.split("\n"):
        flat = re.sub(r"\s+", " ", line).strip(" \t|&")
        if not flat:
            continue
        if _looks_like_leaf_pack_fragment(flat):
            continue
        lines.append(flat)
    return "\n".join(lines).strip()


def _join_wrap_lines(lines: Sequence[str]) -> List[str]:
    """Join lowercase / unit-only continuations onto the previous phrase."""
    out: List[str] = []
    for line in lines:
        s = re.sub(r"\s+", " ", line).strip()
        if not s:
            continue
        if out and (
            s[:1].islower()
            or re.fullmatch(r"\([^)]+\)", s)
            or (len(s.split()) <= 2 and s[:1].islower())
        ):
            out[-1] = f"{out[-1]} {s}".strip()
        else:
            out.append(s)
    return out


def _normalize_header_key(s: str) -> str:
    return re.sub(r"\s+", " ", _cell_str(s)).strip().lower()


def _split_duration_of_interleaved(residual: str) -> Optional[Tuple[str, str]]:
    """``Duration of <Group (unit)> <stub rest>`` → (stub, group)."""
    flat = re.sub(r"\s+", " ", residual).strip()
    m = _DURATION_OF_PREFIX_RE.match(flat)
    if not m:
        return None
    rest = flat[m.end():].strip()
    units = list(_UNIT_PHRASE_RE.finditer(rest))
    if not units:
        return None
    first = units[0]
    group = f"{first.group(1).strip()} {first.group(2).strip()}".strip()
    after = rest[first.end():].strip()
    before = rest[: first.start()].strip()
    stub_core = " ".join(p for p in (before, after) if p).strip()
    if not stub_core:
        return None
    stub = re.sub(r"\s+", " ", f"Duration of {stub_core}").strip()
    if _normalize_header_key(stub) == _normalize_header_key(group):
        return None
    return stub, group


def _split_two_capital_phrases(flat: str) -> Optional[Tuple[str, str]]:
    """Split flattened residual on the second Title-case token start."""
    tokens = flat.split()
    cap_idxs = [
        i for i, t in enumerate(tokens)
        if t[:1].isupper() and not t.startswith("(")
    ]
    if len(cap_idxs) < 2:
        return None
    cut = cap_idxs[1]
    if cut < 1:
        return None
    left = " ".join(tokens[:cut]).strip()
    right = " ".join(tokens[cut:]).strip()
    if not left or not right:
        return None
    return left, right


def _phrases_stub_and_group(residual: str) -> Tuple[Optional[str], Optional[str]]:
    """Split mash residual into row-stub + column-group (topic-agnostic)."""
    if not residual:
        return None, None
    interleaved = _split_duration_of_interleaved(re.sub(r"\s+", " ", residual))
    if interleaved:
        return interleaved

    raw_lines = [ln.strip() for ln in residual.split("\n") if ln.strip()]
    phrases = _join_wrap_lines(raw_lines) if len(raw_lines) >= 2 else []
    if len(phrases) >= 2:
        # Reading order in jammed corners: group banner, then stub axis.
        group, stub = phrases[0], " ".join(phrases[1:]).strip()
        if stub and group and _normalize_header_key(stub) != _normalize_header_key(group):
            return stub, group

    flat = re.sub(r"\s+", " ", residual).strip()
    two = _split_two_capital_phrases(flat)
    if two:
        group, stub = two[0], two[1]
        if stub and group and _normalize_header_key(stub) != _normalize_header_key(group):
            return stub, group
    if phrases:
        return phrases[0], None
    return (flat or None), None


def _split_flat_n_headers(text: str, n_cols: int) -> Optional[List[str]]:
    """Split a flat jammed header into ``n_cols`` Title-case phrases."""
    if n_cols < 2:
        return None
    flat = re.sub(r"[\n\r]+", " ", _cell_str(text))
    flat = re.sub(r"\s+", " ", flat).strip()
    tokens = flat.split()
    if len(tokens) < n_cols:
        return None
    cap_idxs = [i for i, t in enumerate(tokens) if t[:1].isupper()]
    if len(cap_idxs) < n_cols:
        return None
    starts = [0] + cap_idxs[-(n_cols - 1) :]
    uniq: List[int] = []
    for s in starts:
        if not uniq or s > uniq[-1]:
            uniq.append(s)
    if len(uniq) != n_cols:
        uniq = cap_idxs[:n_cols]
        if len(uniq) != n_cols:
            return None
    parts: List[str] = []
    for k, start in enumerate(uniq):
        end = uniq[k + 1] if k + 1 < len(uniq) else len(tokens)
        if end <= start:
            return None
        parts.append(" ".join(tokens[start:end]).strip())
    if any(not p for p in parts):
        return None
    if sum(1 for p in parts if _is_measurement_number(p)) >= 1:
        return None
    return parts


def _looks_like_data_measure_cell(v: Any) -> bool:
    s = _cell_str(v)
    if not s:
        return False
    if _is_measurement_number(s):
        return True
    return bool(re.fullmatch(r"\d+\.\d+", s.replace(",", "")))


def _row_is_measure_data_row(row: Sequence[Any], n_cols: int) -> bool:
    padded = _pad_row(row, n_cols)
    non_empty = [_cell_str(v) for v in padded if _cell_str(v)]
    if len(non_empty) < 2:
        return False
    return sum(1 for v in padded if _looks_like_data_measure_cell(v)) >= max(
        1, n_cols - 2
    )


def _find_following_leaf_strip(
    rows: List[List[Any]], start: int, n_cols: int,
) -> Optional[int]:
    for j in range(start + 1, min(start + 4, len(rows))):
        if _blank(rows[j]):
            continue
        if _looks_like_order_leaf_strip(rows[j], n_cols) or _looks_like_birth_order_leaf_strip(
            rows[j], n_cols
        ):
            return j
        return None
    return None


def _row_is_jammed_multilevel_header(row: Sequence[Any], n_cols: int) -> bool:
    """True when a corner mash sits in cell 0 (topic-agnostic shape check)."""
    return _corner_mash_text(row, n_cols) is not None


def repair_jammed_multilevel_header_rows(
    rows: List[List[Any]],
    n_cols: int,
) -> List[List[Any]]:
    """Unmash corner headers using leaf-strip alignment (not topic phrases).

    Critical: col-0 must become the *stub residual* after leaf labels are
    removed — never the raw mash (``stub or text0`` was the prior bug).

    Parent/group header rows (Block | Panchayat | Autumn | …) are not treated
    as leaf strips, so descriptive title banners above them are left intact
    instead of being split into fake column headers.
    """
    if not rows or n_cols < 2:
        return rows
    out = [_pad_row(r, n_cols) for r in rows]
    for i in range(min(4, len(out))):
        text0 = _corner_mash_text(out[i], n_cols)
        if not text0:
            continue

        # Full-width TABLE-id / descriptive title above real column headers
        # (Sl.No. | Crop | …) must stay a caption — not be split into stub+group.
        # Still allow unmash when the next row is measure data or a true
        # order/band leaf strip (birth-order / education jam cases).
        if _row_is_full_width_banner(out[i]) and (
            _is_table_id_only(text0) or _is_descriptive_in_grid_title(text0)
        ):
            next_i = i + 1
            while next_i < len(out) and _blank(out[next_i]):
                next_i += 1
            if next_i < len(out):
                nxt = out[next_i]
                if not (
                    _row_is_measure_data_row(nxt, n_cols)
                    or _looks_like_order_leaf_strip(nxt, n_cols)
                    or _looks_like_birth_order_leaf_strip(nxt, n_cols)
                ):
                    continue

        flat_parts = _split_flat_n_headers(text0, n_cols)
        if flat_parts:
            next_i = i + 1
            while next_i < len(out) and _blank(out[next_i]):
                next_i += 1
            if next_i < len(out) and _row_is_measure_data_row(out[next_i], n_cols):
                out[i] = flat_parts
                break

        if n_cols < 4:
            continue
        leaf_i = _find_following_leaf_strip(out, i, n_cols)
        if leaf_i is None:
            continue
        leaf_labels = _leaf_labels_from_strip(out[leaf_i], n_cols)
        residual = _strip_leaf_labels_from_text(text0, leaf_labels)
        stub, group = _phrases_stub_and_group(residual)
        if stub:
            stub = re.sub(
                r"\s+", " ", _strip_leaf_labels_from_text(stub, leaf_labels)
            ).strip()
        if group:
            group = re.sub(
                r"\s+", " ", _strip_leaf_labels_from_text(group, leaf_labels)
            ).strip()
        if not stub and residual:
            stub = re.sub(r"\s+", " ", residual).strip()
        if not stub and not group:
            continue
        rebuilt = [None] * n_cols
        # Never fall back to the raw mash for col-0 — that was the UI bug.
        if stub and group:
            rebuilt[0] = stub
            rebuilt[1] = group
        elif stub:
            rebuilt[0] = stub
        else:
            rebuilt[0] = group
        out[i] = rebuilt
        leaf = list(_pad_row(out[leaf_i], n_cols))
        if _cell_str(rebuilt[0]) and not _cell_str(leaf[0]):
            leaf[0] = None
        out[leaf_i] = leaf
        break
    return out


def _looks_like_birth_order_leaf_strip(row: Sequence[Any], n_cols: int) -> bool:
    """True for Sl.No. / age-stub / 1,2,…,>8,All header strips parked as data."""
    padded = _pad_row(row, n_cols)
    non_empty = [v for v in padded if _cell_str(v)]
    if len(non_empty) < max(4, int(n_cols * 0.5)):
        return False
    if sum(1 for v in non_empty if _is_measurement_number(v)) >= 2:
        return False
    # Reject bare 1..N / (1)(2)(3) index strips — those are not leaf headers.
    if all(
        bool(re.match(r"^\(?\d+\)?$", _cell_str(v).replace(" ", "")))
        for v in non_empty
    ):
        return False
    leafish = sum(1 for v in non_empty if _is_leaf_header_token(v))
    if leafish < max(3, int(len(non_empty) * 0.55)):
        return False
    # Need a serial / stub label plus several short order codes.
    has_serial = any(
        re.match(r"^(?:sl\.?\s*no\.?|s\.?\s*no\.?|sno)$", _cell_str(v), re.I)
        for v in non_empty
    )
    order_codes = sum(
        1 for v in non_empty
        if re.match(r"^(?:\d+|>\s*8|≥\s*8|all)$", _cell_str(v).replace(" ", ""), re.I)
    )
    return bool(has_serial and order_codes >= 3)

def _promote_leading_leaf_strip(
    header_matrix: List[List[Any]],
    header_count: int,
    padded: List[List[Any]],
    skip_rows: List[int],
    n_cols: int,
) -> Tuple[List[List[Any]], int, List[List[Any]]]:
    """Pull a misplaced 1..>8 leaf strip from the first body row into headers."""
    next_i = header_count
    while next_i < len(padded) and (next_i in skip_rows or _blank(padded[next_i])):
        next_i += 1
    if next_i >= len(padded):
        return header_matrix, header_count, padded
    candidate = padded[next_i]
    if not _looks_like_birth_order_leaf_strip(candidate, n_cols):
        return header_matrix, header_count, padded
    # Already have distinct short leaves under the group — nothing to promote.
    if header_matrix:
        last = header_matrix[-1]
        last_non_empty = [v for v in last if _cell_str(v)]
        if (
            len(last_non_empty) >= max(4, int(n_cols * 0.5))
            and sum(1 for v in last_non_empty if _is_leaf_header_token(v))
            >= max(3, int(len(last_non_empty) * 0.55))
        ):
            return header_matrix, header_count, padded
    new_matrix = list(header_matrix) + [_pad_row(candidate, n_cols)]
    return new_matrix, next_i + 1, padded

def _recover_stub_from_caption(
    leaf_names: List[str],
    column_meta: List[dict],
    caption_title: Optional[str],
) -> Tuple[List[str], List[dict]]:
    """Rename a truncated age stub using the descriptive caption.

    PyMuPDF often splits ``AGE OF MOTHER`` across header rows (``AGE OF`` on
    the group row, ``MOTHER`` on the leaf). Stub resolution keeps only the
    parent token; restore the full phrase when the caption clearly has it.
    """
    title = _cell_str(caption_title).upper()
    if not title or "MOTHER" not in title:
        return leaf_names, column_meta
    full = None
    if "AGE OF THE MOTHER" in title:
        full = "AGE OF THE MOTHER"
    elif "AGE OF MOTHER" in title:
        full = "AGE OF MOTHER"
    if not full:
        return leaf_names, column_meta
    names = list(leaf_names)
    meta = [dict(m) for m in column_meta]
    for i, name in enumerate(names):
        u = str(name).strip().upper()
        if u not in {"MOTHER", "AGE OF", "AGE OF THE"}:
            continue
        names[i] = full
        if i < len(meta):
            meta[i]["name"] = full
            path = [str(p) for p in (meta[i].get("header_path") or []) if str(p).strip()]
            if path:
                path[-1] = full
            else:
                path = [full]
            meta[i]["header_path"] = path
        break
    return names, meta

def dataframe_from_extracted_rows(rows: Optional[List[List[Any]]]):
    """
    Build a pandas DataFrame from a pymupdf `tab.extract()` grid, flattening
    multi-row / merged headers when present.

    Hierarchy is stored on ``df.attrs["dhara_column_meta"]`` as
    ``[{"name", "header_group", "header_path"}, ...]`` for Preview.
    """
    import pandas as pd

    if not rows:
        return pd.DataFrame()

    n_cols = max((len(r) for r in rows), default=0)
    if n_cols == 0:
        return pd.DataFrame()

    # Expand collapsed M/F stacks while newlines still exist; then unglue
    # horizontally packed measure values into neighbouring empty columns.
    padded = expand_collapsed_sex_pair_rows([_pad_row(r, n_cols) for r in rows])
    n_cols = max((len(r) for r in padded), default=n_cols)
    sex_col = _find_sex_column(padded, n_cols)
    # Also repair already-separate rows where a next-disease title bled into
    # the empty F stub (common with wrapped Name cells).
    padded = repair_sex_pair_next_row_label_bleed(padded, sex_col)
    padded = repair_glued_numeric_cells([_pad_row(r, n_cols) for r in padded])
    # Looser ruled extracts bisect one cell into several columns (serials and
    # names alternate; Wet/Dry/Total land beside their values). Collapse that
    # before header detection, or body rows get read as extra header levels
    # and Block is glued into the panchayat column.
    padded = collapse_split_grid_columns([_pad_row(r, n_cols) for r in padded])
    n_cols = max((len(r) for r in padded), default=n_cols)
    padded = [_pad_row(r, n_cols) for r in padded]
    # Fold ``Experiments not`` + ``conducted due to`` style wrap rows before
    # header detection — otherwise the lowercase line looks like a section band.
    padded = fold_header_label_wrap_rows(padded)
    n_cols = max((len(r) for r in padded), default=n_cols)
    padded = [_pad_row(r, n_cols) for r in padded]
    # Unmash Age of mother / Birth order (+ leaf codes) jammed into cell 0.
    padded = repair_jammed_multilevel_header_rows(padded, n_cols)
    padded = [_pad_row(r, n_cols) for r in padded]
    header_count, skip_rows = detect_header_rows(padded, n_cols)

    root = None
    for i in range(header_count):
        if i not in skip_rows and not _blank(padded[i]):
            # Crop/season/appendix strips are not useful parent rows for
            # stub/data classification of later body candidates.
            if _row_is_header_metadata_strip(padded[i]):
                continue
            root = padded[i]
            break

    # Pull any remaining subheader strips that follow the detected block.
    while True:
        next_i = header_count
        while next_i < len(padded) and next_i in skip_rows:
            next_i += 1
        if next_i >= len(padded):
            break
        # District / group bands stay in the body. They are a single label
        # with empty measure cells, which otherwise looks like another header.
        if _row_is_section_label(padded[next_i]):
            break
        if root is not None:
            leaf_part, data_part = _split_hybrid_leaf_data_row(padded[next_i], root, n_cols)
            if leaf_part is not None and data_part is not None:
                padded[next_i] = leaf_part
                padded.insert(next_i + 1, data_part)
                header_count = next_i + 1
                break
        if _row_looks_like_data(padded[next_i], root):
            break
        if _row_is_subheader(padded[next_i], root) or _row_is_text_header(
            padded[next_i], continuation=True, parent_row=root
        ):
            header_count = next_i + 1
            if root is None and not _row_is_header_metadata_strip(padded[next_i]):
                root = padded[next_i]
            continue
        break

    header_matrix = [padded[i] for i in range(header_count) if i not in skip_rows]
    if not header_matrix:
        header_matrix = [padded[0]]
        header_count = 1

    # When a group banner (education / BIRTH ORDER) absorbed "AGE OF" into the
    # header and the real leaf strip (Sl.No. / MOTHER / 1..>8) was treated as
    # data, promote that first body row back into the header block.
    header_matrix, header_count, padded = _promote_leading_leaf_strip(
        header_matrix, header_count, padded, skip_rows, n_cols
    )

    resolved = resolve_column_headers(header_matrix, n_cols)
    # DataFrame labels must be unique for pandas; API/editor `name` keeps the
    # real leaf (repeated "Total" under Oil Seeds / Fibre / Plantation).
    leaf_names = _uniquify_columns([c["name"] for c in resolved])
    column_meta = []
    for i in range(n_cols):
        path = [str(p) for p in (resolved[i].get("header_path") or []) if str(p).strip()]
        if not path:
            path = [resolved[i].get("name") or leaf_names[i]]
        display_leaf = str(path[-1] if path else (resolved[i].get("name") or leaf_names[i]))
        column_meta.append({
            "name": display_leaf,
            "header_group": path[-2] if len(path) >= 2 else None,
            "header_path": path,
        })
    leaf_names, column_meta = _fill_blank_leading_serial_header(leaf_names, column_meta)

    body = [
        padded[i]
        for i in range(header_count, len(padded))
        if i not in skip_rows and not _blank(padded[i])
    ]
    # Index strips (1..N / (1)(2)(3)) are skipped for header naming but must
    # remain visible as the first body row(s) when they sit under the headers.
    leading_index: List[List[Any]] = []
    for i in range(header_count, len(padded)):
        if i not in skip_rows:
            break
        if _blank(padded[i]):
            continue
        if _row_is_column_number_strip(padded[i], n_cols):
            leading_index.append(padded[i])
        else:
            # Non-index skip (banner) — stop; don't pull mid-table strips forward.
            break
    if leading_index:
        body = leading_index + body
    caption = extract_in_grid_caption(padded)
    leaf_names, column_meta = _recover_stub_from_caption(
        leaf_names, column_meta, caption.get("title")
    )
    # Recover Col_1 / Col_2 stubs from body shape (Rural/Urban, S.No.+District,
    # Age of mother bands) and attach Birth order parents when appropriate.
    leaf_names, column_meta = _recover_placeholder_column_headers(
        leaf_names, column_meta, body,
    )
    # Keep DataFrame labels unique after renames (Total / Total under groups).
    leaf_names = _uniquify_columns(
        [str((column_meta[i].get("name") if i < len(column_meta) else n) or n)
         for i, n in enumerate(leaf_names)]
    )

    def _attach_caption_attrs(frame):
        frame.attrs["dhara_column_meta"] = column_meta
        if caption.get("title"):
            frame.attrs["dhara_table_caption"] = caption["title"]
        if caption.get("table_id_label"):
            frame.attrs["dhara_banner_table_id"] = caption["table_id_label"]
        return frame

    if not body:
        df = pd.DataFrame(columns=leaf_names)
        return _attach_caption_attrs(df)

    clean_body: List[List[Any]] = [
        [_cell_str(v) or None for v in row] for row in body
    ]
    df = pd.DataFrame(clean_body, columns=leaf_names)
    df = _attach_caption_attrs(df)
    # Collapse PyMuPDF interstitial phantom columns (Cause/(2)/(3), Male/(2)/(3))
    # and fold stub-only wrap rows into the parent disease row.
    df = coalesce_phantom_grid_columns(df)
    df = fold_label_wrap_continuation_rows(df)
    df = fold_orphan_parenthetical_share_rows(df)
    return df

__all__ = [
    "dataframe_from_extracted_rows",
]
