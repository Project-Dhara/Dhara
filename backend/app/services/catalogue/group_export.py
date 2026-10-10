"""Build a downloadable ZIP for one published metadata group (release).

Each linked table is exported as .xlsx with Code and Definition columns
appended after every classified / harmonised dimension column — looked up
from the steward code lists on the dataset (falling back to the group).
"""
from __future__ import annotations

import json
import zipfile
from io import BytesIO
from typing import Any, Optional

import psycopg2.extras

from app.services.classification.classifications import _normalize_classification_values
from app.services.ingestion.wizard.table_export import safe_download_stem, table_to_excel_bytes


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


def _code_def_names(col: str, taken: set[str]) -> tuple[str, str]:
    """Prefer plain Code / Definition; disambiguate only if those names are taken."""
    if "Code" not in taken and "Definition" not in taken:
        return "Code", "Definition"
    return f"{col} Code", f"{col} Definition"


def _pair_already_present(col: str, columns: list[str]) -> bool:
    """True when Code/Definition (any naming style) already follow this column."""
    try:
        i = columns.index(col)
    except ValueError:
        return False
    if i + 2 >= len(columns):
        return False
    nxt = (columns[i + 1], columns[i + 2])
    return nxt in {
        ("Code", "Definition"),
        (f"{col} Code", f"{col} Definition"),
        (f"{col}_Code", f"{col}_Definition"),
    }


def append_code_definition_columns(
    columns: list[str],
    rows: list[dict],
    classifications: dict,
) -> tuple[list[str], list[dict]]:
    """After each classified column, insert ``Code`` and ``Definition``.

    Values are filled by matching the row's cell against the classification
    code list (case-insensitive). Unmatched cells get empty strings.
    If more than one classified column is present, later pairs are named
    ``{col} Code`` / ``{col} Definition`` so headers stay unique.
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

    new_columns: list[str] = []
    for col in columns:
        new_columns.append(col)
        if col in planned:
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


def build_group_download_zip(conn, metadata_id: str) -> Optional[tuple[bytes, str]]:
    """Return (zip_bytes, filename) — only enriched tables for the group."""
    mid = (metadata_id or "").strip()
    if not mid:
        return None

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT metadata_id, title, classifications
            FROM metadata_groups
            WHERE metadata_id = %s
        """, (mid,))
        group = cur.fetchone()
        if not group:
            return None
        cur.execute("""
            SELECT dataset_id, title, table_id, classifications
            FROM datasets
            WHERE metadata_id = %s
            ORDER BY title ASC NULLS LAST, dataset_id ASC
        """, (mid,))
        datasets = [dict(r) for r in cur.fetchall()]

    group_cls = _parse_json(group.get("classifications"), {})
    if not isinstance(group_cls, dict):
        group_cls = {}

    buf = BytesIO()
    used_names: set[str] = set()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
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
            while name.lower() in used_names:
                name = f"{stem[:70]}_{n}"
                n += 1
            used_names.add(name.lower())
            zf.writestr(f"{name}.xlsx", table_to_excel_bytes(table))

    title = (group.get("title") or mid).strip() or mid
    zip_stem = safe_download_stem({"title": title}, fallback=mid)
    return buf.getvalue(), f"{zip_stem}_tables.zip"
