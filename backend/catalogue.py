import os
import re
import uuid
import json
from datetime import date
from pathlib import Path
from typing import Optional

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
    # Host-oriented .env often uses localhost; inside Compose that must be the
    # postgres service (sql_extract rewrite covers SQL upload DSNs separately).
    if Path("/.dockerenv").exists():
        from urllib.parse import urlparse, urlunparse, quote_plus

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1", "host.docker.internal"):
            userinfo = ""
            if parsed.username is not None:
                userinfo = quote_plus(parsed.username)
                if parsed.password is not None:
                    userinfo += ":" + quote_plus(parsed.password)
                userinfo += "@"
            port = parsed.port or 5432
            url = urlunparse(
                (parsed.scheme, f"{userinfo}postgres:{port}", parsed.path, parsed.params, parsed.query, parsed.fragment)
            )
    return psycopg2.connect(url)


def init_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                email          TEXT PRIMARY KEY,
                password_hash  TEXT NOT NULL,
                name           TEXT,
                dept           TEXT,
                created_at     TIMESTAMPTZ DEFAULT NOW()
            )
        """)
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
                full_record       JSONB DEFAULT '{}',
                user_email        TEXT
            )
        """)
        cur.execute("""
            ALTER TABLE metadata_groups ADD COLUMN IF NOT EXISTS user_email TEXT
        """)
        cur.execute("""
            ALTER TABLE metadata_groups ADD COLUMN IF NOT EXISTS nmds_concepts JSONB DEFAULT '{}'
        """)
        cur.execute("""
            ALTER TABLE metadata_groups ADD COLUMN IF NOT EXISTS sector TEXT
        """)
        cur.execute("""
            ALTER TABLE metadata_groups ADD COLUMN IF NOT EXISTS theme TEXT
        """)
        cur.execute("""
            ALTER TABLE metadata_groups ADD COLUMN IF NOT EXISTS catalogue_product TEXT
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
                original_excel     TEXT,
                user_email         TEXT
            )
        """)
        cur.execute("""
            ALTER TABLE datasets ADD COLUMN IF NOT EXISTS source_excel TEXT
        """)
        cur.execute("""
            ALTER TABLE datasets ADD COLUMN IF NOT EXISTS original_excel TEXT
        """)
        cur.execute("""
            ALTER TABLE datasets ADD COLUMN IF NOT EXISTS user_email TEXT
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS dataset_rows (
                id         SERIAL PRIMARY KEY,
                dataset_id TEXT REFERENCES datasets ON DELETE CASCADE,
                sl_no      TEXT,
                row_index  INTEGER,
                row_data   JSONB NOT NULL,
                user_email TEXT
            )
        """)
        cur.execute("""
            ALTER TABLE dataset_rows ADD COLUMN IF NOT EXISTS user_email TEXT
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_datasets_metadata_id
                ON datasets (metadata_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_dataset_rows_dataset_id
                ON dataset_rows (dataset_id)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kyds_entries (
                id          SERIAL PRIMARY KEY,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                user_email  TEXT,
                user_name   TEXT,
                user_dept   TEXT,
                responses   JSONB NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_kyds_entries_created_at
                ON kyds_entries (created_at DESC)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nco_2015_codes (
                nco_code           TEXT PRIMARY KEY,
                occupation_title   TEXT NOT NULL,
                division_code      TEXT,
                division_title     TEXT,
                subdivision_code   TEXT,
                subdivision_title  TEXT,
                group_code         TEXT,
                group_title        TEXT,
                family_code        TEXT,
                family_title       TEXT,
                qp_nos_reference   TEXT
            )
        """)
        # Steward-learned mappings from Classify verify — not a hardcoded label list.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nco_value_aliases (
                normalized_value TEXT PRIMARY KEY,
                level            TEXT NOT NULL,
                code             TEXT NOT NULL,
                title            TEXT,
                source           TEXT DEFAULT 'steward',
                updated_at       TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    conn.commit()

    # Stage 6 — pgvector embeddings store (ancillary to authoritative tables above).
    try:
        import vector_store as _vs
        _vs.ensure_semantic_embeddings_table(conn)
    except Exception as exc:
        # Non-pgvector Postgres (e.g. managed DB without the extension) must
        # not break catalogue init; surface via /api/health when available.
        # Critical: roll back so the connection is usable for later queries
        # (otherwise callers hit InFailedSqlTransaction).
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[catalogue.init_schema] pgvector setup skipped: {exc}")

    # PDF pipeline authoritative tables (Preview → Grouping).
    try:
        import pdf_store as _pdf_store
        _pdf_store.init_pdf_schema(conn)
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[catalogue.init_schema] pdf_store setup skipped: {exc}")

    # Excel/SQL extract staging for slim batch-push payloads.
    try:
        import extract_staging as _staging
        _staging.init_staging_schema(conn)
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[catalogue.init_schema] extract_staging setup skipped: {exc}")


