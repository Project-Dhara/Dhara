"""Published datasets: batch-push write path (+ re-export of list query)."""
import json
import re
import uuid
from datetime import date

from catalogue.classifications import (
    _classifications_from_table_data,
    _merge_classifications,
    _merge_real_classifications,
)
from catalogue.query import list_catalogue_datasets  # noqa: F401 — public re-export

# Standard metadata quality concepts used across all DES catalogue records
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
    """Fallback dataset_id when table has no pre-built id."""
    suffix = uuid.uuid4().hex[:6]
    return f"DS-{index+1:03d}-{suffix}"


def _extract_sl_no(row, row_index: int) -> str:
    """Try to find the serial number value from a row dict."""
    if not isinstance(row, dict):
        return str(row_index + 1)
    for key in ("sl_no", "Sl. No.", "S.No.", "Sr.No.", "S.No", "SL NO", "Sl No"):
        if key in row:
            return str(row[key])
    # check the first column value — if it looks like a serial number use it
    if row:
        first_val = next(iter(row.values()), None)
        if first_val is not None and re.match(r"^\d+$", str(first_val).strip()):
            return str(first_val)
    return str(row_index + 1)


def push_to_catalogue(
    conn,
    tables,
    enriched_data,       # list[dict] parallel to tables, from extractor.enrich_for_catalogue
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
    meta_nmds_concepts=None,   # list[{item_no, concept, details}], see backend/metadata/metadata_excel.py parse_concepts
    meta_real_classifications=None,  # {sheet_name: [{code, value, definition}]}
    catalogue_placement=None,  # {sector, theme, product} from Classify
):
    today = meta_last_updated or date.today().strftime("%B, %Y")
    if isinstance(meta_key_statistics, (dict, list)):
        meta_key_statistics = json.dumps(meta_key_statistics)
    nmds_concepts = meta_nmds_concepts or []
    dataset_ids = []
    table_id_codes = []

    with conn.cursor() as cur:
        # ── Insert all datasets + rows ──────────────────────────────────────
        for i, table in enumerate(tables):
            enriched = enriched_data[i] if i < len(enriched_data) else {}

            # table["id"] was built during extraction as DDI_DEL_DES_VS_... format.
            # Use it as dataset_id, table_id, and unique_dataset_id — all three stay in sync.
            ds_id = table.get("id") or _make_dataset_id(table, i)
            table_code = ds_id          # table_id === dataset_id
            unique_ds_id = ds_id        # unique_dataset_id === dataset_id
            dataset_ids.append(ds_id)
            table_id_codes.append(table_code)

            columns = table.get("columns", [])
            rows = table.get("rows", [])
            # Ensure dict rows for storage / later classification rebuild.
            normalized_rows = []
            col_names = [
                (c if isinstance(c, str) else str((c or {}).get("name") or f"column_{i + 1}"))
                for i, c in enumerate(columns or [])
            ]
            for row in rows or []:
                if isinstance(row, dict):
                    normalized_rows.append(row)
                elif isinstance(row, (list, tuple)):
                    normalized_rows.append({
                        col_names[j]: (row[j] if j < len(row) else None)
                        for j in range(len(col_names))
                    })
            rows = normalized_rows

            # Table-derived classifications are the baseline (critical for SQL
            # and Excel without a classifications workbook). LLM + metadata
            # workbook lists overlay and win on conflicting keys.
            table_cls = _classifications_from_table_data([{
                "columns": col_names,
                "rows": rows,
            }])
            classifications = _merge_real_classifications(
                table_cls,
                _merge_real_classifications(
                    enriched.get("classifications") or {},
                    meta_real_classifications,
                ),
            )
            age_column_keys = enriched.get("age_column_keys") or {}

            cur.execute("""
                INSERT INTO datasets (
                    dataset_id, unique_dataset_id, table_id, metadata_id,
                    title, short_description, long_description,
                    category, geography, frequency, time_period,
                    data_source, units, classifications, concepts, age_column_keys,
                    source_excel, original_excel, user_email
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s
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
                    user_email = EXCLUDED.user_email
            """, (
                ds_id,
                unique_ds_id,
                table_code,
                metadata_id if metadata_mode == "existing" else None,
                table.get("title") or table.get("table_id", ""),
                enriched.get("short_description") or table.get("title", ""),
                enriched.get("long_description") or table.get("title", ""),
                meta_category,
                meta_geography,
                meta_frequency,
                meta_time_period,
                meta_data_source,
                enriched.get("units") or "Count",
                json.dumps(classifications),
                STANDARD_CONCEPTS,
                json.dumps(age_column_keys),
                table.get("source_excel_url"),
                table.get("original_excel_url"),
                user_email,
            ))

            # Re-pushing the same table (e.g. re-running the notebook) must not
            # accumulate duplicate rows -- dataset_rows has no unique constraint
            # of its own, so clear out this dataset's old rows first.
            cur.execute("DELETE FROM dataset_rows WHERE dataset_id = %s", (ds_id,))

            for row_index, row in enumerate(rows):
                cur.execute("""
                    INSERT INTO dataset_rows (dataset_id, sl_no, row_index, row_data, user_email)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    ds_id,
                    _extract_sl_no(row, row_index),
                    row_index,
                    json.dumps(row, default=str),
                    user_email,
                ))

        # ── Handle metadata group ───────────────────────────────────────────
        if metadata_mode == "new":
            metadata_id = f"AUTO-{re.sub(r'[^A-Z0-9]', '-', (meta_title or 'DATA').upper())[:20]}-{uuid.uuid4().hex[:6]}"

            group_classifications = _merge_real_classifications(
                _classifications_from_table_data(tables),
                _merge_real_classifications(
                    _merge_classifications(enriched_data),
                    meta_real_classifications,
                ),
            )

            # Build full_record to mirror DES catalogue JSON file structure
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
                        "short_description": (enriched_data[j].get("short_description") if j < len(enriched_data) else "") or "",
                        "long_description": (enriched_data[j].get("long_description") if j < len(enriched_data) else "") or "",
                    }
                    for j in range(len(tables))
                ],
            }

            cur.execute("""
                INSERT INTO metadata_groups (
                    metadata_id, title, description, product, category, geography,
                    frequency, time_period, data_source, last_updated_date,
                    future_release, key_statistics, remarks,
                    metadata_excel, table_ids, classifications, concepts, full_record,
                    user_email, nmds_concepts
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s
                )
            """, (
                metadata_id,
                meta_title,
                meta_description,
                meta_product,
                meta_category,
                meta_geography,
                meta_frequency,
                meta_time_period,
                meta_data_source,
                today,
                meta_future_release,
                meta_key_statistics,
                meta_remarks,
                meta_excel_filename,
                dataset_ids,
                json.dumps(group_classifications),
                STANDARD_CONCEPTS,
                json.dumps(full_record),
                user_email,
                json.dumps(nmds_concepts),
            ))

            placement = catalogue_placement or {}
            cur.execute("""
                UPDATE metadata_groups
                SET sector = %s, theme = %s, catalogue_product = %s
                WHERE metadata_id = %s
            """, (
                placement.get("sector"),
                placement.get("theme"),
                placement.get("product"),
                metadata_id,
            ))

            # Back-fill metadata_id on datasets just inserted
            cur.execute("""
                UPDATE datasets SET metadata_id = %s
                WHERE dataset_id = ANY(%s)
            """, (metadata_id, dataset_ids))

        else:
            # existing group: append new dataset_ids to table_ids array
            cur.execute("""
                UPDATE metadata_groups
                SET table_ids        = array_cat(COALESCE(table_ids, '{}'), %s),
                    last_updated_date = %s
                WHERE metadata_id = %s
            """, (dataset_ids, today, metadata_id))

    conn.commit()

    return {
        "metadata_id": metadata_id,
        "dataset_ids": dataset_ids,
        "tables_pushed": len(tables),
    }
