"""Build a downloadable ZIP for one published metadata group (release).

Each linked table is exported as .xlsx with Code and Definition columns
appended at the end for every classified / harmonised dimension column —
looked up from the steward code lists on the dataset (falling back to the
group). LGD / NCO columns use standard-aware code headers. Each workbook
also includes Metadata and NMDS sheets for the release.
"""
from __future__ import annotations

import json
import re
import zipfile
from io import BytesIO
from typing import Any, Optional

import psycopg2.extras

from app.services.classification.classifications import _normalize_classification_values
from app.services.ingestion.wizard.table_export import safe_download_stem, table_to_excel_bytes

# Catalogue fields written to the Metadata sheet (label, db column).
_METADATA_SHEET_FIELDS: tuple[tuple[str, str], ...] = (
    ("title", "title"),
    ("product", "product"),
    ("category", "category"),
    ("geography", "geography"),
    ("frequency", "frequency"),
    ("time_period", "time_period"),
    ("data_source", "data_source"),
    ("description", "description"),
    ("last_updated", "last_updated_date"),
    ("future_release", "future_release"),
    ("key_statistics", "key_statistics"),
    ("remarks", "remarks"),
    ("sector", "sector"),
    ("theme", "theme"),
)


def _metadata_pairs_from_group(group: dict) -> list[tuple[str, Any]]:
    pairs: list[tuple[str, Any]] = []
    for label, key in _METADATA_SHEET_FIELDS:
        val = group.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            # Still include blank so the sheet is complete for steward review.
            pairs.append((label, ""))
        else:
            pairs.append((label, val))
    return pairs


