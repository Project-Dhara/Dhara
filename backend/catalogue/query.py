"""Read-only catalogue queries shared by REST and MCP surfaces.

List/transform logic lives here so routes and other callers do not duplicate
SQL or response shaping. Write paths stay in ``datasets.push_to_catalogue``.
"""
from __future__ import annotations

import json
import re

import psycopg2.extras

_MAX_PAGE = 500
_DEFAULT_PAGE = 100
_SAFE_COLUMN = re.compile(r"^[A-Za-z0-9 _.\-/()]{1,120}$")


def _nmds_concepts_as_list(raw):
    """Normalise stored concept JSON (list of rows, {concept: details}, or wrapped {standard, concepts})."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict) and "concepts" in raw and isinstance(raw.get("concepts"), (list, dict)):
        return _nmds_concepts_as_list(raw.get("concepts"))
    if isinstance(raw, dict):
        return [
            {"item_no": "", "concept": k, "code": "", "details": v or ""}
            for k, v in raw.items()
            if k != "standard" and str(v or "").strip()
        ]
    out = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        details = row.get("details") or ""
        if not str(details).strip():
            continue
        out.append({
            "item_no": row.get("item_no") or "",
            "concept": row.get("concept") or "",
            "code": row.get("code") or "",
            "details": details,
        })
    return out


def _metadata_standard_from_concepts(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if isinstance(raw, dict) and raw.get("standard"):
        return raw.get("standard")
    return None


def _shape_dataset_row(row):
    """Map a SQL join row into the catalogue/API dataset card shape."""
    cls = row.get("classifications") or {}
    if isinstance(cls, str):
        try:
            cls = json.loads(cls)
        except json.JSONDecodeError:
            cls = {}
    facets = list(cls.keys()) if isinstance(cls, dict) else []
    title = row.get("title") or row["dataset_id"]
    geo = row.get("geography") or "—"
    freq = row.get("frequency") or "—"
    source = row.get("data_source") or "—"
    summary = (row.get("long_description") or row.get("short_description") or "").strip() or title
    tags = []
    for x in (row.get("theme"), row.get("catalogue_product"), row.get("sector"), row.get("category"), geo):
        if x and str(x).strip() and str(x) not in tags:
            tags.append(str(x).strip())
    for f in facets:
        if f not in tags:
            tags.append(f)
    keywords = " ".join(
        str(x) for x in [
            row["dataset_id"], title, geo, freq, source,
            row.get("theme"), row.get("catalogue_product"), *facets,
        ] if x
    ).lower()
    nmds = _nmds_concepts_as_list(row.get("nmds_concepts"))
    return {
        "id": row["dataset_id"],
        "title": title,
        "rows": str(row.get("row_count") or 0),
        "row_count": int(row.get("row_count") or 0),
        "geo": geo,
        "freq": freq,
        "source": source,
        "access": "Public",
        "summary": summary,
        "short_description": row.get("short_description") or "",
        "long_description": row.get("long_description") or "",
        "nmds_concepts": nmds,
        "metadata_standard": _metadata_standard_from_concepts(row.get("nmds_concepts")),
        "keywords": keywords,
        "facets": facets,
        "tags": tags[:16],
        "theme": row.get("theme"),
        "product": row.get("catalogue_product"),
        "category": row.get("category"),
        "time_period": row.get("time_period"),
        "metadata_id": row.get("metadata_id"),
        "sector": row.get("sector"),
        "last_updated": str(row.get("last_updated_date") or "") or None,
        "classifications": cls if isinstance(cls, dict) else {},
    }


_DATASET_SELECT = """
    SELECT
      d.dataset_id,
      d.title,
      d.short_description,
      d.long_description,
      d.geography,
      d.frequency,
      d.time_period,
      d.data_source,
      d.classifications,
      d.category,
      d.metadata_id,
      m.sector,
      m.theme,
      m.catalogue_product,
      m.nmds_concepts,
      m.last_updated_date,
      (SELECT COUNT(*)::int FROM dataset_rows r WHERE r.dataset_id = d.dataset_id) AS row_count
    FROM datasets d
    LEFT JOIN metadata_groups m ON m.metadata_id = d.metadata_id
