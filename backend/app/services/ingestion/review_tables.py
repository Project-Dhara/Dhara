"""Canonical review-table shape for Console / PdfReview (PDF, Excel, CSV)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

BATCH_META_KEY = "__batch_meta__"


def batch_meta_from_result(result: Optional[Dict[Any, Any]]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    meta = result.get(BATCH_META_KEY)
    return meta if isinstance(meta, dict) else {}


def result_pages_only(result: Optional[Dict[Any, Any]]) -> Dict[Any, Any]:
    if not isinstance(result, dict):
        return {}
    return {k: v for k, v in result.items() if k != BATCH_META_KEY}


def source_location_label(table: Dict[str, Any]) -> Optional[str]:
    """Human-readable source location for review cards."""
    st = (table.get("source_type") or "").lower()
    if st == "pdf":
        page = table.get("page")
        if page is not None and str(page).strip():
            return f"Page {page}"
        return None
    if st == "excel":
        sheet = (table.get("sheet") or "").strip()
        if sheet:
            return f"Sheet {sheet}"
        return None
    if st == "csv":
        return "CSV rows"
    return None


def enrich_table_for_review(
    table: Dict[str, Any],
    *,
    table_id: str,
    page_key: Any,
    source_filename: Optional[str] = None,
    source_file_id: Optional[str] = None,
    batch_id: Optional[str] = None,
) -> Dict[str, Any]:
    out = {
        **table,
        "table_id": table_id,
        # Alias used at publish / catalogue — same human-readable id.
        "dataset_id": table.get("dataset_id") or table_id,
        "page": table.get("page", page_key),
    }
    if source_filename and not out.get("source_filename"):
        out["source_filename"] = source_filename
    if source_file_id and not out.get("source_file_id"):
        out["source_file_id"] = source_file_id
    if batch_id and not out.get("batch_id"):
        out["batch_id"] = batch_id
    loc = source_location_label(out)
    if loc:
        out["source_location"] = loc
    return out


def flatten_job_result_to_review_tables(
    job: Dict[str, Any],
    *,
    default_filename: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Flatten page-keyed extraction result into review tables (with reviews merged)."""
    from app.services.ingestion.table_ids import (
        build_review_table_id,
        dataset_id_config_from_job,
        parse_batch_page_key,
        physical_page_value,
    )

    reviews = dict(job.get("reviews") or {})
    deleted = set(job.get("deleted_table_ids") or [])
    result = result_pages_only(job.get("result"))
    batch_id = job.get("job_id")
    filename = default_filename or job.get("filename")
    cfg = dataset_id_config_from_job(job)
    meta = batch_meta_from_result(job.get("result"))
    batch_files = list(meta.get("batch_files") or job.get("batch_files") or [])
    tables: List[Dict[str, Any]] = []
    for page_num in sorted(result.keys(), key=lambda k: int(k) if str(k).isdigit() else str(k)):
        page_tables = (result.get(page_num) or {}).get("tables") or []
        tables_on_page = len(page_tables)
        for idx, t in enumerate(page_tables):
            file_index, _phys = parse_batch_page_key(page_num)
            src_name = t.get("source_filename") or t.get("source_file") or filename
            src_type = t.get("source_type") or job.get("source_type") or "pdf"
            if file_index is not None and 0 <= file_index < len(batch_files):
                entry = batch_files[file_index] or {}
                src_name = entry.get("filename") or src_name
                src_type = entry.get("source_type") or src_type
            table_id = str(t.get("table_id") or "").strip() or build_review_table_id(
                config=cfg,
                source_filename=src_name,
                source_type=str(src_type or "pdf"),
                page=physical_page_value(t, page_num),
                index=idx,
                tables_on_page=tables_on_page,
                file_index=file_index,
            )
            if table_id in deleted:
                continue
            # Also honor legacy deletes keyed by opaque page-index ids.
            legacy_id = f"{page_num}-{idx}"
            if legacy_id in deleted:
                continue
            merged = enrich_table_for_review(
                {**t, **reviews.get(table_id, {}), **reviews.get(legacy_id, {})},
                table_id=table_id,
                page_key=page_num,
                source_filename=src_name,
                source_file_id=t.get("source_file_id"),
                batch_id=t.get("batch_id") or batch_id,
            )
            tables.append(merged)
    return tables


def namespace_page_key(file_index: int, page_key: Any) -> str:
    return f"__f{file_index}__{page_key}"


def merge_file_result_into_batch(
    batch_result: Dict[Any, Any],
    file_index: int,
    file_result: Dict[Any, Any],
    *,
    source_filename: str,
    source_file_id: str,
    source_type: str,
) -> None:
    """Merge one file's page-keyed result into a batch aggregate (in place)."""
    for page_key, page in (file_result or {}).items():
        ns_key = namespace_page_key(file_index, page_key)
        tables = []
        for t in page.get("tables") or []:
            tables.append(
                {
                    **t,
                    "source_type": t.get("source_type") or source_type,
                    "source_filename": source_filename,
                    "source_file": source_filename,
                    "source_file_id": source_file_id,
                }
            )
        batch_result[ns_key] = {**(page or {}), "tables": tables}


def attach_batch_meta(result: Dict[Any, Any], meta: Dict[str, Any]) -> Dict[Any, Any]:
    out = dict(result or {})
    out[BATCH_META_KEY] = meta
    return out
