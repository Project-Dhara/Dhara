"""Human-readable review / dataset table IDs.

Matches Settings → Dataset ID configuration (prefix, separator, statistics)
plus a short source/page suffix (and ``T{n}`` only when a page has multiple tables).

Examples:
  ``DDI_DES_DEL_VS_1_P79``           — one table on page 79 of ``1.pdf``
  ``DDI_DES_DEL_VS_1_P79_T2``        — 2nd of several tables on that page
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

# Keep in sync with frontend/src/lib/settingsConfig.ts defaults.
DEFAULT_DATASET_ID_CONFIG: Dict[str, str] = {
    "prefix": "DDI_DES_DEL",
    "separator": "_",
    "statistics": "Vital Statistics",
}

STATISTICS_SHORT_FORMS: Dict[str, str] = {
    "Vital Statistics": "VS",
    "Labour Statistics": "LS",
    "Industrial Statistics": "IS",
}

_BATCH_PAGE_NS = re.compile(r"^__f(\d+)__(.+)$")


def normalize_dataset_id_config(raw: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    base = dict(DEFAULT_DATASET_ID_CONFIG)
    if not isinstance(raw, Mapping):
        return base
    prefix = str(raw.get("prefix") or base["prefix"]).strip() or base["prefix"]
    separator = str(raw.get("separator") if raw.get("separator") is not None else base["separator"])
    if separator == "":
        separator = base["separator"]
    statistics = str(raw.get("statistics") or base["statistics"]).strip() or base["statistics"]
    return {"prefix": prefix, "separator": separator, "statistics": statistics}


def dataset_id_config_from_job(job: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Read config from the job payload or the reserved reviews key (durable)."""
    if not isinstance(job, Mapping):
        return normalize_dataset_id_config(None)
    cfg = job.get("dataset_id_config")
    if isinstance(cfg, Mapping) and cfg:
        return normalize_dataset_id_config(cfg)
    reviews = job.get("reviews")
    if isinstance(reviews, Mapping):
        nested = reviews.get("__dataset_id_config")
        if isinstance(nested, Mapping) and nested:
            return normalize_dataset_id_config(nested)
    return normalize_dataset_id_config(None)


def statistics_short_form(statistics: str) -> str:
    label = (statistics or "").strip()
    if label in STATISTICS_SHORT_FORMS:
        return STATISTICS_SHORT_FORMS[label]
    # Initials fallback: "Vital Statistics" → "VS", "Foo Bar Baz" → "FBB"
    words = re.findall(r"[A-Za-z0-9]+", label)
    if words:
        return "".join(w[0].upper() for w in words)[:6]
    return "STAT"


_EPHEMERAL_STEM = re.compile(
    r"^(tmp|temp)[a-z0-9_]*$",
    re.IGNORECASE,
)

_TYPE_TOKEN = {
    "pdf": "PDF",
    "excel": "XLS",
    "csv": "CSV",
}


def is_ephemeral_upload_name(filename: Optional[str]) -> bool:
    """True for OS temp names (e.g. ``tmp86rimsi.pdf`` from NamedTemporaryFile)."""
    stem = Path(str(filename or "")).stem.strip()
    if not stem:
        return True
    return bool(_EPHEMERAL_STEM.match(stem))


def source_stem_abbrev(
    filename: Optional[str],
    *,
    source_type: str = "pdf",
    max_len: int = 10,
) -> str:
    """Short source token from the filename stem only (e.g. ``1.pdf`` → ``1``).

    Ephemeral worker temp paths are replaced with a short type token (``PDF``),
    never the random ``TMP…`` stem.
    """
    if is_ephemeral_upload_name(filename):
        return _TYPE_TOKEN.get((source_type or "pdf").lower(), "DOC")
    stem = Path(str(filename or "src")).stem
    clean = re.sub(r"[^A-Za-z0-9]", "", stem).upper() or _TYPE_TOKEN.get(
        (source_type or "pdf").lower(), "DOC"
    )
    if len(clean) > max_len:
        clean = clean[:max_len]
    return clean


def resolve_source_filename_for_id(
    *candidates: Optional[str],
    source_type: str = "pdf",
) -> Optional[str]:
    """First non-ephemeral filename among candidates (upload name over temp path)."""
    for raw in candidates:
        if raw and str(raw).strip() and not is_ephemeral_upload_name(raw):
            return str(raw).strip()
    return None


def parse_batch_page_key(page_key: Any) -> Tuple[Optional[int], Any]:
    """Return ``(file_index, physical_page_key)`` for ``__fN__…`` keys."""
    m = _BATCH_PAGE_NS.match(str(page_key))
    if not m:
        return None, page_key
    inner: Any = m.group(2)
    if str(inner).isdigit():
        inner = int(inner)
    return int(m.group(1)), inner


def physical_page_value(table: Mapping[str, Any], page_key: Any) -> int:
    raw = table.get("page")
    if raw is not None and str(raw).strip() != "":
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    _fi, phys = parse_batch_page_key(page_key)
    try:
        return int(phys)
    except (TypeError, ValueError):
        return 0


