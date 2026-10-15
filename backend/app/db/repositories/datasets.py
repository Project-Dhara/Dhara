"""Published dataset write path (SQLAlchemy Session)."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date
from typing import Any, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.repositories.catalogue import tag_publish_organisation
from app.services.classification.classifications import (
    _classifications_from_table_data,
    _looks_like_index_or_toc_table,
    _merge_classifications,
    _merge_real_classifications,
)
from app.services.ingestion.table_ids import (
    catalogue_id_stem,
    format_sequential_dataset_id,
    is_review_locator_id,
    is_sequential_catalogue_id,
    looks_like_uuid,
    normalize_dataset_id_config,
)

logger = logging.getLogger(__name__)

_COUNTERS_DDL = """
CREATE TABLE IF NOT EXISTS dataset_id_counters (
    stem         TEXT PRIMARY KEY,
    last_value   INTEGER NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
)
"""

STANDARD_CONCEPTS = [
    "Contact",
    "Data description and Presentation",
    "Data Processing",
    "Data Analysis",
    "Dissemination",
    "Quality",
    "Meta data update",
    "Institutional Mandate",
    "Accuracy and Reliability",
    "Timeliness",
    "Coherence/Comparability",
]


def _looks_like_uuid(value: str) -> bool:
    return looks_like_uuid(value)


def _max_sequential_in_datasets(session: Session, stem: str, sep: str) -> int:
    """Highest trailing sequence already present for ``stem`` in ``datasets``."""
    like = f"{stem}{sep}%"
    try:
        rows = session.execute(
            text("SELECT dataset_id FROM datasets WHERE dataset_id LIKE :like"),
            {"like": like},
        ).fetchall()
    except Exception:
        logger.exception("Could not scan datasets for max sequential id (stem=%s)", stem)
        return 0
    best = 0
    prefix = stem + sep
    for (ds_id,) in rows:
        raw = str(ds_id or "")
        if not raw.startswith(prefix):
            continue
        tail = raw[len(prefix) :]
        if tail.isdigit():
            best = max(best, int(tail))
    return best


def _dataset_id_exists(session: Session, dataset_id: str) -> bool:
    try:
        row = session.execute(
            text("SELECT 1 FROM datasets WHERE dataset_id = :ds LIMIT 1"),
            {"ds": dataset_id},
        ).first()
        return row is not None
    except Exception:
        logger.exception("Could not check dataset_id existence for %s", dataset_id)
        # Assume taken so we skip to another candidate instead of colliding.
        return True


def _ensure_dataset_id_counters_table(session: Session) -> bool:
    """Create counters table if missing. Uses a savepoint so publish stays intact."""
    try:
        with session.begin_nested():
            session.execute(text(_COUNTERS_DDL))
        return True
    except Exception:
        logger.warning(
            "dataset_id_counters unavailable; using datasets-scan fallback",
            exc_info=True,
        )
        return False


def _bump_counter(session: Session, stem: str, floor: int) -> Optional[int]:
    """Atomically advance the counter; None if the counter path is unavailable."""
    try:
        with session.begin_nested():
            session.execute(
                text(
                    """
                    INSERT INTO dataset_id_counters (stem, last_value)
                    VALUES (:stem, :floor)
                    ON CONFLICT (stem) DO NOTHING
                    """
                ),
                {"stem": stem, "floor": floor},
            )
            session.execute(
                text(
                    """
                    UPDATE dataset_id_counters
                    SET last_value = GREATEST(last_value, :floor)
                    WHERE stem = :stem
                    """
                ),
                {"stem": stem, "floor": floor},
            )
            row = session.execute(
                text(
                    """
                    UPDATE dataset_id_counters
                    SET last_value = last_value + 1,
                        updated_at = NOW()
                    WHERE stem = :stem
                    RETURNING last_value
                    """
                ),
                {"stem": stem},
            ).one()
            return int(row[0])
    except Exception:
        logger.warning(
            "Counter bump failed for stem=%s; falling back to scan",
            stem,
            exc_info=True,
        )
        return None


def _allocate_free_sequential(
    session: Session,
    *,
    config: Mapping[str, str],
    start_after: int,
) -> str:
    """Pick the next free ``…_NNNNN`` by probing ``datasets`` (never raises)."""
    n = max(0, int(start_after))
    for _ in range(10_000):
        n += 1
        candidate = format_sequential_dataset_id(n, config=config)
        if not _dataset_id_exists(session, candidate):
            return candidate
    # Absolute last resort — unique, still under the configured stem.
    stem = catalogue_id_stem(config)
    sep = config["separator"]
    return f"{stem}{sep}{uuid.uuid4().hex[:8].upper()}"


def allocate_sequential_dataset_id(
    session: Session,
    config: Optional[Mapping[str, Any]] = None,
) -> str:
    """Mint the next ``{prefix}_{stats}_{NNNNN}`` id; never reuse a prior value.

    Prefers ``dataset_id_counters`` (created on demand if missing). If the
    counter path is unavailable, falls back to ``max(datasets)+1`` probing so
    publish never fails solely because of id allocation.
    """
    cfg = normalize_dataset_id_config(config)
    stem = catalogue_id_stem(cfg)
    floor = _max_sequential_in_datasets(session, stem, cfg["separator"])

    if _ensure_dataset_id_counters_table(session):
        for _ in range(10_000):
            n = _bump_counter(session, stem, floor)
            if n is None:
                break
            floor = max(floor, n)
            candidate = format_sequential_dataset_id(n, config=cfg)
            if not _dataset_id_exists(session, candidate):
                return candidate
            # Collision (legacy/import): keep bumping the durable counter.

    return _allocate_free_sequential(session, config=cfg, start_after=floor)


def _reuse_published_dataset_id(
    session: Optional[Session], table: Mapping[str, Any]
) -> Optional[str]:
    """If this table was published before, return its catalogue dataset_id."""
    if session is None:
        return None
    candidates = []
    for key in ("dataset_id", "unique_dataset_id", "table_id", "id"):
        val = str(table.get(key) or "").strip()
        if val and not _looks_like_uuid(val):
            candidates.append(val)
    seen: set[str] = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        try:
            with session.begin_nested():
                row = session.execute(
                    text(
                        """
                        SELECT dataset_id FROM datasets
                        WHERE dataset_id = :c
                           OR unique_dataset_id = :c
                           OR table_id = :c
                        LIMIT 1
                        """
                    ),
                    {"c": cand},
                ).first()
        except Exception:
            logger.exception("Republish lookup failed for candidate=%s", cand)
            continue
        if row and row[0]:
            return str(row[0])
    return None


def prefer_existing_catalogue_dataset_id(
    table: Mapping[str, Any],
    *,
    config: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Return a catalogue id to keep, or None if a new sequential id is needed.

    Keeps steward/KYDS/Excel ids. Does **not** promote Preview page locators
    (``…_P79``) to catalogue primary keys.
    """
    cfg = normalize_dataset_id_config(config)

    for key in ("dataset_id", "unique_dataset_id"):
        explicit = str(table.get(key) or "").strip()
        if not explicit or _looks_like_uuid(explicit):
            continue
        if is_review_locator_id(explicit):
            continue
        return explicit

    row_id = str(table.get("id") or "").strip()
    if row_id and not _looks_like_uuid(row_id) and not is_review_locator_id(row_id):
        return row_id

    table_id = str(table.get("table_id") or "").strip()
    if table_id and is_sequential_catalogue_id(table_id, config=cfg):
        return table_id

    return None


