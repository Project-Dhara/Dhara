"""Optional GCS uploads for catalogue/PDF exports.

GCS is opt-in so local/dev can push catalogue rows to Neon without a
bucket. Set ENABLE_GCS=true (and GCS_BUCKET_NAME) for production Excel
uploads. Placeholder bucket names are treated as unset.
"""
import os
from typing import Optional

_GCS_SKIP_LOGGED = False


def _gcs_enabled() -> bool:
    return os.getenv("ENABLE_GCS", "").strip().lower() in ("1", "true", "yes")


def _gcs_bucket_name() -> str:
    name = os.getenv("GCS_BUCKET_NAME", "").strip()
    if not name or name.startswith("your_"):
        return ""
    return name


def _upload_bytes_to_gcs(file_bytes: bytes, blob_name: str) -> Optional[str]:
    """Upload bytes to GCS, or return None when GCS is disabled (local/dev)."""
    global _GCS_SKIP_LOGGED
    if not _gcs_enabled():
        if not _GCS_SKIP_LOGGED:
            print("GCS uploads skipped (ENABLE_GCS is not true). Catalogue rows will still be written to Postgres.")
            _GCS_SKIP_LOGGED = True
        return None

    from google.cloud import storage as gcs
    bucket_name = _gcs_bucket_name()
    if not bucket_name:
        raise ValueError(
            "ENABLE_GCS is true but GCS_BUCKET_NAME is not set. "
            "Set GCS_BUCKET_NAME, or set ENABLE_GCS=false for Neon-only local testing."
        )
    client = gcs.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(file_bytes, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return f"gs://{bucket_name}/{blob_name}"


def _upload_excel_to_gcs(file_bytes: bytes, filename: str) -> Optional[str]:
    """Upload a metadata workbook and return the gs:// URL, stored on
    metadata_groups.metadata_excel. Returns None when GCS is disabled."""
    return _upload_bytes_to_gcs(file_bytes, f"metadata_excel/{filename}")


def _upload_table_excel_to_gcs(file_bytes: bytes, dataset_id: str) -> Optional[str]:
    """Upload a per-dataset clean Excel export (see table_export.py) and
    return the gs:// URL, stored on datasets.source_excel. Returns None
    when GCS is disabled."""
    return _upload_bytes_to_gcs(file_bytes, f"datasets/{dataset_id}.xlsx")


def _upload_original_sheet_to_gcs(file_bytes: bytes, source_file: str, sheet: str) -> Optional[str]:
    """Upload a formatting-preserving single-sheet export (see
    original_sheet_export.py) and return the gs:// URL, stored on
    datasets.original_excel. Returns None when GCS is disabled."""
    safe_name = f"{source_file}__{sheet}".replace("/", "_")
    return _upload_bytes_to_gcs(file_bytes, f"original_sheets/{safe_name}.xlsx")
