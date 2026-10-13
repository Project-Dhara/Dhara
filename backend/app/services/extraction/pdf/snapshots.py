"""Render and persist per-table PDF snapshot PNGs for review comparison."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

_SNAPSHOT_DPI = 144
_SNAPSHOT_PAD = 8.0
# Batch review table ids look like ``__f0__12-0`` (file index + local page-index id).
_BATCH_TABLE_NS = re.compile(r"^__f(\d+)__(.+)$")


def parse_batch_table_namespace(table_id: str) -> Optional[Tuple[int, str]]:
    """Return ``(file_index, local_table_id)`` for batch-namespaced ids, else None."""
    m = _BATCH_TABLE_NS.match(str(table_id or ""))
    if not m:
        return None
    return int(m.group(1)), m.group(2)


def resolve_snapshot_storage_target(
    job: Mapping[str, Any], table_id: str
) -> Tuple[str, str]:
    """Map a review table id to the job/table keys where snapshots are stored.

    Single-file jobs store under themselves. Batch parent jobs namespace pages as
    ``__f{n}__{page}-{idx}`` while child file jobs store ``{page}-{idx}`` and the
    source PDF bytes — resolve to the child so saved snapshots and pdf_bytes hit.
    """
    job_id = str(job.get("job_id") or "")
    parsed = parse_batch_table_namespace(table_id)
    if not parsed:
        return job_id, str(table_id)

    file_index, local_table_id = parsed
    from app.services.ingestion.review_tables import batch_meta_from_result

    meta = batch_meta_from_result(job.get("result"))
    files: List[Dict[str, Any]] = list(
        meta.get("batch_files") or job.get("batch_files") or []
    )
    if 0 <= file_index < len(files):
        child_id = (files[file_index] or {}).get("file_job_id")
        if child_id:
            return str(child_id), local_table_id
    return job_id, str(table_id)


def physical_page_number(table: Mapping[str, Any], page_s: str) -> int:
    """Page number for PyMuPDF, stripping batch ``__fN__`` prefixes when needed."""
    raw = table.get("page")
    if raw is not None and str(raw).strip() != "":
        return int(raw)
    s = str(page_s)
    m = _BATCH_TABLE_NS.match(s)
    if m:
        return int(m.group(2))
    return int(s)


def render_table_snapshot_png(
    pdf_bytes: bytes,
    *,
    page_num: int,
    bbox: Any = None,
    dpi: int = _SNAPSHOT_DPI,
) -> bytes:
    """Crop one table region (or the full page) from PDF bytes into a PNG."""
    import pymupdf

    if not pdf_bytes:
        raise ValueError("pdf_bytes is empty")
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        if page_num < 1 or page_num > doc.page_count:
            raise ValueError(f"Page {page_num} out of range")
        page = doc[page_num - 1]
        clip = None
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            x0, y0, x1, y1 = (
                float(bbox[0]),
                float(bbox[1]),
                float(bbox[2]),
                float(bbox[3]),
            )
            pad = _SNAPSHOT_PAD
            clip = pymupdf.Rect(
                max(0, x0 - pad),
                max(0, y0 - pad),
                min(page.rect.x1, x1 + pad),
                min(page.rect.y1, y1 + pad),
            )
        pix = page.get_pixmap(clip=clip, dpi=dpi, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def _page_num_for_table(table: Mapping[str, Any], page_key: Any) -> Optional[int]:
    raw = table.get("page", page_key)
    try:
        return int(raw)
    except (TypeError, ValueError):
        try:
            return int(page_key)
        except (TypeError, ValueError):
            return None


def build_snapshots_for_result(
    pdf_bytes: bytes, result: Optional[Dict[Any, Any]]
) -> Dict[str, bytes]:
    """Render a PNG crop for every table in an extraction result."""
    from app.services.ingestion.review_tables import result_pages_only

    pages = result_pages_only(result)
    if not pdf_bytes or not pages:
        return {}

    import pymupdf

    out: Dict[str, bytes] = {}
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page_key, page_data in pages.items():
            tables = (page_data or {}).get("tables") or []
            for idx, table in enumerate(tables):
                table_id = str((table or {}).get("table_id") or f"{page_key}-{idx}")
                page_num = _page_num_for_table(table or {}, page_key)
                if page_num is None:
                    continue
                if page_num < 1 or page_num > doc.page_count:
                    continue
                try:
                    page = doc[page_num - 1]
                    bbox = (table or {}).get("bbox")
                    clip = None
                    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                        x0, y0, x1, y1 = (
                            float(bbox[0]),
                            float(bbox[1]),
                            float(bbox[2]),
                            float(bbox[3]),
                        )
                        pad = _SNAPSHOT_PAD
                        clip = pymupdf.Rect(
                            max(0, x0 - pad),
                            max(0, y0 - pad),
                            min(page.rect.x1, x1 + pad),
                            min(page.rect.y1, y1 + pad),
                        )
                    pix = page.get_pixmap(clip=clip, dpi=_SNAPSHOT_DPI, alpha=False)
                    out[table_id] = pix.tobytes("png")
                except Exception as e:
                    logger.warning(
                        "could not render snapshot for table %s: %s", table_id, e
                    )
    finally:
        doc.close()
    return out


def persist_job_snapshots(
    job_id: str, pdf_bytes: bytes, result: Optional[Dict[Any, Any]]
) -> int:
    """Render and store all table snapshots for a finished PDF job."""
    from app.db.repositories import pdf_jobs as pdf_jobs_repo
    from app.db.session import session_scope

    snapshots = build_snapshots_for_result(pdf_bytes, result)
    if not snapshots:
        return 0
    try:
        with session_scope() as session:
            return pdf_jobs_repo.upsert_table_snapshots(session, job_id, snapshots)
    except Exception as e:
        logger.warning("could not persist snapshots for job %s: %s", job_id, e)
        return 0


def get_or_create_table_snapshot(
    job_id: str,
    table_id: str,
    *,
    pdf_bytes: Optional[bytes] = None,
    page_num: int,
    bbox: Any = None,
    also_save_as: Optional[Tuple[str, str]] = None,
) -> Tuple[Optional[bytes], Optional[str]]:
    """Return saved PNG if present; otherwise render from pdf_bytes and save.

    When ``pdf_bytes`` is omitted, loads them from ``pdf_jobs`` only if no
    saved snapshot exists. Returns ``(png_bytes, error_message)``.

    ``also_save_as`` optionally mirrors the PNG under another (job_id, table_id)
    — used so batch parents keep a namespaced copy after resolving a child job.
    """
    from app.db.repositories import pdf_jobs as pdf_jobs_repo
    from app.db.session import session_scope

    try:
        with session_scope() as session:
            saved = pdf_jobs_repo.get_table_snapshot(session, job_id, table_id)
            if saved:
                if also_save_as and also_save_as != (job_id, table_id):
                    try:
                        pdf_jobs_repo.upsert_table_snapshot(
                            session, also_save_as[0], also_save_as[1], saved
                        )
                    except Exception as e:
                        logger.warning(
                            "could not mirror snapshot to %s/%s: %s",
                            also_save_as[0],
                            also_save_as[1],
                            e,
                        )
                return saved, None
            if pdf_bytes is None:
                pdf_bytes = pdf_jobs_repo.get_pdf_bytes(session, job_id)
    except Exception as e:
        logger.warning(
            "could not load snapshot %s/%s: %s", job_id, table_id, e
        )
        if pdf_bytes is None:
            try:
                with session_scope() as session:
                    pdf_bytes = pdf_jobs_repo.get_pdf_bytes(session, job_id)
            except Exception as e2:
                logger.warning(
                    "could not load PDF bytes for %s: %s", job_id, e2
                )

    if not pdf_bytes:
        return None, (
            "Source PDF is no longer available for snapshots "
            "(re-upload the file to enable comparison)."
        )

    try:
        png = render_table_snapshot_png(
            pdf_bytes, page_num=page_num, bbox=bbox
        )
    except Exception as e:
        return None, f"Could not render snapshot: {e}"

    try:
        with session_scope() as session:
            pdf_jobs_repo.upsert_table_snapshot(session, job_id, table_id, png)
            if also_save_as and also_save_as != (job_id, table_id):
                pdf_jobs_repo.upsert_table_snapshot(
                    session, also_save_as[0], also_save_as[1], png
                )
    except Exception as e:
        logger.warning(
            "could not save snapshot %s/%s: %s", job_id, table_id, e
        )
    return png, None
