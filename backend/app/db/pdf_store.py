"""Compatibility re-export of PDF persistence (SQLAlchemy).

Prefer ``app.db.repositories.pdf_jobs`` directly in new code.
All callables take ``session: Session`` as the first argument.
"""
from app.db.repositories.pdf_jobs import (
    CLASSIFICATION_FIELDS,
    classification_dict,
    flatten_classification_text,
    get_job,
    get_pdf_bytes,
    get_pipeline_step,
    list_active_tables,
    list_working_jobs,
    load_grouping,
    load_working_job,
    persist_approved_tables,
    save_grouping,
    save_working_job,
    set_pipeline_step,
    upsert_job,
)

__all__ = [
    "CLASSIFICATION_FIELDS",
    "classification_dict",
    "flatten_classification_text",
    "upsert_job",
    "save_working_job",
    "load_working_job",
    "list_working_jobs",
    "get_pdf_bytes",
    "set_pipeline_step",
    "get_pipeline_step",
    "persist_approved_tables",
    "list_active_tables",
    "get_job",
    "save_grouping",
    "load_grouping",
]