def resolve_catalogue_dataset_id(
    table: dict,
    index: int,
    *,
    session: Optional[Session] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> str:
    """Pick the published dataset_id.

    Prefer explicit / Excel ids, then an already-published row (republish),
    then allocate ``{prefix}_{stats}_{NNNNN}``. Preview locators are not used
    as catalogue ids. ``index`` is unused (kept for call-site compatibility).
    """
    del index  # sequential allocator owns uniqueness
    cfg = normalize_dataset_id_config(config)

    preferred = prefer_existing_catalogue_dataset_id(table, config=cfg)
    if preferred:
        return preferred

    try:
        reused = _reuse_published_dataset_id(session, table)
    except Exception:
        logger.exception("Republish id reuse failed; allocating a new id")
        reused = None
    if reused:
        return reused

    if session is not None:
        try:
            return allocate_sequential_dataset_id(session, cfg)
        except Exception:
            logger.exception(
                "Sequential dataset id allocation failed; using unique fallback"
            )
            stem = catalogue_id_stem(cfg)
            sep = cfg["separator"]
            return f"{stem}{sep}{uuid.uuid4().hex[:8].upper()}"

    # Offline / unit-test fallback when no DB session is available.
    stem = catalogue_id_stem(cfg)
    sep = cfg["separator"]
    return f"{stem}{sep}{uuid.uuid4().hex[:8].upper()}"


def _extract_sl_no(row, row_index: int) -> str:
    if not isinstance(row, dict):
        return str(row_index + 1)
    for key in ("sl_no", "Sl. No.", "S.No.", "Sr.No.", "S.No", "SL NO", "Sl No"):
        if key in row:
            return str(row[key])
    if row:
        first_val = next(iter(row.values()), None)
        if first_val is not None and re.match(r"^\d+$", str(first_val).strip()):
            return str(first_val)
    return str(row_index + 1)


def push_to_catalogue(
    session: Session,
    tables,
    enriched_data,
    metadata_mode,
    metadata_id,
    meta_title,
    meta_description,
    meta_product,
    meta_category,
    meta_geography,
    meta_frequency,
    meta_time_period,
    meta_data_source,
    meta_last_updated,
    meta_future_release,
    meta_key_statistics,
    meta_remarks,
    meta_excel_filename,
    user_email=None,
    meta_nmds_concepts=None,
    meta_real_classifications=None,
    catalogue_placement=None,
    organisation_id: uuid.UUID | str | None = None,
    dataset_id_config: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    today = meta_last_updated or date.today().strftime("%B, %Y")
    if isinstance(meta_key_statistics, (dict, list)):
        meta_key_statistics = json.dumps(meta_key_statistics)
    nmds_concepts = meta_nmds_concepts or []
    dataset_ids: list[str] = []
    table_id_codes: list[str] = []
    org = str(organisation_id) if organisation_id else None
    id_cfg = normalize_dataset_id_config(dataset_id_config)

    # Drop Contents / index grids so they never become catalogue datasets or
    # feed redundant Classify dimensions (Sl.No, Contents, Page, …).
    paired = []
    for i, table in enumerate(tables or []):
        if _looks_like_index_or_toc_table(table):
            continue
        enriched = enriched_data[i] if i < len(enriched_data or []) else {}
        paired.append((table, enriched))
    tables = [t for t, _ in paired]
    enriched_data = [e for _, e in paired]
    if not tables:
        return {
            "metadata_id": None if metadata_mode == "new" else metadata_id,
            "dataset_ids": [],
            "tables_pushed": 0,
            "skipped_index_tables": True,
        }

    for i, table in enumerate(tables):
        enriched = enriched_data[i] if i < len(enriched_data) else {}
        ds_id = resolve_catalogue_dataset_id(
            table, i, session=session, config=id_cfg
        )
        review_tid = str(table.get("table_id") or "").strip()
        # Keep Preview locator (or Excel table label) on table_id for republish
        # matching; catalogue PK is the sequential / explicit dataset_id.
        if review_tid and not _looks_like_uuid(review_tid):
            table_code = review_tid
        else:
            table_code = ds_id
        unique_explicit = str(table.get("unique_dataset_id") or "").strip()
        if (
            unique_explicit
            and not _looks_like_uuid(unique_explicit)
            and not is_review_locator_id(unique_explicit)
        ):
            unique_ds_id = unique_explicit
        else:
            unique_ds_id = ds_id
        dataset_ids.append(ds_id)
        table_id_codes.append(table_code)

        columns = table.get("columns", [])
        rows = table.get("rows", [])
        normalized_rows = []
        col_names = [
            (
                c
                if isinstance(c, str)
                else str((c or {}).get("name") or f"column_{i + 1}")
            )
            for i, c in enumerate(columns or [])
        ]
        for row in rows or []:
            if isinstance(row, dict):
                normalized_rows.append(row)
            elif isinstance(row, (list, tuple)):
                normalized_rows.append(
                    {
                        col_names[j]: (row[j] if j < len(row) else None)
                        for j in range(len(col_names))
                    }
                )
        rows = normalized_rows

        table_cls = _classifications_from_table_data(
            [{"columns": col_names, "rows": rows}]
        )
        classifications = _merge_real_classifications(
            table_cls,
            _merge_real_classifications(
                enriched.get("classifications") or {},
                meta_real_classifications,
            ),
        )
        age_column_keys = enriched.get("age_column_keys") or {}

        session.execute(
            text(
                """
                INSERT INTO datasets (
                    dataset_id, unique_dataset_id, table_id, metadata_id,
                    title, short_description, long_description,
                    category, geography, frequency, time_period,
                    data_source, units, classifications, concepts, age_column_keys,
                    source_excel, original_excel, user_email, organisation_id
                ) VALUES (
                    :dataset_id, :unique_dataset_id, :table_id, :metadata_id,
                    :title, :short_description, :long_description,
                    :category, :geography, :frequency, :time_period,
                    :data_source, :units, CAST(:classifications AS jsonb),
                    :concepts, CAST(:age_column_keys AS jsonb),
                    :source_excel, :original_excel, :user_email,
                    CAST(:organisation_id AS uuid)
                )
                ON CONFLICT (dataset_id) DO UPDATE SET
                    unique_dataset_id = EXCLUDED.unique_dataset_id,
                    table_id = EXCLUDED.table_id,
                    metadata_id = EXCLUDED.metadata_id,
                    title = EXCLUDED.title,
                    short_description = EXCLUDED.short_description,
                    long_description = EXCLUDED.long_description,
                    category = EXCLUDED.category,
                    geography = EXCLUDED.geography,
                    frequency = EXCLUDED.frequency,
                    time_period = EXCLUDED.time_period,
                    data_source = EXCLUDED.data_source,
                    units = EXCLUDED.units,
                    classifications = EXCLUDED.classifications,
                    concepts = EXCLUDED.concepts,
                    age_column_keys = EXCLUDED.age_column_keys,
                    source_excel = EXCLUDED.source_excel,
                    original_excel = EXCLUDED.original_excel,
                    user_email = EXCLUDED.user_email,
                    organisation_id = COALESCE(
                        EXCLUDED.organisation_id, datasets.organisation_id
                    )
                """
            ),
            {
                "dataset_id": ds_id,
                "unique_dataset_id": unique_ds_id,
                "table_id": table_code,
                "metadata_id": metadata_id if metadata_mode == "existing" else None,
                "title": table.get("title") or table.get("table_id", ""),
                "short_description": enriched.get("short_description")
                or table.get("title", ""),
                "long_description": enriched.get("long_description")
                or table.get("title", ""),
                "category": meta_category,
                "geography": meta_geography,
                "frequency": meta_frequency,
                "time_period": meta_time_period,
                "data_source": meta_data_source,
                "units": enriched.get("units") or "Count",
                "classifications": json.dumps(classifications),
                "concepts": STANDARD_CONCEPTS,
                "age_column_keys": json.dumps(age_column_keys),
                "source_excel": table.get("source_excel_url"),
                "original_excel": table.get("original_excel_url"),
                "user_email": user_email,
                "organisation_id": org,
            },
        )
        session.execute(
            text("DELETE FROM dataset_rows WHERE dataset_id = :ds_id"),
            {"ds_id": ds_id},
        )
        for row_index, row in enumerate(rows):
            session.execute(
                text(
                    """
                    INSERT INTO dataset_rows (
                        dataset_id, sl_no, row_index, row_data,
                        user_email, organisation_id
                    )
                    VALUES (
                        :dataset_id, :sl_no, :row_index,
                        CAST(:row_data AS jsonb), :user_email,
                        CAST(:organisation_id AS uuid)
                    )
                    """
                ),
                {
                    "dataset_id": ds_id,
                    "sl_no": _extract_sl_no(row, row_index),
                    "row_index": row_index,
                    "row_data": json.dumps(row, default=str),
                    "user_email": user_email,
                    "organisation_id": org,
                },
            )

    if metadata_mode == "new":
        metadata_id = (
            f"AUTO-{re.sub(r'[^A-Z0-9]', '-', (meta_title or 'DATA').upper())[:20]}"
            f"-{uuid.uuid4().hex[:6]}"
        )
        group_classifications = _merge_real_classifications(
            _classifications_from_table_data(tables),
            _merge_real_classifications(
                _merge_classifications(enriched_data),
                meta_real_classifications,
            ),
        )
        full_record = {
            "metadata": {
                "metadata_id": metadata_id,
                "title": meta_title,
                "description": meta_description,
                "product": meta_product,
                "category": meta_category,
                "geography": meta_geography,
                "frequency": meta_frequency,
                "time_period": meta_time_period,
                "data_source": meta_data_source,
                "last_updated_date": today,
                "future_release": meta_future_release,
                "key_statistics": meta_key_statistics,
                "remarks": meta_remarks,
                "metadata_excel": meta_excel_filename,
                "table_ids": table_id_codes,
            },
            "classifications": group_classifications,
            "concepts": STANDARD_CONCEPTS,
            "nmds_concepts": nmds_concepts,
            "catalogue_placement": catalogue_placement or {},
            "dataset_inventory_list": [
                {
                    "dataset_id": dataset_ids[j],
                    "table_id": table_id_codes[j],
                    "title": tables[j].get("title") or tables[j].get("table_id", ""),
                    "short_description": (
                        enriched_data[j].get("short_description")
                        if j < len(enriched_data)
                        else ""
                    )
                    or "",
                    "long_description": (
                        enriched_data[j].get("long_description")
                        if j < len(enriched_data)
                        else ""
                    )
                    or "",
                }
                for j in range(len(tables))
            ],
        }
        session.execute(
            text(
                """
                INSERT INTO metadata_groups (
                    metadata_id, title, description, product, category, geography,
                    frequency, time_period, data_source, last_updated_date,
                    future_release, key_statistics, remarks,
                    metadata_excel, table_ids, classifications, concepts, full_record,
                    user_email, nmds_concepts, organisation_id
                ) VALUES (
                    :metadata_id, :title, :description, :product, :category, :geography,
                    :frequency, :time_period, :data_source, :last_updated_date,
                    :future_release, :key_statistics, :remarks,
                    :metadata_excel, :table_ids, CAST(:classifications AS jsonb),
                    :concepts, CAST(:full_record AS jsonb),
                    :user_email, CAST(:nmds_concepts AS jsonb),
                    CAST(:organisation_id AS uuid)
                )
                """
            ),
            {
                "metadata_id": metadata_id,
                "title": meta_title,
                "description": meta_description,
                "product": meta_product,
                "category": meta_category,
                "geography": meta_geography,
                "frequency": meta_frequency,
                "time_period": meta_time_period,
                "data_source": meta_data_source,
                "last_updated_date": today,
                "future_release": meta_future_release,
                "key_statistics": meta_key_statistics,
                "remarks": meta_remarks,
                "metadata_excel": meta_excel_filename,
                "table_ids": dataset_ids,
                "classifications": json.dumps(group_classifications),
                "concepts": STANDARD_CONCEPTS,
                "full_record": json.dumps(full_record),
                "user_email": user_email,
                "nmds_concepts": json.dumps(nmds_concepts),
                "organisation_id": org,
            },
        )
        placement = catalogue_placement or {}
        session.execute(
            text(
                """
                UPDATE metadata_groups
                   SET sector = :sector,
                       theme = :theme,
                       catalogue_product = :product
                 WHERE metadata_id = :mid
                """
            ),
            {
                "sector": placement.get("sector"),
                "theme": placement.get("theme"),
                "product": placement.get("product"),
                "mid": metadata_id,
            },
        )
        session.execute(
            text(
                """
                UPDATE datasets SET metadata_id = :mid
                 WHERE dataset_id = ANY(:ids)
                """
            ),
            {"mid": metadata_id, "ids": dataset_ids},
        )
    else:
        session.execute(
            text(
                """
                UPDATE metadata_groups
                   SET table_ids = array_cat(COALESCE(table_ids, '{}'), :ids),
                       last_updated_date = :today
                 WHERE metadata_id = :mid
                """
            ),
            {"ids": dataset_ids, "today": today, "mid": metadata_id},
        )
        if org:
            tag_publish_organisation(
                session, metadata_id=metadata_id, organisation_id=org
            )

    session.flush()
    return {
        "metadata_id": metadata_id,
        "dataset_ids": dataset_ids,
        "tables_pushed": len(tables),
    }
