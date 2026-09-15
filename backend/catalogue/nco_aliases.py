"""NCO-2015 occupation code seeding + steward-learned value aliases."""
import os

import psycopg2.extras

NCO_2015_CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "nco_2015_concordance.csv")


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
            from catalogue.nco_matching import normalize_occupation_value
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
