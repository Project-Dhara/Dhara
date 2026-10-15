"""Dataset ID helpers — ``{prefix}_{stats}_{NNNNN}`` for Preview and catalogue.

Settings → Dataset ID configuration (prefix, separator, statistics) drives the
stem. Sequential numbers are allocated from ``dataset_id_counters`` when tables
are stamped after extraction and reused at publish (never reassigned).
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

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

# Zero-padded sequence width for published catalogue ids.
SEQUENTIAL_ID_WIDTH = 5

_BATCH_PAGE_NS = re.compile(r"^__f(\d+)__(.+)$")
# Review locator marker: …_P12 or …_P12_T2 (not …_00012 sequential).
_REVIEW_PAGE_MARKER = re.compile(r"(?:^|_)P\d+(?:_|$)")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


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


def catalogue_id_stem(config: Optional[Mapping[str, Any]] = None) -> str:
    """``{prefix}{sep}{stats}`` used as the sequential counter key / id prefix."""
    cfg = normalize_dataset_id_config(config)
    return cfg["separator"].join(
        [cfg["prefix"], statistics_short_form(cfg["statistics"])]
    )


def format_sequential_dataset_id(
    n: int, *, config: Optional[Mapping[str, Any]] = None
) -> str:
    """Format ``{prefix}{sep}{stats}{sep}{NNNNN}`` (e.g. ``DDI_DES_DEL_VS_00042``)."""
    cfg = normalize_dataset_id_config(config)
    sep = cfg["separator"]
    stem = catalogue_id_stem(cfg)
    try:
        num = max(0, int(n))
    except (TypeError, ValueError):
        num = 0
    return f"{stem}{sep}{num:0{SEQUENTIAL_ID_WIDTH}d}"


def parse_sequential_dataset_number(
    value: str, *, config: Optional[Mapping[str, Any]] = None
) -> Optional[int]:
    """Return the integer sequence if ``value`` matches the catalogue id shape."""
    cfg = normalize_dataset_id_config(config)
    stem = catalogue_id_stem(cfg)
    sep = cfg["separator"]
    raw = str(value or "").strip()
    if not raw.startswith(stem + sep):
        return None
    tail = raw[len(stem) + len(sep) :]
    if not tail.isdigit():
        return None
    return int(tail)


def is_sequential_catalogue_id(
    value: str, *, config: Optional[Mapping[str, Any]] = None
) -> bool:
    return parse_sequential_dataset_number(value, config=config) is not None


def is_review_locator_id(value: str) -> bool:
    """True for Preview locators that embed a page marker (``P79``), not sequences."""
    raw = str(value or "").strip()
    if not raw or _UUID_RE.fullmatch(raw):
        return False
    if parse_sequential_dataset_number(raw) is not None:
        return False
    return bool(_REVIEW_PAGE_MARKER.search(raw))


def looks_like_uuid(value: str) -> bool:
    return bool(_UUID_RE.fullmatch(str(value or "").strip()))


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
    """Build a Preview locator: ``{prefix}{sep}{stats}[{sep}F{n}]{sep}P{page}[{sep}T{n}]``.

    Filename stems are intentionally omitted (catalogue ids are sequential at
    publish). ``F{n}`` is included for multi-file batches so page numbers from
    different files do not collide. ``T{n}`` only when ``tables_on_page > 1``.

    ``source_filename`` / ``source_type`` are accepted for call-site compatibility
    and are not embedded in the id.
    """
    del source_filename, source_type  # not part of the locator
    cfg = normalize_dataset_id_config(config)
    sep = cfg["separator"]
    stats = statistics_short_form(cfg["statistics"])
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

    parts = [cfg["prefix"], stats]
    if file_index is not None:
        try:
            parts.append(f"F{int(file_index) + 1}")
        except (TypeError, ValueError):
            pass
    parts.append(f"P{page_n}")
    if n_on_page > 1:
        parts.append(f"T{table_n}")
    return sep.join(str(p) for p in parts if str(p))


def _mint_sequential_dataset_ids(
    cfg: Mapping[str, str], count: int
) -> List[str]:
    """Allocate ``count`` sequential ids in one DB transaction (robust offline)."""
    if count <= 0:
        return []
    try:
        from app.db.repositories.datasets import allocate_sequential_dataset_id
        from app.db.session import session_scope

        out: List[str] = []
        with session_scope() as session:
            for _ in range(count):
                out.append(allocate_sequential_dataset_id(session, cfg))
        return out
    except Exception:
        logger.warning(
            "Sequential id allocation unavailable; using unique stem fallbacks",
            exc_info=True,
        )
        stem = catalogue_id_stem(cfg)
        sep = cfg["separator"]
        return [f"{stem}{sep}{uuid.uuid4().hex[:8].upper()}" for _ in range(count)]


def job_needs_sequential_dataset_ids(
    job: Optional[Mapping[str, Any]],
) -> bool:
    """True when any table lacks a ``{prefix}_{stats}_{NNNNN}`` id."""
    from app.services.ingestion.review_tables import result_pages_only

    if not isinstance(job, Mapping):
        return False
    cfg = dataset_id_config_from_job(job)
    result = job.get("result")
    if not isinstance(result, dict):
        return False
    for page_data in result_pages_only(result).values():
        if not isinstance(page_data, dict):
            continue
        for table in page_data.get("tables") or []:
            if not isinstance(table, dict):
                continue
            tid = str(table.get("table_id") or table.get("dataset_id") or "").strip()
            if not tid or not is_sequential_catalogue_id(tid, config=cfg):
                return True
    return False


def ensure_sequential_dataset_ids_on_job(job: Dict[str, Any]) -> bool:
    """Re-stamp non-sequential table ids in-place. Returns True if the job changed.

    Migrates ``reviews`` / ``deleted_table_ids`` keys from old → new ids so
    Preview edits and soft-deletes stay attached after the upgrade.
    """
    if not isinstance(job, dict) or not job_needs_sequential_dataset_ids(job):
        return False

    from app.services.ingestion.review_tables import result_pages_only

    cfg = dataset_id_config_from_job(job)
    result = job.get("result")
    if not isinstance(result, dict):
        return False

    before: List[Tuple[dict, str]] = []
    for page_data in result_pages_only(result).values():
        if not isinstance(page_data, dict):
            continue
        for table in page_data.get("tables") or []:
            if isinstance(table, dict):
                before.append(
                    (table, str(table.get("table_id") or "").strip())
                )

    meta = result.get("__batch_meta__") if isinstance(result.get("__batch_meta__"), dict) else {}
    assign_table_ids_to_result(
        result,
        config=cfg,
        default_filename=job.get("filename"),
        default_source_type=str(job.get("source_type") or "pdf"),
        batch_files=list(meta.get("batch_files") or job.get("batch_files") or []),
    )

    reviews = job.get("reviews")
    if not isinstance(reviews, dict):
        reviews = {}
        job["reviews"] = reviews
    deleted = job.get("deleted_table_ids")
    deleted_set = set(str(x) for x in (deleted or []))
    renamed: List[Tuple[str, str]] = []
    for table, old in before:
        new = str(table.get("table_id") or "").strip()
        if not old or not new or old == new:
            continue
        renamed.append((old, new))
        if old in reviews:
            prev = reviews.pop(old) or {}
            reviews[new] = {**(reviews.get(new) or {}), **prev}
        if old in deleted_set:
            deleted_set.discard(old)
            deleted_set.add(new)
    if deleted is not None or deleted_set:
        job["deleted_table_ids"] = sorted(deleted_set)

    if renamed:
        _migrate_snapshot_table_ids(str(job.get("job_id") or ""), renamed)

    return True


def _migrate_snapshot_table_ids(job_id: str, renamed: List[Tuple[str, str]]) -> None:
    """Best-effort rename of persisted PDF snapshot keys after id restamp."""
    if not job_id or not renamed:
        return
    try:
        from sqlalchemy import text as sa_text

        from app.db.session import session_scope

        with session_scope() as session:
            for old, new in renamed:
                session.execute(
                    sa_text(
                        """
                        UPDATE pdf_table_snapshots
                        SET table_id = :new
                        WHERE job_id = :job_id AND table_id = :old
                        """
                    ),
                    {"job_id": job_id, "old": old, "new": new},
                )
    except Exception:
        logger.warning(
            "Could not migrate pdf_table_snapshots for job %s", job_id, exc_info=True
        )


def assign_table_ids_to_result(
    result: Optional[Dict[Any, Any]],
    *,
    config: Optional[Mapping[str, Any]] = None,
    default_filename: Optional[str] = None,
    default_source_type: str = "pdf",
    batch_files: Optional[list] = None,
) -> Dict[Any, Any]:
    """Stamp ``{prefix}_{stats}_{NNNNN}`` onto every table (in place).

    Keeps an already-sequential ``table_id``. Page/filename locators are not
    used as the displayed/stored dataset id.
    """
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

    # Collect tables that need a new sequential id (preserve existing ones).
    need_mint: List[dict] = []
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
            prior = str(table.get("table_id") or "").strip()
            # Preserve the per-file (child) id so batch snapshots can resolve
            # against the child job's stored PNG / pdf_bytes keys.
            if file_index is not None:
                table["source_table_id"] = prior or build_review_table_id(
                    config=cfg,
                    source_filename=src_fn,
                    source_type=src_ty,
                    page=page_n,
                    index=idx,
                    tables_on_page=tables_on_page,
                    file_index=None,
                )
            table["review_index"] = idx
            if prior and is_sequential_catalogue_id(prior, config=cfg):
                table["table_id"] = prior
                table["dataset_id"] = prior
            else:
                # Keep a non-sequential prior as a locator for snapshots / legacy.
                if prior and not looks_like_uuid(prior):
                    table.setdefault("review_locator_id", prior)
                need_mint.append(table)

    if need_mint:
        minted = _mint_sequential_dataset_ids(cfg, len(need_mint))
        for table, tid in zip(need_mint, minted):
            table["table_id"] = tid
            table["dataset_id"] = tid
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
