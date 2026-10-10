"""Published dataset write path (SQLAlchemy Session)."""
from __future__ import annotations

import json
import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.repositories.catalogue import tag_publish_organisation
from app.services.classification.classifications import (
    _classifications_from_table_data,
    _merge_classifications,
    _merge_real_classifications,
)

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


def _make_dataset_id(table: dict, index: int) -> str:
    suffix = uuid.uuid4().hex[:6]
    return f"DS-{index+1:03d}-{suffix}"


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
) -> dict[str, Any]:
    today = meta_last_updated or date.today().strftime("%B, %Y")
    if isinstance(meta_key_statistics, (dict, list)):
        meta_key_statistics = json.dumps(meta_key_statistics)
    nmds_concepts = meta_nmds_concepts or []
    dataset_ids: list[str] = []
    table_id_codes: list[str] = []
    org = str(organisation_id) if organisation_id else None

    for i, table in enumerate(tables):
        enriched = enriched_data[i] if i < len(enriched_data) else {}
        ds_id = table.get("id") or _make_dataset_id(table, i)
        table_code = ds_id
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