NCO_2015_CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "nco_2015_concordance.csv")


def seed_nco_2015(conn, csv_path=NCO_2015_CSV_PATH):
    """Load the concordance CSV into nco_2015_codes if the table is empty."""
    import csv as _csv
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM nco_2015_codes")
        if cur.fetchone()[0] > 0:
            return 0
    if not os.path.exists(csv_path):
        return 0
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for r in _csv.DictReader(f):
            code = (r.get("NCO_2015_Code") or "").strip()
            title = (r.get("Occupation_Title") or "").strip()
            if not code or not title:
                continue
            rows.append((
                code, title,
                (r.get("Division_Code") or "").strip(),
                (r.get("Division_Title") or "").strip(),
                (r.get("SubDivision_Code") or "").strip(),
                (r.get("SubDivision_Title") or "").strip(),
                (r.get("Group_Code") or "").strip(),
                (r.get("Group_Title") or "").strip(),
                (r.get("Family_Code") or "").strip(),
                (r.get("Family_Title") or "").strip(),
                (r.get("QP_NOS_Reference") or "").strip(),
            ))
    if not rows:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO nco_2015_codes (
                nco_code, occupation_title,
                division_code, division_title,
                subdivision_code, subdivision_title,
                group_code, group_title,
                family_code, family_title,
                qp_nos_reference
            ) VALUES %s
            ON CONFLICT (nco_code) DO NOTHING
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def lookup_nco_alias(conn, normalized_value: str):
    """Return a learned alias row dict or None."""
    if not normalized_value:
        return None
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT normalized_value, level, code, title, source
              FROM nco_value_aliases
             WHERE normalized_value = %s
            """,
            (normalized_value,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def upsert_nco_aliases(conn, aliases: list, source: str = "steward") -> int:
    """Persist steward-verified occupation → NCO mappings. Each item:
    {normalized_value|value, level, code, title?}."""
    if not aliases:
        return 0
    saved = 0
    with conn.cursor() as cur:
        for a in aliases:
            if not isinstance(a, dict):
                continue
            raw = a.get("normalized_value") or a.get("value") or ""
            # Lazy import to avoid circular import at module load.
            from nco_matching import normalize_occupation_value
            norm = normalize_occupation_value(raw)
            level = str(a.get("level") or "").strip().lower()
            code = str(a.get("code") or "").strip()
            title = a.get("title")
            if not norm or not code or level not in ("division", "subdivision", "group", "family"):
                continue
            if level == "group":
                level = "subdivision"
            cur.execute(
                """
                INSERT INTO nco_value_aliases (normalized_value, level, code, title, source, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (normalized_value) DO UPDATE SET
                    level = EXCLUDED.level,
                    code = EXCLUDED.code,
                    title = EXCLUDED.title,
                    source = EXCLUDED.source,
                    updated_at = NOW()
                """,
                (norm, level, code, title, source),
            )
            saved += 1
    conn.commit()
    return saved


def save_kyds_entry(conn, responses, user=None):
    """Persist a KYDS (Know Your Dataset) form submission for later use."""
    user = user or {}
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO kyds_entries (user_email, user_name, user_dept, responses)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (
            user.get("email"),
            user.get("name"),
            user.get("dept"),
            json.dumps(responses),
        ))
        entry_id = cur.fetchone()[0]
    conn.commit()
    return entry_id


def get_latest_kyds_responses(conn, user_email):
    """Returns the most recent KYDS form responses submitted by this user, or
    None if this user hasn't submitted one. Used to ground Stage 4 LLM
    metadata generation in real, DB-stored context -- deliberately no
    fallback to another user's entry: if this user hasn't done KYDS, Stage 4
    must not fabricate metadata from a stranger's answers, and should leave
    the fields for manual entry instead."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT responses FROM kyds_entries
            WHERE user_email = %s
            ORDER BY created_at DESC LIMIT 1
        """, (user_email,))
        row = cur.fetchone()
    return row["responses"] if row else None


def get_own_latest_kyds_entry(conn, user_email):
    """Returns this user's own most recent KYDS submission (id, responses,
    created_at), or None — used to show/edit "your" KYDS entry in the
    console."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id, responses, created_at FROM kyds_entries
            WHERE user_email = %s
            ORDER BY created_at DESC LIMIT 1
        """, (user_email,))
        row = cur.fetchone()
    return dict(row) if row else None


def create_user(conn, email, password_hash, name=None, dept=None):
    """Provision (or update) a login. Admin-only — see create_user.py."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO users (email, password_hash, name, dept)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (email) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    name          = COALESCE(EXCLUDED.name, users.name),
                    dept          = COALESCE(EXCLUDED.dept, users.dept)
        """, (email, password_hash, name, dept))
    conn.commit()


def get_user_by_email(conn, email):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT email, password_hash, name, dept FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
    return dict(row) if row else None


def _normalize_code_entry(entry):
    """A classification entry is normally {code, value, definition} (from the
    real metadata-excel parse). But when no metadata-excel sheet covered a
    dimension, the LLM-guessed fallback stores it as a flat list of plain
    value strings instead — normalize those too so the frontend always gets
    a consistent {code, value, definition} shape."""
    if isinstance(entry, dict):
        return {"code": entry.get("code"), "value": entry.get("value"), "definition": entry.get("definition")}
    return {"code": entry, "value": entry, "definition": None}


def get_metadata_group_classifications(conn, metadata_id):
    """Read metadata_groups.classifications for the Classify step, reshaped
    into the [{name, concept, note, codes}] array the frontend expects."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT classifications FROM metadata_groups WHERE metadata_id = %s",
                (metadata_id,),
            )
            row = cur.fetchone()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    if not row:
        return None

    classifications = row[0] or {}
    if isinstance(classifications, str):
        try:
            classifications = json.loads(classifications) or {}
        except Exception:
            classifications = {}
    if not isinstance(classifications, dict):
        classifications = {}

    if not classifications:
        try:
            classifications = _classifications_from_linked_datasets(conn, metadata_id) or {}
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"[catalogue] rebuild classifications failed for {metadata_id}: {exc}")
            classifications = {}

    columns = []
    for name, codes in classifications.items():
        norm = _normalize_classification_values(codes)
        if not norm:
            continue
        columns.append({
            "name": name,
            "concept": name,
            "note": "",
            "codes": norm,
        })
    if not columns:
        # Last resort: rebuild from linked dataset rows (SQL / no workbook).
        try:
            rebuilt = _classifications_from_linked_datasets(conn, metadata_id) or {}
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"[catalogue] linked-dataset rebuild failed for {metadata_id}: {exc}")
            rebuilt = {}
        for name, codes in rebuilt.items():
            norm = _normalize_classification_values(codes)
            if norm:
                columns.append({
                    "name": name,
                    "concept": name,
                    "note": "",
                    "codes": norm,
                })
    return columns