def build_review_table_id(
    *,
    config: Optional[Mapping[str, Any]] = None,
    source_filename: Optional[str] = None,
    source_type: str = "pdf",
    page: Any,
    index: int = 0,
    tables_on_page: int = 1,
    file_index: Optional[int] = None,
) -> str:
    """Build ``{prefix}{sep}{stats}{sep}{src}{sep}P{page}[{sep}T{n}]``.

    ``T{n}`` is included only when ``tables_on_page > 1``.
    ``file_index`` is ignored when a source filename stem is available (avoids
    redundant ``F1`` next to ``1`` / ``REPORT``).
    """
    cfg = normalize_dataset_id_config(config)
    sep = cfg["separator"]
    stats = statistics_short_form(cfg["statistics"])
    src = source_stem_abbrev(source_filename, source_type=source_type)
    try:
        page_n = int(page)
    except (TypeError, ValueError):
        page_n = 0
    try:
        table_n = int(index) + 1
    except (TypeError, ValueError):
        table_n = 1
    try:
        n_on_page = int(tables_on_page)
    except (TypeError, ValueError):
        n_on_page = 1

    parts = [cfg["prefix"], stats, src]
    # Only use Fn when we have no usable source stem (should be rare).
    if not src and file_index is not None:
        try:
            parts.append(f"F{int(file_index) + 1}")
        except (TypeError, ValueError):
            pass
    parts.append(f"P{page_n}")
    if n_on_page > 1:
        parts.append(f"T{table_n}")
    return sep.join(str(p) for p in parts if str(p))


def assign_table_ids_to_result(
    result: Optional[Dict[Any, Any]],
    *,
    config: Optional[Mapping[str, Any]] = None,
    default_filename: Optional[str] = None,
    default_source_type: str = "pdf",
    batch_files: Optional[list] = None,
) -> Dict[Any, Any]:
    """Stamp human-readable ``table_id`` onto every table in a job result (in place)."""
    from app.services.ingestion.review_tables import BATCH_META_KEY, result_pages_only

    if not isinstance(result, dict):
        return {}
    cfg = normalize_dataset_id_config(config)
    pages = result_pages_only(result)
    files = list(batch_files or [])
    if not files:
        meta = result.get(BATCH_META_KEY)
        if isinstance(meta, dict) and isinstance(meta.get("batch_files"), list):
            files = list(meta["batch_files"])

    for page_key, page_data in pages.items():
        if not isinstance(page_data, dict):
            continue
        tables = [t for t in (page_data.get("tables") or []) if isinstance(t, dict)]
        tables_on_page = len(tables)
        file_index, _phys = parse_batch_page_key(page_key)
        src_name = default_filename
        src_type = default_source_type
        if file_index is not None and 0 <= file_index < len(files):
            entry = files[file_index] or {}
            src_name = entry.get("filename") or src_name
            src_type = entry.get("source_type") or src_type
        for idx, table in enumerate(tables):
            page_n = physical_page_value(table, page_key)
            src_ty = str(table.get("source_type") or src_type or "pdf")
            # Prefer the steward's upload name over the worker's NamedTemporaryFile.
            src_fn = resolve_source_filename_for_id(
                src_name,
                table.get("source_filename"),
                table.get("source_file"),
                source_type=src_ty,
            )
            if src_fn:
                table["source_filename"] = src_fn
                if not table.get("source_file") or is_ephemeral_upload_name(
                    table.get("source_file")
                ):
                    table["source_file"] = src_fn
            # Preserve the per-file (child) id so batch snapshots can resolve
            # against the child job's stored PNG / pdf_bytes keys.
            if file_index is not None:
                prior = str(table.get("table_id") or "").strip()
                table["source_table_id"] = prior or build_review_table_id(
                    config=cfg,
                    source_filename=src_fn,
                    source_type=src_ty,
                    page=page_n,
                    index=idx,
                    tables_on_page=tables_on_page,
                    file_index=None,
                )
            table["table_id"] = build_review_table_id(
                config=cfg,
                source_filename=src_fn,
                source_type=src_ty,
                page=page_n,
                index=idx,
                tables_on_page=tables_on_page,
                file_index=file_index,
            )
            table["review_index"] = idx
    return result


def find_table_in_job_result(
    job: Mapping[str, Any], table_id: str
) -> Optional[Tuple[Any, int, Dict[str, Any]]]:
    """Locate ``(page_key, idx, table_dict)`` for a review table_id."""
    from app.services.ingestion.review_tables import result_pages_only

    target = str(table_id)
    result = result_pages_only(job.get("result"))
    cfg = dataset_id_config_from_job(job)
    filename = job.get("filename")
    source_type = job.get("source_type") or "pdf"
    meta = (job.get("result") or {}).get("__batch_meta__") if isinstance(job.get("result"), dict) else {}
    files = list((meta or {}).get("batch_files") or job.get("batch_files") or [])

    for page_key, page_data in result.items():
        tables = [t for t in ((page_data or {}).get("tables") or []) if isinstance(t, dict)]
        tables_on_page = len(tables)
        for idx, table in enumerate(tables):
            stamped = str(table.get("table_id") or "")
            if stamped and stamped == target:
                return page_key, idx, table
            # Legacy / unstamped: rebuild expected id and compare.
            file_index, _phys = parse_batch_page_key(page_key)
            src_type = table.get("source_type") or source_type
            batch_name = None
            if file_index is not None and 0 <= file_index < len(files):
                batch_name = (files[file_index] or {}).get("filename")
                src_type = (files[file_index] or {}).get("source_type") or src_type
            src_name = resolve_source_filename_for_id(
                batch_name,
                filename,
                table.get("source_filename"),
                table.get("source_file"),
                source_type=str(src_type or "pdf"),
            )
            expected = build_review_table_id(
                config=cfg,
                source_filename=src_name,
                source_type=str(src_type or "pdf"),
                page=physical_page_value(table, page_key),
                index=idx,
                tables_on_page=tables_on_page,
                file_index=file_index,
            )
            if expected == target:
                return page_key, idx, table
            # Legacy opaque ids: "48-0" or "__f0__48-0"
            legacy = f"{page_key}-{idx}"
            if legacy == target:
                return page_key, idx, table
    return None
