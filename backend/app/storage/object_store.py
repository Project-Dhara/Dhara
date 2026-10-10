"""Cloud object storage (GCS) and catalogue upload helpers."""
from __future__ import annotations

from typing import Optional

from app.core.config import get_settings
from app.storage.files import NoOpObjectStore, ObjectStore

_GCS_SKIP_LOGGED = False


class GcsObjectStore:
    """Google Cloud Storage backend when ``ENABLE_GCS=true``."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.enable_gcs:
            raise ValueError("GcsObjectStore requires ENABLE_GCS=true")
        if not settings.gcs_bucket_name:
            raise ValueError(
                "ENABLE_GCS is true but GCS_BUCKET_NAME is not set. "
                "Set GCS_BUCKET_NAME, or set ENABLE_GCS=false for Postgres-only."
            )
        self._bucket_name = settings.gcs_bucket_name

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> Optional[str]:
        from google.cloud import storage as gcs

        client = gcs.Client()
        bucket = client.bucket(self._bucket_name)
        blob = bucket.blob(key.lstrip("/"))
        blob.upload_from_string(data, content_type=content_type)
        return f"gs://{self._bucket_name}/{key.lstrip('/')}"

    def enabled(self) -> bool:
        return True


def get_object_store() -> ObjectStore:
    """Return GCS when enabled, else a no-op store (Postgres remains source of truth)."""
    global _GCS_SKIP_LOGGED
    settings = get_settings()
    if settings.enable_gcs and settings.gcs_bucket_name:
        return GcsObjectStore()
    if settings.enable_gcs and not settings.gcs_bucket_name:
        raise ValueError(
            "ENABLE_GCS is true but GCS_BUCKET_NAME is not set. "
            "Set GCS_BUCKET_NAME, or set ENABLE_GCS=false."
        )
    if not _GCS_SKIP_LOGGED:
        print(
            "GCS uploads skipped (ENABLE_GCS is not true). "
            "Catalogue rows will still be written to Postgres.",
            flush=True,
        )
        _GCS_SKIP_LOGGED = True
    return NoOpObjectStore()


_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def upload_bytes_to_gcs(file_bytes: bytes, blob_name: str) -> Optional[str]:
    store = get_object_store()
    if not store.enabled():
        return None
    return store.put_bytes(blob_name, file_bytes, content_type=_XLSX)


def upload_excel_to_gcs(file_bytes: bytes, filename: str) -> Optional[str]:
    return upload_bytes_to_gcs(file_bytes, f"metadata_excel/{filename}")


def upload_table_excel_to_gcs(file_bytes: bytes, dataset_id: str) -> Optional[str]:
    return upload_bytes_to_gcs(file_bytes, f"datasets/{dataset_id}.xlsx")


def upload_original_sheet_to_gcs(
    file_bytes: bytes, source_file: str, sheet: str
) -> Optional[str]:
    safe_name = f"{source_file}__{sheet}".replace("/", "_")
    return upload_bytes_to_gcs(file_bytes, f"original_sheets/{safe_name}.xlsx")