def get_definition_facts(conn, metadata_id):
    """Compact catalogue + workbook facts for filling classification definitions."""
    if not metadata_id:
        return {}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT title, description, product, category, geography, frequency,
                   time_period, data_source, key_statistics, full_record
            FROM metadata_groups WHERE metadata_id = %s
        """, (metadata_id,))
        row = cur.fetchone()
    if not row:
        return {}
    rec = row[9] or {}
    inventory = rec.get("dataset_inventory_list") or []
    return {
        "title": row[0],
        "description": row[1],
        "product": row[2],
        "category": row[3],
        "geography": row[4],
        "frequency": row[5],
        "time_period": row[6],
        "data_source": row[7],
        "key_statistics": row[8],
        "tables": [
            {
                "title": t.get("title"),
                "short_description": t.get("short_description"),
            }
            for t in inventory[:10]
            if isinstance(t, dict)
        ],
    }


def get_recent_classification_columns(conn, user_email, limit=12):
    """Fallback when the frontend has no metadataIds in session: the most
    recently pushed groups for this user."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT metadata_id FROM metadata_groups
            WHERE user_email = %s
            ORDER BY last_updated_date DESC NULLS LAST, metadata_id DESC
            LIMIT %s
        """, (user_email, limit))
        ids = [r[0] for r in cur.fetchall()]
    columns = []
    for mid in ids:
        cols = get_metadata_group_classifications(conn, mid) or []
        for c in cols:
            columns.append({**c, "_metadataId": mid})
    return columns


def _nmds_concepts_as_list(raw):
    """Normalise stored concept JSON (list of rows, {concept: details}, or wrapped {standard, concepts})."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict) and "concepts" in raw and isinstance(raw.get("concepts"), (list, dict)):
        return _nmds_concepts_as_list(raw.get("concepts"))
    if isinstance(raw, dict):
        return [
            {"item_no": "", "concept": k, "code": "", "details": v or ""}
            for k, v in raw.items()
            if k != "standard" and str(v or "").strip()
        ]
    out = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        details = row.get("details") or ""
        if not str(details).strip():
            continue
        out.append({
            "item_no": row.get("item_no") or "",
            "concept": row.get("concept") or "",
            "code": row.get("code") or "",
            "details": details,
        })
    return out


