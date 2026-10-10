"""Compatibility shim — GCS uploads live in ``app.storage.object_store``."""
from app.storage.object_store import (  # noqa: F401
    upload_bytes_to_gcs as _upload_bytes_to_gcs,
    upload_excel_to_gcs as _upload_excel_to_gcs,
    upload_original_sheet_to_gcs as _upload_original_sheet_to_gcs,
    upload_table_excel_to_gcs as _upload_table_excel_to_gcs,
)

__all__ = [
    "_upload_bytes_to_gcs",
    "_upload_excel_to_gcs",
    "_upload_original_sheet_to_gcs",
    "_upload_table_excel_to_gcs",
]
