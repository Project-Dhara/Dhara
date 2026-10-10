"""Background job registry — re-exports extraction upload workers."""
from app.workers import extraction_jobs as _extraction

_pdf_jobs = _extraction._pdf_jobs
_pdf_jobs_lock = _extraction._pdf_jobs_lock

__all__ = [
    "_pdf_jobs",
    "_pdf_jobs_lock",
    "_get_pdf_bytes",
    "_get_pdf_job",
    "_hydrate_user_pdf_jobs",
    "_list_pdf_jobs_for_user",
    "_load_pdf_job",
    "_normalize_pdf_header_name",
    "_parse_pdf_table_id",
    "_pdf_job_public",
    "_pdf_merged_tables_for_job",
    "_pdf_table_header_key",
    "_pdf_table_sort_key",
    "_pdf_tables_from_job",
    "_run_extraction_job",
    "_run_pdf_job",
    "_save_pdf_job",
    "queue_extraction_job",
]

for _name in __all__:
    if _name.startswith("_") or _name == "queue_extraction_job":
        globals()[_name] = getattr(_extraction, _name)