def _metadata_standard_from_concepts(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if isinstance(raw, dict) and raw.get("standard"):
        return raw.get("standard")
    return None


def list_catalogue_datasets(conn):
    """Published datasets for the catalogue page (everything in `datasets`)."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT
              d.dataset_id,
              d.title,
              d.short_description,
              d.long_description,
              d.geography,
              d.frequency,
              d.time_period,
              d.data_source,
              d.classifications,
              d.category,
              d.metadata_id,
              m.sector,
              m.theme,
              m.catalogue_product,
              m.nmds_concepts,
              m.last_updated_date,
              (SELECT COUNT(*)::int FROM dataset_rows r WHERE r.dataset_id = d.dataset_id) AS row_count
            FROM datasets d
            LEFT JOIN metadata_groups m ON m.metadata_id = d.metadata_id
            ORDER BY m.last_updated_date DESC NULLS LAST, d.dataset_id DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]

    out = []
    for row in rows:
        cls = row.get("classifications") or {}
        if isinstance(cls, str):
            try:
                cls = json.loads(cls)
            except json.JSONDecodeError:
                cls = {}
        facets = list(cls.keys()) if isinstance(cls, dict) else []
        title = row.get("title") or row["dataset_id"]
        geo = row.get("geography") or "—"
        freq = row.get("frequency") or "—"
        source = row.get("data_source") or "—"
        summary = (row.get("long_description") or row.get("short_description") or "").strip() or title
        tags = []
        for x in (row.get("theme"), row.get("catalogue_product"), row.get("sector"), row.get("category"), geo):
            if x and str(x).strip() and str(x) not in tags:
                tags.append(str(x).strip())
        for f in facets:
            if f not in tags:
                tags.append(f)
        keywords = " ".join(
            str(x) for x in [
                row["dataset_id"], title, geo, freq, source,
                row.get("theme"), row.get("catalogue_product"), *facets,
            ] if x
        ).lower()
        nmds = _nmds_concepts_as_list(row.get("nmds_concepts"))
        out.append({
            "id": row["dataset_id"],
            "title": title,
            "rows": str(row.get("row_count") or 0),
            "geo": geo,
            "freq": freq,
            "source": source,
            "access": "Public",
            "summary": summary,
            "nmds_concepts": nmds,
            "metadata_standard": _metadata_standard_from_concepts(row.get("nmds_concepts")),
            "keywords": keywords,
            "facets": facets,
            "tags": tags[:16],
            "theme": row.get("theme"),
            "product": row.get("catalogue_product"),
            "time_period": row.get("time_period"),
            "metadata_id": row.get("metadata_id"),
        })
    return out


def _classifications_from_linked_datasets(conn, metadata_id):
    """If the metadata group was saved with empty classifications (LLM skipped),
    rebuild them from per-dataset JSON and, failing that, from stored rows."""
    merged = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT classifications FROM datasets WHERE metadata_id = %s",
            (metadata_id,),
        )
        for (ds_cls,) in cur.fetchall():
            for name, codes in (ds_cls or {}).items():
                if name not in merged and codes:
                    merged[name] = codes
        if merged:
            return merged
        cur.execute("""
            SELECT dr.row_data
            FROM datasets d
            JOIN dataset_rows dr ON dr.dataset_id = d.dataset_id
            WHERE d.metadata_id = %s
            ORDER BY d.dataset_id, dr.row_index
        """, (metadata_id,))
        rows = [r[0] or {} for r in cur.fetchall()]
    if not rows:
        return {}
    cols = list(rows[0].keys())
    return _classifications_from_table_data([{"columns": cols, "rows": rows}])


def _normalize_classification_values(vals) -> list:
    """Coerce LLM / workbook / heuristic classification entries to a list of
    {code, value, definition} dicts. Handles list[str], list[dict], a lone
    string (must not iterate characters), and empty/invalid inputs."""
    if vals is None:
        return []
    if isinstance(vals, str):
        s = vals.strip()
        return [{"code": s, "value": s, "definition": None}] if s else []
    if isinstance(vals, dict):
        # Single code-list entry shaped as a dict.
        if any(k in vals for k in ("code", "value", "definition")):
            return [_normalize_code_entry(vals)]
        # Rare LLM shape: {"values": [...]}
        if isinstance(vals.get("values"), list):
            return _normalize_classification_values(vals.get("values"))
        return []
    if not isinstance(vals, (list, tuple)):
        s = str(vals).strip()
        return [{"code": s, "value": s, "definition": None}] if s else []

    out = []
    seen = set()
    for v in vals:
        if isinstance(v, str):
            s = v.strip()
            if not s:
                continue
            entry = {"code": s, "value": s, "definition": None}
        else:
            entry = _normalize_code_entry(v)
        key = (str(entry.get("value") or entry.get("code") or "").strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def _classifications_from_table_data(tables):
    """Treat low-cardinality non-numeric columns as classification dimensions.

    Used for Excel without a classifications workbook and for SQL extracts,
    where there is no metadata-excel code list."""
    merged = {}
    for table in tables or []:
        raw_columns = table.get("columns") or []
        columns = []
        for i, col in enumerate(raw_columns):
            if isinstance(col, str):
                columns.append(col)
            elif isinstance(col, dict):
                columns.append(str(col.get("name") or f"column_{i + 1}"))
            else:
                columns.append(f"column_{i + 1}")
        rows = table.get("rows") or []
        for col in columns:
            values, seen = [], set()
            for row in rows:
                if isinstance(row, dict):
                    raw = row.get(col)
                elif isinstance(row, (list, tuple)):
                    # Positional rows (rare in Excel/SQL path) — skip; need names.
                    continue
                else:
                    continue
                if raw is None or raw == "":
                    continue
                if isinstance(raw, bool):
                    s = "true" if raw else "false"
                else:
                    s = str(raw).strip()
                if not s:
                    continue
                # Skip pure numerics (measures), keep codes like "01" that are
                # categorical when mixed with non-numeric — only skip if the
                # whole string parses as a number AND has no alpha.
                if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", s.replace(",", "")):
                    continue
                key = s.lower()
                if key in seen:
                    continue
                seen.add(key)
                values.append({"code": s, "value": s, "definition": None})
                if len(values) > 80:
                    break
            if 2 <= len(values) <= 80:
                name = re.sub(r"\s+", "_", str(col).strip()) or str(col)
                if name not in merged:
                    merged[name] = values
                else:
                    existing = {(e.get("value") or "").lower() for e in merged[name]}
                    for e in values:
                        if (e["value"] or "").lower() not in existing:
                            merged[name].append(e)
                            existing.add((e["value"] or "").lower())
    return merged


def _merge_real_classifications(llm_merged, real):
    """Real metadata-excel code lists win per column name; LLM/heuristic
    guesses fill columns the workbook didn't cover. Values are normalized."""
    merged = {
        str(k): _normalize_classification_values(v)
        for k, v in (llm_merged or {}).items()
        if _normalize_classification_values(v)
    }
    for k, v in (real or {}).items():
        norm = _normalize_classification_values(v)
        if norm:
            merged[str(k)] = norm
    return merged


def _classification_value_key(entries):
    vals = []
    for e in entries or []:
        if isinstance(e, dict):
            v = str(e.get("value") or "").strip().lower()
        else:
            v = str(e).strip().lower()
        if v:
            vals.append(v)
    return tuple(sorted(vals))


def _is_occupation_name(name):
    return bool(re.search(r"occupat", name or "", re.I))


def _expand_alias_names(classifications, names, codes):
    """Include hidden duplicate columns that share the same value list."""
    names = [n for n in names if n]
    target = _classification_value_key(codes)
    if not target:
        return names
    occ = any(_is_occupation_name(n) for n in names)
    extra = [
        n for n, ents in (classifications or {}).items()
        if n not in names
        and _is_occupation_name(n) == occ
        and _classification_value_key(ents) == target
    ]
    return names + extra


def update_metadata_group_classification_column(
    conn, metadata_id, column_name, codes, column_names=None, expand_aliases=True,
):
    """Persist code/definition rows to the metadata group and every linked
    dataset table. expand_aliases copies to hidden same-value columns."""
    names = [n for n in (column_names or [column_name]) if n]
    if not names:
        return False
    with conn.cursor() as cur:
        cur.execute("SELECT classifications FROM metadata_groups WHERE metadata_id = %s FOR UPDATE", (metadata_id,))
        row = cur.fetchone()
        if not row:
            return False
        classifications = row[0] or {}
        if expand_aliases:
            names = _expand_alias_names(classifications, names, codes)
        for name in names:
            classifications[name] = codes
        cur.execute(
            "UPDATE metadata_groups SET classifications = %s WHERE metadata_id = %s",
            (json.dumps(classifications), metadata_id),
        )
        cur.execute(
            "SELECT dataset_id, classifications FROM datasets WHERE metadata_id = %s FOR UPDATE",
            (metadata_id,),
        )
        for dataset_id, ds_cls in cur.fetchall():
            ds_cls = dict(ds_cls or {})
            ds_names = _expand_alias_names(ds_cls, names, codes) if expand_aliases else names
            changed = False
            for name in ds_names:
                if ds_cls.get(name) != codes:
                    ds_cls[name] = codes
                    changed = True
            if changed:
                cur.execute(
                    "UPDATE datasets SET classifications = %s WHERE dataset_id = %s",
                    (json.dumps(ds_cls), dataset_id),
                )
    conn.commit()
    return True


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
    meta_nmds_concepts=None,   # list[{item_no, concept, details}], see backend/metadata_excel.py parse_concepts
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


def _merge_classifications(enriched_data: list) -> dict:
    """Merge classifications across all enriched tables, deduplicating values per dimension."""
    merged: dict = {}
    for enriched in enriched_data:
        cls = enriched.get("classifications") or {}
        for dim, vals in cls.items():
            norm = _normalize_classification_values(vals)
            if not norm:
                continue
            if dim not in merged:
                merged[dim] = []
            existing = {(e.get("value") or "").lower() for e in merged[dim]}
            for entry in norm:
                key = (entry.get("value") or "").lower()
                if key and key not in existing:
                    merged[dim].append(entry)
                    existing.add(key)
    return merged


def _classification_fill_ratio(classifications) -> float:
    """Share of classification entries that have a non-empty definition."""
    if not isinstance(classifications, dict) or not classifications:
        return 0.0
    total = 0
    filled = 0
    for codes in classifications.values():
        if not isinstance(codes, list):
            continue
        for entry in codes:
            total += 1
            if isinstance(entry, dict):
                if str(entry.get("definition") or "").strip():
                    filled += 1
            # Plain strings are codes without definitions — not filled.
    if total == 0:
        return 0.0
    return filled / total


def _infer_source_label(data_source: Optional[str], fallback: str = "—") -> str:
    s = str(data_source or "").strip()
    if not s:
        return fallback
    low = s.lower()
    if "pdf" in low:
        return "PDF"
    if low.endswith(".xlsx") or low.endswith(".xls") or "excel" in low or "xlsx" in low:
        return "XLSX"
    if low.endswith(".csv") or "csv" in low:
        return "CSV"
    if "sql" in low or "postgres" in low or "database" in low:
        return "SQL"
    return s[:32]


def list_dashboard(conn, user_email: str) -> dict:
    """
    Dataset readiness snapshot for the Dashboard.

    Catalogue metadata groups only exist after the Metadata push (console
    step 4), so they are always at Classification (5) or Published (6).
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT
              m.metadata_id,
              m.title,
              m.catalogue_product,
              m.product,
              m.data_source,
              m.classifications,
              m.last_updated_date,
              m.user_email,
              (SELECT COUNT(*)::int FROM datasets d WHERE d.metadata_id = m.metadata_id) AS dataset_count
            FROM metadata_groups m
            WHERE m.user_email = %s
            ORDER BY m.last_updated_date DESC NULLS LAST, m.metadata_id DESC
        """, (user_email,))
        groups = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT COUNT(*)::int FROM datasets WHERE user_email = %s
        """, (user_email,))
        dataset_count = cur.fetchone()["count"]

    products = set()
    rows = []
    awaiting = 0
    published = 0

    for g in groups:
        cls = g.get("classifications") or {}
        if isinstance(cls, str):
            try:
                cls = json.loads(cls)
            except json.JSONDecodeError:
                cls = {}
        fill = _classification_fill_ratio(cls)
        has_dims = isinstance(cls, dict) and bool(cls)
        product = (g.get("catalogue_product") or g.get("product") or "").strip()
        if product:
            products.add(product)
        title = (g.get("title") or g["metadata_id"]).strip()
        source = _infer_source_label(g.get("data_source"), "Catalogue")
        ds_n = int(g.get("dataset_count") or 0)

        # Metadata already pushed → never "Metadata review".
        if has_dims and fill >= 0.9:
            status = "Published"
            status_key = "published"
            pct = 100
            action = "View"
            href = "/catalogue"
            published += max(ds_n, 1)
        else:
            status = "Classification review"
            status_key = "classification_review"
            # Step 5 band: 75–95% as definitions are filled in.
            pct = int(round(75 + (fill * 20 if has_dims else 0)))
            action = "Review"
            href = "/console"
            awaiting += 1

        updated = g.get("last_updated_date")
        rows.append({
            "id": g["metadata_id"],
            "kind": "catalogue_group",
            "name": title,
            "source": source,
            "product": product or "—",
            "readiness_pct": pct,
            "status": status,
            "status_key": status_key,
            "action": action,
            "href": href,
            "metadata_id": g["metadata_id"],
            "dataset_count": ds_n,
            "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else updated,
        })

    return {
        "stats": {
            "datasets": dataset_count,
            "data_products": len(products),
            "awaiting_review": awaiting,
            "published": published,
        },
        "rows": rows,
    }
