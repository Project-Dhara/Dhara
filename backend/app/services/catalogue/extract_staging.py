"""Temporary storage for extracted Excel/SQL tables between extract and catalogue push.

batch-push used to receive full table rows inside a multipart form field, which
hits Starlette's 1MB max_part_size on large batches. Callers now stage tables
here at extract time and send only ids + steward overlays on push.

Delegates to ``app.db.repositories.staging`` (SQLAlchemy Session).
"""
from app.db.repositories.staging import (
    load_staging_tables,
    new_batch_id,
    save_staging_tables,
)

__all__ = [
    "new_batch_id",
    "save_staging_tables",
    "load_staging_tables",
]
