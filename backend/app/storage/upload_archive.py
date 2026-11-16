"""Best-effort on-disk archive of original uploaded files (PDF, Excel, CSV, …).

Files are split by type into gitignored folders under ``backend/data/``:

- ``pdf_uploads/``   — ``.pdf``
- ``excel_uploads/`` — ``.xlsx`` / ``.xls``
- ``csv_uploads/``   — ``.csv``
- ``other_uploads/`` — anything else

Basenames are kept as-is; duplicates append ``(1)``, ``(2)``, ….

Failures are logged and never raised — callers must not depend on this for
pipeline correctness.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_KIND_DIR_NAMES = {
    "pdf": "pdf_uploads",
    "excel": "excel_uploads",
    "csv": "csv_uploads",
    "other": "other_uploads",
}


def archive_kind(filename: Optional[str]) -> str:
    """Map a filename to an archive bucket: pdf | excel | csv | other."""
    ext = Path(safe_upload_basename(filename)).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".xlsx", ".xls"):
        return "excel"
    if ext == ".csv":
        return "csv"
    return "other"


def archive_root(filename: Optional[str] = None) -> Path:
    """Directory for one upload's archive bucket.

    ``UPLOAD_ARCHIVE_PATH`` (optional) is the parent of the type folders
    (``pdf_uploads``, ``excel_uploads``, …). Default parent is ``backend/data``.
    """
    kind = archive_kind(filename)
    dir_name = _KIND_DIR_NAMES[kind]
    override = (os.environ.get("UPLOAD_ARCHIVE_PATH") or "").strip()
    if override:
        return Path(override).expanduser().resolve() / dir_name
    return (_BACKEND_DIR / "data" / dir_name).resolve()


def safe_upload_basename(filename: Optional[str]) -> str:
    """Keep the original basename; only strip directories / NUL / empty names."""
    raw = str(filename or "").replace("\x00", "").strip() or "upload"
    # Path.name drops any directory components from client-supplied paths.
    base = Path(raw).name.strip() or "upload"
    if base in (".", ".."):
        return "upload"
    return base


def _allocate_and_write(root: Path, filename: str, data: bytes) -> Path:
    """Create a unique path with exclusive create, then write ``data`` verbatim."""
    safe = safe_upload_basename(filename)
    stem = Path(safe).stem or "upload"
    suffix = Path(safe).suffix
    n = 0
    while n <= 10_000:
        name = f"{stem}{suffix}" if n == 0 else f"{stem}({n}){suffix}"
        candidate = root / name
        try:
            fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            n += 1
            continue
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        except Exception:
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return candidate
    raise RuntimeError(f"Could not allocate unique archive name for {safe!r}")


def archive_upload_bytes(filename: str, data: bytes) -> Optional[Path]:
    """Copy upload bytes unchanged into the type-specific archive folder."""
    if not data:
        return None
    try:
        root = archive_root(filename)
        root.mkdir(parents=True, exist_ok=True)
        path = _allocate_and_write(root, filename, data)
        logger.info("Archived upload %r → %s", filename, path)
        return path
    except Exception as exc:
        logger.warning(
            "Upload archive skipped for %r (%s)", filename, exc, exc_info=False
        )
        return None


def archive_upload_files(
    files: Sequence[Union[Tuple[str, bytes], Tuple[str, str, bytes]]],
) -> List[Optional[Path]]:
    """Archive each ``(filename, bytes)`` or ``(filename, source_type, bytes)`` entry."""
    out: List[Optional[Path]] = []
    for entry in files:
        if len(entry) == 2:
            filename, content = entry  # type: ignore[misc]
        else:
            filename, _source_type, content = entry  # type: ignore[misc]
        out.append(archive_upload_bytes(str(filename), content))
    return out
