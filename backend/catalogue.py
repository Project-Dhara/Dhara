import os
import re
import uuid
import json
from datetime import date

import psycopg2
import psycopg2.extras


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


def get_connection():
    url = os.environ["DATABASE_URL"]
    return psycopg2.connect(url)


def init_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS metadata_groups (
                metadata_id       TEXT PRIMARY KEY,
                title             TEXT,
                description       TEXT,
                product           TEXT,
                category          TEXT,
                geography         TEXT,
                frequency         TEXT,
                time_period       TEXT,
                data_source       TEXT,
                last_updated_date TEXT,
                future_release    TEXT,
                key_statistics    TEXT,
                remarks           TEXT,
                metadata_excel    TEXT,
                table_ids         TEXT[],
                classifications   JSONB DEFAULT '{}',
                concepts          TEXT[] DEFAULT '{}',
                full_record       JSONB DEFAULT '{}'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS datasets (
                dataset_id         TEXT PRIMARY KEY,
                unique_dataset_id  TEXT,
                table_id           TEXT,
                metadata_id        TEXT REFERENCES metadata_groups,
                title              TEXT,
                short_description  TEXT,
                long_description   TEXT,
                category           TEXT,
                geography          TEXT,
                frequency          TEXT,
                time_period        TEXT,
                data_source        TEXT,
                units              TEXT,
                classifications    JSONB DEFAULT '{}',
                concepts           TEXT[] DEFAULT '{}',
                age_column_keys    JSONB DEFAULT '{}',
                source_excel       TEXT,
                original_excel     TEXT
            )
        """)
        cur.execute("""
            ALTER TABLE datasets ADD COLUMN IF NOT EXISTS source_excel TEXT
        """)
        cur.execute("""
            ALTER TABLE datasets ADD COLUMN IF NOT EXISTS original_excel TEXT
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS dataset_rows (
                id         SERIAL PRIMARY KEY,
                dataset_id TEXT REFERENCES datasets ON DELETE CASCADE,
                sl_no      TEXT,
                row_index  INTEGER,
                row_data   JSONB NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_datasets_metadata_id
                ON datasets (metadata_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_dataset_rows_dataset_id
                ON dataset_rows (dataset_id)
        """)
    conn.commit()


def list_metadata_groups(conn):
    # Returns the full field set (not just display fields) so the frontend
    # can prefill an edit form when a user adds tables to an existing group.
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT
                metadata_id,
                title,
                description,
                product,
                category,
                geography,
                frequency,
                time_period,
                data_source,
                last_updated_date,
                future_release,
                key_statistics,
                remarks,
                array_length(table_ids, 1) AS table_count
            FROM metadata_groups
            ORDER BY title
        """)
        rows = cur.fetchall()
    return [dict(r) for r in rows]



def _make_dataset_id(table: dict, index: int) -> str:
    """Fallback dataset_id when table has no pre-built id."""
    suffix = uuid.uuid4().hex[:6]
    return f"DS-{index+1:03d}-{suffix}"


def _extract_sl_no(row: dict, row_index: int) -> str:
    """Try to find the serial number value from a row dict."""
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
):
    today = meta_last_updated or date.today().strftime("%B, %Y")
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

            # Merge classifications from enriched data
            classifications = enriched.get("classifications") or {}
            age_column_keys = enriched.get("age_column_keys") or {}

            cur.execute("""
                INSERT INTO datasets (
                    dataset_id, unique_dataset_id, table_id, metadata_id,
                    title, short_description, long_description,
                    category, geography, frequency, time_period,
                    data_source, units, classifications, concepts, age_column_keys,
                    source_excel, original_excel
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s
                )
            """, (
                ds_id,
                unique_ds_id,
                table_code,
                metadata_id if metadata_mode == "existing" else None,
                table.get("description") or table.get("title", ""),
                enriched.get("short_description") or table.get("description", ""),
                enriched.get("long_description") or table.get("description", ""),
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
            ))

            for row_index, row in enumerate(rows):
                cur.execute("""
                    INSERT INTO dataset_rows (dataset_id, sl_no, row_index, row_data)
                    VALUES (%s, %s, %s, %s)
                """, (
                    ds_id,
                    _extract_sl_no(row, row_index),
                    row_index,
                    json.dumps(row, default=str),
                ))

        # ── Handle metadata group ───────────────────────────────────────────
        if metadata_mode == "new":
            metadata_id = f"AUTO-{re.sub(r'[^A-Z0-9]', '-', (meta_title or 'DATA').upper())[:20]}-{uuid.uuid4().hex[:6]}"

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
                "classifications": _merge_classifications(enriched_data),
                "concepts": STANDARD_CONCEPTS,
                "dataset_inventory_list": [
                    {
                        "dataset_id": dataset_ids[j],
                        "table_id": table_id_codes[j],
                        "title": tables[j].get("description") or tables[j].get("title", ""),
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
                    metadata_excel, table_ids, classifications, concepts, full_record
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s
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
                json.dumps(_merge_classifications(enriched_data)),
                STANDARD_CONCEPTS,
                json.dumps(full_record),
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


def _merge_classifications(enriched_data: list) -> dict:
    """Merge classifications across all enriched tables, deduplicating values per dimension."""
    merged: dict = {}
    for enriched in enriched_data:
        cls = enriched.get("classifications") or {}
        for dim, vals in cls.items():
            if dim not in merged:
                merged[dim] = []
            for v in vals:
                if v not in merged[dim]:
                    merged[dim].append(v)
    return merged
