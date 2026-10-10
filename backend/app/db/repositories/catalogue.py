"""Catalogue read/query helpers (SQLAlchemy Session)."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_MAX_PAGE = 500
_DEFAULT_PAGE = 100
_SAFE_COLUMN = re.compile(r"^[A-Za-z0-9 _.\-/()]{1,120}$")

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

_GROUP_SELECT = """
    SELECT
      m.metadata_id,
      m.title,
      m.description,
      m.product,
      m.category,
      m.geography,
      m.frequency,
      m.time_period,
      m.data_source,
      m.classifications,
      m.sector,
      m.theme,
      m.catalogue_product,
      m.nmds_concepts,
      m.last_updated_date
    FROM metadata_groups m
"""


def _nmds_concepts_as_list(raw: Any) -> list:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict) and "concepts" in raw and isinstance(
        raw.get("concepts"), (list, dict)
    ):
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
        out.append(
            {
                "item_no": row.get("item_no") or "",
                "concept": row.get("concept") or "",
                "code": row.get("code") or "",
                "details": details,
            }
        )
    return out


def _metadata_standard_from_concepts(raw: Any):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if isinstance(raw, dict) and raw.get("standard"):
        return raw.get("standard")
    return None


def _shape_dataset_row(row: dict) -> dict:
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
    summary = (
        (row.get("long_description") or row.get("short_description") or "").strip()
        or title
    )
    tags: list[str] = []
    for x in (
        row.get("theme"),
        row.get("catalogue_product"),
        row.get("sector"),
        row.get("category"),
        geo,
    ):
        if x and str(x).strip() and str(x) not in tags:
            tags.append(str(x).strip())
    for f in facets:
        if f not in tags:
            tags.append(f)
    keywords = " ".join(
        str(x)
        for x in [
            row["dataset_id"],
            title,
            geo,
            freq,
            source,
            row.get("theme"),
            row.get("catalogue_product"),
            *facets,
        ]
        if x
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


def _shape_group_row(row: dict, tables: list) -> dict:
    cls = row.get("classifications") or {}
    if isinstance(cls, str):
        try:
            cls = json.loads(cls)
        except json.JSONDecodeError:
            cls = {}
    if not isinstance(cls, dict):
        cls = {}
    facets = list(cls.keys())
    title = (row.get("title") or row["metadata_id"] or "").strip() or row["metadata_id"]
    geo = row.get("geography") or "—"
    freq = row.get("frequency") or "—"
    source = row.get("data_source") or "—"
    summary = (row.get("description") or "").strip() or title
    table_count = len(tables)
    row_count = sum(int(t.get("row_count") or 0) for t in tables)
    tags: list[str] = []
    for x in (
        row.get("theme"),
        row.get("catalogue_product") or row.get("product"),
        row.get("sector"),
        row.get("category"),
        geo,
    ):
        if x and str(x).strip() and str(x) not in tags:
            tags.append(str(x).strip())
    for f in facets:
        if f not in tags:
            tags.append(f)
    keywords = " ".join(
        str(x)
        for x in [
            row["metadata_id"],
            title,
            geo,
            freq,
            source,
            row.get("theme"),
            row.get("catalogue_product"),
            *facets,
            *(t.get("title") for t in tables),
            *(t.get("dataset_id") or t.get("id") for t in tables),
        ]
        if x
    ).lower()
    nmds = _nmds_concepts_as_list(row.get("nmds_concepts"))
    return {
        "id": row["metadata_id"],
        "kind": "group",
        "metadata_id": row["metadata_id"],
        "title": title,
        "rows": str(row_count),
        "row_count": row_count,
        "table_count": table_count,
        "tables": tables,
        "geo": geo,
        "freq": freq,
        "source": source,
        "access": "Public",
        "summary": summary,
        "short_description": row.get("description") or "",
        "long_description": row.get("description") or "",
        "nmds_concepts": nmds,
        "metadata_standard": _metadata_standard_from_concepts(row.get("nmds_concepts")),
        "keywords": keywords,
        "facets": facets,
        "tags": tags[:16],
        "theme": row.get("theme"),
        "product": row.get("catalogue_product") or row.get("product"),
        "category": row.get("category"),
        "time_period": row.get("time_period"),
        "sector": row.get("sector"),
        "last_updated": str(row.get("last_updated_date") or "") or None,
        "classifications": cls,
    }


def _mappings(result) -> list[dict]:
    return [dict(r) for r in result.mappings().all()]


def list_catalogue_datasets(
    session: Session, *, organisation_id: uuid.UUID | str | None = None
) -> list[dict]:
    if organisation_id is not None:
        rows = _mappings(
            session.execute(
                text(
                    _DATASET_SELECT
                    + """
                WHERE d.organisation_id = :org_id OR d.organisation_id IS NULL
                ORDER BY m.last_updated_date DESC NULLS LAST, d.dataset_id DESC
                """
                ),
                {"org_id": str(organisation_id)},
            )
        )
    else:
        rows = _mappings(
            session.execute(
                text(
                    _DATASET_SELECT
                    + """
                ORDER BY m.last_updated_date DESC NULLS LAST, d.dataset_id DESC
                """
                )
            )
        )
    return [_shape_dataset_row(row) for row in rows]


def _tables_for_group(session: Session, metadata_id: str) -> list:
    rows = _mappings(
        session.execute(
            text(
                """
                SELECT
                  d.dataset_id,
                  d.title,
                  d.table_id,
                  (SELECT COUNT(*)::int FROM dataset_rows r
                    WHERE r.dataset_id = d.dataset_id) AS row_count
                FROM datasets d
                WHERE d.metadata_id = :mid
                ORDER BY d.title ASC NULLS LAST, d.dataset_id ASC
                """
            ),
            {"mid": metadata_id},
        )
    )
    return [
        {
            "id": r["dataset_id"],
            "dataset_id": r["dataset_id"],
            "title": r.get("title") or r["dataset_id"],
            "table_id": r.get("table_id") or r["dataset_id"],
            "row_count": int(r.get("row_count") or 0),
        }
        for r in rows
    ]


def list_catalogue_groups(
    session: Session, *, organisation_id: uuid.UUID | str | None = None
) -> list[dict]:
    if organisation_id is not None:
        groups = _mappings(
            session.execute(
                text(
                    _GROUP_SELECT
                    + """
                WHERE m.organisation_id = :org_id OR m.organisation_id IS NULL
                ORDER BY m.last_updated_date DESC NULLS LAST, m.metadata_id DESC
                """
                ),
                {"org_id": str(organisation_id)},
            )
        )
    else:
        groups = _mappings(
            session.execute(
                text(
                    _GROUP_SELECT
                    + """
                ORDER BY m.last_updated_date DESC NULLS LAST, m.metadata_id DESC
                """
                )
            )
        )
    return [
        _shape_group_row(g, _tables_for_group(session, g["metadata_id"]))
        for g in groups
    ]


def get_catalogue_group(
    session: Session,
    metadata_id: str,
    *,
    organisation_id: uuid.UUID | str | None = None,
):
    mid = (metadata_id or "").strip()
    if not mid:
        return None
    if organisation_id is not None:
        row = session.execute(
            text(
                _GROUP_SELECT
                + """
                WHERE m.metadata_id = :mid
                  AND (m.organisation_id = :org_id OR m.organisation_id IS NULL)
                """
            ),
            {"mid": mid, "org_id": str(organisation_id)},
        ).mappings().first()
    else:
        row = session.execute(
            text(_GROUP_SELECT + " WHERE m.metadata_id = :mid"),
            {"mid": mid},
        ).mappings().first()
    if not row:
        return None
    return _shape_group_row(dict(row), _tables_for_group(session, mid))


def search_catalogue_datasets(
    session: Session,
    *,
    q: str | None = None,
    metadata_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    organisation_id: uuid.UUID | str | None = None,
):
    limit = max(1, min(int(limit or 50), _MAX_PAGE))
    offset = max(0, int(offset or 0))
    datasets = list_catalogue_datasets(session, organisation_id=organisation_id)
    if metadata_id:
        mid = str(metadata_id).strip()
        datasets = [d for d in datasets if (d.get("metadata_id") or "") == mid]
    if q and str(q).strip():
        needle = str(q).strip().lower()
        datasets = [
            d
            for d in datasets
            if needle in (d.get("keywords") or "")
            or needle in (d.get("summary") or "").lower()
            or needle in (d.get("title") or "").lower()
            or needle in (d.get("id") or "").lower()
        ]
    total = len(datasets)
    page = datasets[offset : offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "datasets": page,
    }


def get_catalogue_dataset(
    session: Session,
    dataset_id: str,
    *,
    organisation_id: uuid.UUID | str | None = None,
):
    ds_id = (dataset_id or "").strip()
    if not ds_id:
        return None
    if organisation_id is not None:
        row = session.execute(
            text(
                _DATASET_SELECT
                + """
                WHERE d.dataset_id = :ds_id
                  AND (d.organisation_id = :org_id OR d.organisation_id IS NULL)
                """
            ),
            {"ds_id": ds_id, "org_id": str(organisation_id)},
        ).mappings().first()
    else:
        row = session.execute(
            text(_DATASET_SELECT + " WHERE d.dataset_id = :ds_id"),
            {"ds_id": ds_id},
        ).mappings().first()
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
    session: Session,
    dataset_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
    column: str | None = None,
    equals: str | None = None,
    contains: str | None = None,
    organisation_id: uuid.UUID | str | None = None,
):
    ds_id = (dataset_id or "").strip()
    if not ds_id:
        raise ValueError("dataset_id is required")
    meta = get_catalogue_dataset(
        session, ds_id, organisation_id=organisation_id
    )
    if not meta:
        return None

    limit, offset = _clamp_page(limit, offset)
    col = _validate_column(column)
    if (equals is not None or contains is not None) and not col:
        raise ValueError("column is required when using equals or contains")

    where = ["dataset_id = :ds_id"]
    params: dict[str, Any] = {"ds_id": ds_id, "limit": limit, "offset": offset}
    if col and equals is not None:
        where.append("row_data ->> :col = :equals")
        params["col"] = col
        params["equals"] = str(equals)
    elif col and contains is not None:
        where.append("row_data ->> :col ILIKE :contains")
        params["col"] = col
        params["contains"] = f"%{contains}%"

    where_sql = " AND ".join(where)
    total = int(
        session.execute(
            text(f"SELECT COUNT(*)::int AS n FROM dataset_rows WHERE {where_sql}"),
            params,
        ).scalar_one()
    )
    fetched = _mappings(
        session.execute(
            text(
                f"""
                SELECT sl_no, row_index, row_data
                FROM dataset_rows
                WHERE {where_sql}
                ORDER BY row_index ASC NULLS LAST, id ASC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    )

    rows = []
    columns: list[str] = []
    seen: set[str] = set()
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
        rows.append(
            {
                "sl_no": r.get("sl_no"),
                "row_index": r.get("row_index"),
                "data": data,
            }
        )

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
        }
        if col
        else None,
    }


def tag_publish_organisation(
    session: Session,
    *,
    metadata_id: str,
    organisation_id: uuid.UUID | str,
) -> None:
    """Set organisation_id on a newly published group and its datasets."""
    org = str(organisation_id)
    session.execute(
        text(
            """
            UPDATE metadata_groups
               SET organisation_id = CAST(:org AS uuid)
             WHERE metadata_id = :mid
               AND organisation_id IS NULL
            """
        ),
        {"org": org, "mid": metadata_id},
    )
    session.execute(
        text(
            """
            UPDATE datasets
               SET organisation_id = CAST(:org AS uuid)
             WHERE metadata_id = :mid
               AND organisation_id IS NULL
            """
        ),
        {"org": org, "mid": metadata_id},
    )
    session.flush()
