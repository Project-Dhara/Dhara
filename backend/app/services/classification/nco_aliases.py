"""NCO-2015 occupation code seeding + steward-learned value aliases."""
import os

import psycopg2.extras

# backend/data/… (this file lives under app/services/classification/)
NCO_2015_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data",
    "nco_2015_concordance.csv",
)


def seed_nco_2015(conn, csv_path=NCO_2015_CSV_PATH):
    """Optional local bootstrap: register bundled concordance as a standard.

    Prefer Settings → Classification code configuration for steward uploads.
    When ``backend/data/nco_2015_concordance.csv`` exists, this creates the
    ``NCO 2015`` list entry (and loads ``nco_2015_codes`` if nothing is selected).
    """
    from app.services.standards.classification_standards import ensure_bundled_nco_standard

    created = ensure_bundled_nco_standard(conn, csv_path=csv_path)
    if created:
        return int(created.get("row_count") or 0)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM nco_2015_codes")
        return cur.fetchone()[0]


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
            from app.services.classification.nco_matching import (
                is_non_occupation_aggregate,
                is_usable_nco_alias,
                looks_like_nco_code,
                normalize_occupation_value,
            )
            norm = normalize_occupation_value(raw)
            level = str(a.get("level") or "").strip().lower()
            code = str(a.get("code") or "").strip()
            title = a.get("title")
            if not norm or not code or level not in ("division", "subdivision", "group", "family"):
                continue
            if is_non_occupation_aggregate(raw):
                continue
            # Never learn identity mappings (label stored as code) — they break
            # later Suggest runs by short-circuiting real NCO matching.
            if not looks_like_nco_code(code):
                continue
            if not is_usable_nco_alias({"code": code}, raw):
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