def _nmds_pairs_from_raw(raw: Any) -> list[tuple[str, Any]]:
    """Flatten nmds_concepts JSON into Field / Value rows."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    # Wrapped { standard, concepts }
    if isinstance(raw, dict) and "concepts" in raw:
        concepts = raw.get("concepts")
        if isinstance(concepts, dict):
            return [
                (str(k), "" if v is None else v)
                for k, v in concepts.items()
                if k != "standard"
            ]
        if isinstance(concepts, list):
            raw = concepts
        else:
            return []
    if isinstance(raw, dict):
        return [
            (str(k), "" if v is None else v)
            for k, v in raw.items()
            if k != "standard"
        ]
    pairs: list[tuple[str, Any]] = []
    if isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict):
                continue
            concept = str(row.get("concept") or row.get("field") or "").strip()
            details = row.get("details")
            if details is None:
                details = row.get("value") or row.get("code") or ""
            if not concept and not str(details or "").strip():
                continue
            label = concept or str(row.get("item_no") or "concept")
            pairs.append((label, details if details is not None else ""))
    return pairs


def _parse_json(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, type(fallback)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _lookup_maps(classifications: dict) -> dict[str, dict[str, tuple[str, str]]]:
    """column_name → {normalized_value → (code, definition)}."""
    out: dict[str, dict[str, tuple[str, str]]] = {}
    if not isinstance(classifications, dict):
        return out
    for name, codes in classifications.items():
        if not name:
            continue
        mapping: dict[str, tuple[str, str]] = {}
        for entry in _normalize_classification_values(codes):
            key = _norm_key(entry.get("value"))
            if not key or key in mapping:
                continue
            mapping[key] = (
                str(entry.get("code") or "").strip(),
                str(entry.get("definition") or "").strip(),
            )
        if mapping:
            out[str(name)] = mapping
    return out


# Mirror frontend/src/lib/classifyColumns.js occupation / LGD heuristics.
_OCCUPATION_ID_TOKENS = frozenset({"id", "code", "number", "no", "num", "key"})
_LGD_ID_TOKENS = frozenset({"id", "code", "number", "no", "num", "key"})
_LGD_NAME_RE = re.compile(
    r"(?:^|_)(?:state|district|sub[_\s-]?districts?|tehsils?|taluks?|blocks?|"
    r"villages?|wards?|local[_\s-]?bod(?:y|ies)|municipalit(?:y|ies)|"
    r"corporations?|cantonments?|panchayats?|lgd)(?:_|$)",
    re.IGNORECASE,
)
_LGD_GEO_TOKEN_RE = re.compile(
    r"^(?:state|district|subdistrict|tehsil|taluk|block|village|ward|"
    r"municipality|corporation|cantonment|panchayat|lgd)$"
)

NCO_CODE_HEADER = "NCO 2015 codes"
LGD_CODE_HEADER = "LGD codes"


def _is_occupation_column(name: str) -> bool:
    raw = str(name or "")
    if re.search(r"occupat", raw, re.IGNORECASE):
        return True
    tokens = [t for t in re.split(r"[^a-z]+", raw.lower()) if t]
    if "job" not in tokens and "jobs" not in tokens:
        return False
    return not any(t in _OCCUPATION_ID_TOKENS for t in tokens)


def _is_lgd_column(name: str) -> bool:
    raw = str(name or "").strip()
    if not raw:
        return False
    if _is_occupation_column(raw):
        return False
    if re.search(r"lgd", raw, re.IGNORECASE):
        return True
    underscored = re.sub(r"\s+", "_", raw)
    if not _LGD_NAME_RE.search(raw) and not _LGD_NAME_RE.search(underscored):
        return False
    tokens = [t for t in re.split(r"[^a-z0-9]+", raw.lower()) if t]
    if len(tokens) <= 2 and any(t in _LGD_ID_TOKENS for t in tokens):
        geo = any(
            _LGD_GEO_TOKEN_RE.match(t) or t in {"local", "body", "bodies"}
            for t in tokens
        )
        if geo and any(t in _LGD_ID_TOKENS for t in tokens):
            return False
    return True


def _preferred_code_header(col: str) -> str:
    if _is_occupation_column(col):
        return NCO_CODE_HEADER
    if _is_lgd_column(col):
        return LGD_CODE_HEADER
    return "Code"


def _unique_header(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    n = 2
    while f"{base} ({n})" in taken:
        n += 1
    return f"{base} ({n})"


def _code_def_names(col: str, taken: set[str]) -> tuple[str, str]:
    """Standard-aware Code header + always-Definition; uniquify with (2), (3), …"""
    code_name = _unique_header(_preferred_code_header(col), taken)
    def_name = _unique_header("Definition", taken | {code_name})
    return code_name, def_name


def _header_matches_preferred(name: str, preferred: str) -> bool:
    if name == preferred:
        return True
    return bool(re.fullmatch(re.escape(preferred) + r" \(\d+\)", name))


def _is_definition_header(name: str) -> bool:
    return name == "Definition" or bool(re.fullmatch(r"Definition \(\d+\)", name))


def _pair_already_present(col: str, columns: list[str]) -> bool:
    """True when enrichment for this column is already in the grid.

    Covers legacy mid-table inserts (immediately after the source column) and
    end-append layouts with NCO / LGD / Code (+ uniquified) headers followed
    by a Definition header. A bare data column named ``Code`` does not count.
    """
    try:
        i = columns.index(col)
    except ValueError:
        return False
    preferred = _preferred_code_header(col)
    if i + 2 < len(columns):
        nxt = (columns[i + 1], columns[i + 2])
        if nxt in {
            ("Code", "Definition"),
            (preferred, "Definition"),
            (f"{col} Code", f"{col} Definition"),
            (f"{col}_Code", f"{col}_Definition"),
        }:
            return True
        if _header_matches_preferred(columns[i + 1], preferred) and _is_definition_header(
            columns[i + 2]
        ):
            return True
    # End-append: preferred code header family appears after this column with
    # an adjacent Definition pair (not a coincidental data column named Code).
    for j in range(i + 1, len(columns) - 1):
        if _header_matches_preferred(columns[j], preferred) and _is_definition_header(
            columns[j + 1]
        ):
            return True
        if columns[j] in {f"{col} Code", f"{col}_Code"} and columns[j + 1] in {
            f"{col} Definition",
            f"{col}_Definition",
        }:
            return True
    return False


def append_code_definition_columns(
    columns: list[str],
    rows: list[dict],
    classifications: dict,
) -> tuple[list[str], list[dict]]:
    """Append ``Code`` / ``Definition`` pairs at the end for classified columns.

    Original column order is preserved. Values are filled by matching each
    row's source cell against the classification code list (case-insensitive).
    Unmatched cells get empty strings. Code headers use NCO / LGD / Code by
    column-name heuristics; Definition stays ``Definition`` (uniquified).
    """
    lookups = _lookup_maps(classifications)
    if not lookups or not columns:
        return columns, rows

    # Only enrich columns that appear in both the table and the code lists.
    # Skip if Code/Definition were already appended (re-download safety).
    enrich_cols = []
    taken = set(columns)
    planned: dict[str, tuple[str, str]] = {}
    for col in columns:
        if col not in lookups:
            continue
        if _pair_already_present(col, columns):
            continue
        code_name, def_name = _code_def_names(col, taken)
        if code_name in taken or def_name in taken:
            continue
        enrich_cols.append(col)
        planned[col] = (code_name, def_name)
        taken.add(code_name)
        taken.add(def_name)
    if not enrich_cols:
        return columns, rows

    new_columns = list(columns)
    for col in enrich_cols:
        code_name, def_name = planned[col]
        new_columns.append(code_name)
        new_columns.append(def_name)

    new_rows: list[dict] = []
    for row in rows:
        out = dict(row)
        for col in enrich_cols:
            code_name, def_name = planned[col]
            code, definition = lookups[col].get(_norm_key(row.get(col)), ("", ""))
            out[code_name] = code
            out[def_name] = definition
        new_rows.append(out)
    return new_columns, new_rows


def _columns_and_rows_from_dataset(conn, dataset_id: str) -> tuple[list[str], list[dict]]:
    """Rebuild column order + dict rows from published dataset_rows."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT row_data
            FROM dataset_rows
            WHERE dataset_id = %s
            ORDER BY row_index ASC NULLS LAST, id ASC
        """, (dataset_id,))
        raw_rows = [r["row_data"] for r in cur.fetchall()]

    columns: list[str] = []
    seen: set[str] = set()
    rows: list[dict] = []
    for raw in raw_rows:
        data = _parse_json(raw, {})
        if not isinstance(data, dict):
            data = {"value": data}
        for k in data.keys():
            if k not in seen:
                seen.add(k)
                columns.append(str(k))
        rows.append(data)
    return columns, rows


def _merge_classifications(primary: dict, fallback: dict) -> dict:
    """Prefer per-dataset lists; fill missing columns from the group."""
    merged = dict(fallback or {})
    for name, codes in (primary or {}).items():
        if codes:
            merged[name] = codes
    return merged


def _load_group_and_datasets(conn, metadata_id: str) -> Optional[tuple[dict, list[dict]]]:
    """Load one metadata group and its linked datasets (with table_ids fallback)."""
    mid = (metadata_id or "").strip()
    if not mid:
        return None

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT metadata_id, title, description, product, category, geography,
                   frequency, time_period, data_source, last_updated_date,
                   future_release, key_statistics, remarks, sector, theme,
                   classifications, nmds_concepts, table_ids
            FROM metadata_groups
            WHERE metadata_id = %s
        """, (mid,))
        group = cur.fetchone()
        if not group:
            return None
        group = dict(group)
        cur.execute("""
            SELECT dataset_id, title, table_id, classifications
            FROM datasets
            WHERE metadata_id = %s
            ORDER BY title ASC NULLS LAST, dataset_id ASC
        """, (mid,))
        datasets = [dict(r) for r in cur.fetchall()]
        # Fallback: older rows may list table_ids on the group but miss metadata_id
        # on some datasets — still include every id from the release inventory.
        linked_ids = {str(d["dataset_id"]) for d in datasets}
        raw_ids = group.get("table_ids") or []
        if isinstance(raw_ids, str):
            try:
                raw_ids = json.loads(raw_ids)
            except json.JSONDecodeError:
                raw_ids = []
        missing = [
            str(i).strip()
            for i in (raw_ids or [])
            if str(i).strip() and str(i).strip() not in linked_ids
        ]
        if missing:
            cur.execute("""
                SELECT dataset_id, title, table_id, classifications
                FROM datasets
                WHERE dataset_id = ANY(%s)
                ORDER BY title ASC NULLS LAST, dataset_id ASC
            """, (missing,))
            for row in cur.fetchall():
                d = dict(row)
                if str(d["dataset_id"]) not in linked_ids:
                    datasets.append(d)
                    linked_ids.add(str(d["dataset_id"]))

    seen_ds: set[str] = set()
    unique_datasets: list[dict] = []
    for d in datasets:
        did = str(d.get("dataset_id") or "")
        if not did or did in seen_ds:
            continue
        seen_ds.add(did)
        unique_datasets.append(d)
    return group, unique_datasets