"""


def list_catalogue_datasets(conn):
    """Published datasets for the catalogue page (everything in `datasets`)."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_DATASET_SELECT + """
            ORDER BY m.last_updated_date DESC NULLS LAST, d.dataset_id DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
    return [_shape_dataset_row(row) for row in rows]


def search_catalogue_datasets(
    conn,
    *,
    q: str | None = None,
    metadata_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """Discover published datasets with optional text / metadata_id filters."""
    limit = max(1, min(int(limit or 50), _MAX_PAGE))
    offset = max(0, int(offset or 0))
    datasets = list_catalogue_datasets(conn)
    if metadata_id:
        mid = str(metadata_id).strip()
        datasets = [d for d in datasets if (d.get("metadata_id") or "") == mid]
    if q and str(q).strip():
        needle = str(q).strip().lower()
        datasets = [
            d for d in datasets
            if needle in (d.get("keywords") or "")
            or needle in (d.get("summary") or "").lower()
            or needle in (d.get("title") or "").lower()
            or needle in (d.get("id") or "").lower()
        ]
    total = len(datasets)
    page = datasets[offset: offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "datasets": page,
    }


def get_catalogue_dataset(conn, dataset_id: str):
    """Return one published dataset or None."""
    ds_id = (dataset_id or "").strip()
    if not ds_id:
        return None
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            _DATASET_SELECT + " WHERE d.dataset_id = %s",
            (ds_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return _shape_dataset_row(dict(row))


def _clamp_page(limit, offset):
    limit = max(1, min(int(limit if limit is not None else _DEFAULT_PAGE), _MAX_PAGE))
    offset = max(0, int(offset or 0))
    return limit, offset


def _validate_column(column: str | None):
    if column is None or not str(column).strip():
        return None
    col = str(column).strip()
    if not _SAFE_COLUMN.match(col):
        raise ValueError(
            "Invalid column name. Use letters, numbers, spaces, and ._-()/ only."
        )
    return col


def query_dataset_rows(
    conn,
    dataset_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
    column: str | None = None,
    equals: str | None = None,
    contains: str | None = None,
):
    """Page over published ``dataset_rows`` with optional JSONB field filter.

    Filters are equality or case-insensitive substring on a single ``row_data``
    key — never free-form SQL.
    """
    ds_id = (dataset_id or "").strip()
    if not ds_id:
        raise ValueError("dataset_id is required")
    meta = get_catalogue_dataset(conn, ds_id)
    if not meta:
        return None

    limit, offset = _clamp_page(limit, offset)
    col = _validate_column(column)
    if (equals is not None or contains is not None) and not col:
        raise ValueError("column is required when using equals or contains")

    where = ["dataset_id = %s"]
    params: list = [ds_id]
    if col and equals is not None:
        where.append("row_data ->> %s = %s")
        params.extend([col, str(equals)])
    elif col and contains is not None:
        where.append("row_data ->> %s ILIKE %s")
        params.extend([col, f"%{contains}%"])

    where_sql = " AND ".join(where)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT COUNT(*)::int AS n FROM dataset_rows WHERE {where_sql}", params)
        total = int(cur.fetchone()["n"])
        cur.execute(
            f"""
            SELECT sl_no, row_index, row_data
            FROM dataset_rows
            WHERE {where_sql}
            ORDER BY row_index ASC NULLS LAST, id ASC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        fetched = [dict(r) for r in cur.fetchall()]

    rows = []
    columns: list[str] = []
    seen = set()
    for r in fetched:
        data = r.get("row_data") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {"value": data}
        if not isinstance(data, dict):
            data = {"value": data}
        for k in data.keys():
            if k not in seen:
                seen.add(k)
                columns.append(k)
        rows.append({
            "sl_no": r.get("sl_no"),
            "row_index": r.get("row_index"),
            "data": data,
        })

    return {
        "dataset_id": ds_id,
        "title": meta.get("title"),
        "total": total,
        "limit": limit,
        "offset": offset,
        "columns": columns,
        "rows": rows,
        "filter": {
            "column": col,
            "equals": equals,
            "contains": contains,
        } if col else None,
    }
