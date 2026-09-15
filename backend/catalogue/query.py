"""Read-only catalogue queries shared by REST (and future MCP) surfaces.

List/transform logic lives here so routes and other callers do not duplicate
SQL or response shaping. Write paths stay in ``datasets.push_to_catalogue``.
"""
import json

import psycopg2.extras


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


def list_catalogue_datasets(conn):
    """Published datasets for the catalogue page (everything in `datasets`)."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
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
            ORDER BY m.last_updated_date DESC NULLS LAST, d.dataset_id DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]

    out = []
    for row in rows:
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
        out.append({
            "id": row["dataset_id"],
            "title": title,
            "rows": str(row.get("row_count") or 0),
            "geo": geo,
            "freq": freq,
            "source": source,
            "access": "Public",
            "summary": summary,
            "nmds_concepts": nmds,
            "metadata_standard": _metadata_standard_from_concepts(row.get("nmds_concepts")),
            "keywords": keywords,
            "facets": facets,
            "tags": tags[:16],
            "theme": row.get("theme"),
            "product": row.get("catalogue_product"),
            "time_period": row.get("time_period"),
            "metadata_id": row.get("metadata_id"),
        })
    return out