def _write_group_tables_to_zip(
    zf: zipfile.ZipFile,
    conn,
    group: dict,
    datasets: list[dict],
    *,
    path_prefix: str,
    used_names: set[str],
) -> None:
    """Append one group's enriched table workbooks into an open ZIP."""
    group_cls = _parse_json(group.get("classifications"), {})
    if not isinstance(group_cls, dict):
        group_cls = {}
    metadata_pairs = _metadata_pairs_from_group(group)
    nmds_pairs = _nmds_pairs_from_raw(group.get("nmds_concepts"))
    prefix = path_prefix or ""

    for ds in datasets:
        columns, rows = _columns_and_rows_from_dataset(conn, ds["dataset_id"])
        ds_cls = _parse_json(ds.get("classifications"), {})
        if not isinstance(ds_cls, dict):
            ds_cls = {}
        classifications = _merge_classifications(ds_cls, group_cls)
        columns, rows = append_code_definition_columns(columns, rows, classifications)
        table = {
            "title": ds.get("title") or ds["dataset_id"],
            "table_id": ds.get("table_id") or ds["dataset_id"],
            "id": ds["dataset_id"],
            "columns": columns,
            "rows": rows,
        }
        stem = safe_download_stem(table, fallback=ds["dataset_id"])
        name = stem
        n = 2
        while f"{prefix}{name}.xlsx".lower() in used_names:
            name = f"{stem[:70]}_{n}"
            n += 1
        arc = f"{prefix}{name}.xlsx"
        used_names.add(arc.lower())
        zf.writestr(
            arc,
            table_to_excel_bytes(
                table,
                metadata_pairs=metadata_pairs,
                nmds_pairs=nmds_pairs,
            ),
        )


