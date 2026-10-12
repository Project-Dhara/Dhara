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
    reviews = dict(job.get("reviews") or {})
    deleted = set(job.get("deleted_table_ids") or [])
    result = result_pages_only(job.get("result"))
    batch_id = job.get("job_id")
    filename = default_filename or job.get("filename")
    tables: List[Dict[str, Any]] = []
    for page_num in sorted(result.keys(), key=lambda k: int(k) if str(k).isdigit() else str(k)):
        for idx, t in enumerate((result.get(page_num) or {}).get("tables") or []):
            table_id = f"{page_num}-{idx}"
            if table_id in deleted:
                continue
            merged = enrich_table_for_review(
                {**t, **reviews.get(table_id, {})},
                table_id=table_id,
                page_key=page_num,
                source_filename=t.get("source_filename") or t.get("source_file") or filename,
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
