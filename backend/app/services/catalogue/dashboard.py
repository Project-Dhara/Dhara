"""Upload readiness snapshot for the Dashboard (catalogue groups + file type)."""
import json
import os
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.classification.classifications import _classification_fill_ratio


def _basename(value: Optional[str]) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    return os.path.basename(s.replace("\\", "/"))


def _infer_source_label(*candidates: Optional[str], fallback: str = "—") -> str:
    """Return a file-type label (PDF / XLSX / CSV / SQL) or fallback.

    Ignores descriptive ``data_source`` text (agency names, report titles,
    doubled OCR) so the Dashboard Source column stays scannable.
    """
    for raw in candidates:
        s = str(raw or "").strip()
        if not s:
            continue
        low = s.lower()
        base = _basename(s).lower()
        # Prefer extension / explicit type tokens over substring matches on prose.
        if base.endswith(".pdf") or low == "pdf" or low.startswith("pdf "):
            return "PDF"
        if (
            base.endswith((".xlsx", ".xls"))
            or low in ("xlsx", "xls", "excel")
            or "spreadsheet" in low
        ):
            return "XLSX"
        if base.endswith(".csv") or low == "csv":
            return "CSV"
        if (
            low in ("sql", "postgres", "postgresql", "database")
            or base.endswith((".sql", ".dump"))
            or low.startswith("postgres://")
            or low.startswith("postgresql://")
        ):
            return "SQL"
        # Narrow keyword hits only when the whole field is short (type-like).
        if len(s) <= 12:
            if "pdf" in low:
                return "PDF"
            if "xlsx" in low or "xls" in low or "excel" in low:
                return "XLSX"
            if "csv" in low:
                return "CSV"
            if "sql" in low:
                return "SQL"
    return fallback


def list_dashboard(session: Session, user_email: str) -> dict:
    """
    Catalogue-side readiness for the Dashboard.

    Used for data-product / published stats and for Excel/SQL rows that have
    no ``pdf_jobs`` upload record. PDF uploads are listed from ``pdf_jobs``
    in ``routes/dashboard.py`` (one row per uploaded file).
    """
    result = session.execute(
        text(
            """
            SELECT
              m.metadata_id,
              m.title,
              m.catalogue_product,
              m.product,
              m.data_source,
              m.metadata_excel,
              m.classifications,
              m.last_updated_date,
              m.user_email,
              (SELECT COUNT(*)::int FROM datasets d WHERE d.metadata_id = m.metadata_id) AS dataset_count
            FROM metadata_groups m
            WHERE m.user_email = :user_email
            ORDER BY m.last_updated_date DESC NULLS LAST, m.metadata_id DESC
            """
        ),
        {"user_email": user_email},
    )
    groups = [dict(r) for r in result.mappings()]

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

        meta_excel = g.get("metadata_excel")
        source = _infer_source_label(meta_excel, g.get("data_source"), fallback="—")
        # Prefer an uploaded workbook name when we have one; else group title.
        file_name = _basename(meta_excel)
        title = (g.get("title") or g["metadata_id"]).strip()
        name = file_name or title
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
            "name": name,
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
            # Placeholder — routes/dashboard.py sets this to upload count.
            "datasets": 0,
            "data_products": len(products),
            "awaiting_review": awaiting,
            "published": published,
        },
        "rows": rows,
    }