def build_groups_download_zip(conn, metadata_ids: list[str]) -> Optional[tuple[bytes, str]]:
    """ZIP every enriched table across one or more published metadata groups.

    Multiple groups → `{group_stem}/{table}.xlsx`. One group → flat `{table}.xlsx`.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for raw in metadata_ids or []:
        mid = str(raw or "").strip()
        if mid and mid not in seen:
            seen.add(mid)
            ids.append(mid)
    if not ids:
        return None

    loaded: list[tuple[str, dict, list[dict]]] = []
    for mid in ids:
        pair = _load_group_and_datasets(conn, mid)
        if pair:
            loaded.append((mid, pair[0], pair[1]))
    if not loaded:
        return None

    nest = len(loaded) > 1
    buf = BytesIO()
    used_names: set[str] = set()
    used_prefixes: set[str] = set()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for mid, group, datasets in loaded:
            prefix = ""
            if nest:
                gstem = safe_download_stem(
                    {"title": (group.get("title") or mid).strip() or mid},
                    fallback=mid,
                )
                folder = gstem
                n = 2
                while folder.lower() in used_prefixes:
                    folder = f"{gstem[:70]}_{n}"
                    n += 1
                used_prefixes.add(folder.lower())
                prefix = f"{folder}/"
            _write_group_tables_to_zip(
                zf, conn, group, datasets, path_prefix=prefix, used_names=used_names
            )

    first_mid, first_group, _ = loaded[0]
    title = (first_group.get("title") or first_mid).strip() or first_mid
    zip_stem = safe_download_stem({"title": title}, fallback=first_mid)
    suffix = "_all_tables.zip" if nest else "_tables.zip"
    return buf.getvalue(), f"{zip_stem}{suffix}"


def build_group_download_zip(conn, metadata_id: str) -> Optional[tuple[bytes, str]]:
    """Return (zip_bytes, filename) — only enriched tables for one group."""
    return build_groups_download_zip(conn, [metadata_id])
