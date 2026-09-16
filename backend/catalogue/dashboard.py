"""Dataset readiness snapshot for the Dashboard (catalogue groups only)."""
import json
from typing import Optional

import psycopg2.extras

from catalogue.classifications import _classification_fill_ratio


def _infer_source_label(data_source: Optional[str], fallback: str = "—") -> str:
    s = str(data_source or "").strip()
    if not s:
        return fallback
    low = s.lower()
    if "pdf" in low:
        return "PDF"
    if low.endswith(".xlsx") or low.endswith(".xls") or "excel" in low or "xlsx" in low:
        return "XLSX"
    if low.endswith(".csv") or "csv" in low:
        return "CSV"
    if "sql" in low or "postgres" in low or "database" in low:
        return "SQL"
    return s[:32]


def list_dashboard(conn, user_email: str) -> dict:
    """
    Dataset readiness snapshot for the Dashboard.

    Catalogue metadata groups only exist after the Metadata push (console
    step 4), so they are always at Classification (5) or Published (6).
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT
              m.metadata_id,
              m.title,
              m.catalogue_product,
              m.product,
              m.data_source,
              m.classifications,
              m.last_updated_date,
              m.user_email,
              (SELECT COUNT(*)::int FROM datasets d WHERE d.metadata_id = m.metadata_id) AS dataset_count
            FROM metadata_groups m
            WHERE m.user_email = %s
            ORDER BY m.last_updated_date DESC NULLS LAST, m.metadata_id DESC
        """, (user_email,))
        groups = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT COUNT(*)::int FROM datasets WHERE user_email = %s
        """, (user_email,))
        dataset_count = cur.fetchone()["count"]

    products = set()
    rows = []
    awaiting = 0
    published = 0

    for g in groups:
        cls = g.get("classifications") or {}
        if isinstance(cls, str):
            try:
                cls = json.loads(cls)
            except json.JSONDecodeError:
                cls = {}
        fill = _classification_fill_ratio(cls)
        has_dims = isinstance(cls, dict) and bool(cls)
        product = (g.get("catalogue_product") or g.get("product") or "").strip()
        if product:
            products.add(product)
        title = (g.get("title") or g["metadata_id"]).strip()
        source = _infer_source_label(g.get("data_source"), "Catalogue")
        ds_n = int(g.get("dataset_count") or 0)

        # Metadata already pushed → never "Metadata review".
        if has_dims and fill >= 0.9:
            status = "Published"
            status_key = "published"
            pct = 100
            action = "View"
            href = "/catalogue"
            published += max(ds_n, 1)
        else:
            status = "Classification review"
            status_key = "classification_review"
            # Step 5 band: 75–95% as definitions are filled in.
            pct = int(round(75 + (fill * 20 if has_dims else 0)))
            action = "Review"
            href = "/console"
            awaiting += 1

        updated = g.get("last_updated_date")
        rows.append({
            "id": g["metadata_id"],
            "kind": "catalogue_group",
            "name": title,
            "source": source,
            "product": product or "—",
            "readiness_pct": pct,
            "status": status,
            "status_key": status_key,
            "action": action,
            "href": href,
            "metadata_id": g["metadata_id"],
            "dataset_count": ds_n,
            "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else updated,
        })

    return {
        "stats": {
            "datasets": dataset_count,
            "data_products": len(products),
            "awaiting_review": awaiting,
            "published": published,
        },
        "rows": rows,
    }
