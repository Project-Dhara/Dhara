"""User-uploaded classification concordance CSVs stored in Postgres.

Matching still reads the active working set from ``nco_2015_codes`` (unchanged
suggestion logic). Selecting a standard replaces that table from the stored
upload so Classify uses the steward's chosen file.
"""
from __future__ import annotations

import csv
import io
import re

import psycopg2.extras

# Same columns as the NCO 2015 concordance template (see
# backend/data/nco_2015_concordance.csv.example).
REQUIRED_COLUMNS = ("NCO_2015_Code", "Occupation_Title")
OPTIONAL_COLUMNS = (
    "Division_Code",
    "Division_Title",
    "SubDivision_Code",
    "SubDivision_Title",
    "Group_Code",
    "Group_Title",
    "Family_Code",
    "Family_Title",
    "QP_NOS_Reference",
)


def _clear_matching_cache():
    try:
        from catalogue import nco_matching as _nco

        _nco.clear_codes_cache()
    except Exception:
        pass


def parse_concordance_csv(content: bytes | str) -> list[tuple]:
    """Parse a concordance CSV into insert tuples for nco_2015_codes shape.

    Raises ValueError with a steward-facing message on bad input.
    """
    if isinstance(content, bytes):
        text = content.decode("utf-8-sig")
    else:
        text = content.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    fields = {(f or "").strip() for f in reader.fieldnames}
    missing = [c for c in REQUIRED_COLUMNS if c not in fields]
    if missing:
        raise ValueError(
            "CSV is missing required columns: "
            + ", ".join(missing)
            + ". Expected the NCO concordance layout "
            "(NCO_2015_Code, Occupation_Title, Division_*, SubDivision_*, …)."
        )
    rows = []
    for r in reader:
        code = (r.get("NCO_2015_Code") or "").strip()
        title = (r.get("Occupation_Title") or "").strip()
        if not code or not title:
            continue
        rows.append((
            code,
            title,
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
        raise ValueError("CSV has no usable occupation rows (need NCO_2015_Code and Occupation_Title)")
    return rows


def _slugify_name(name: str) -> str:
    s = re.sub(r"\s+", " ", (name or "").strip())
    return s


def list_standards(conn) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, name, description, original_filename, row_count,
                   is_selected, uploaded_by, created_at
              FROM classification_standards
             ORDER BY created_at DESC, id DESC
            """
        )
        out = []
        for row in cur.fetchall():
            d = dict(row)
            if d.get("created_at") is not None:
                d["created_at"] = d["created_at"].isoformat()
            out.append(d)
        return out


def _reload_active_into_nco_table(conn, standard_id: int) -> int:
    """Replace nco_2015_codes with rows for the given standard (matching source of truth)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM nco_2015_codes")
        cur.execute(
            """
            INSERT INTO nco_2015_codes (
                nco_code, occupation_title,
                division_code, division_title,
                subdivision_code, subdivision_title,
                group_code, group_title,
                family_code, family_title,
                qp_nos_reference
            )
            SELECT nco_code, occupation_title,
                   division_code, division_title,
                   subdivision_code, subdivision_title,
                   group_code, group_title,
                   family_code, family_title,
                   qp_nos_reference
              FROM classification_standard_codes
             WHERE standard_id = %s
            ON CONFLICT (nco_code) DO NOTHING
            """,
            (standard_id,),
        )
        cur.execute("SELECT COUNT(*) FROM nco_2015_codes")
        count = cur.fetchone()[0]
    _clear_matching_cache()
    return count


def create_standard(
    conn,
    *,
    name: str,
    csv_bytes: bytes,
    original_filename: str | None = None,
    description: str | None = None,
    uploaded_by: str | None = None,
    select: bool = True,
) -> dict:
    display_name = _slugify_name(name)
    if not display_name:
        raise ValueError("Name is required")
    rows = parse_concordance_csv(csv_bytes)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id FROM classification_standards WHERE lower(name) = lower(%s)",
            (display_name,),
        )
        if cur.fetchone():
            raise ValueError(f'A classification standard named "{display_name}" already exists')

        if select:
            cur.execute("UPDATE classification_standards SET is_selected = FALSE")

        cur.execute(
            """
            INSERT INTO classification_standards (
                name, description, original_filename, row_count,
                is_selected, uploaded_by
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, name, description, original_filename, row_count,
                      is_selected, uploaded_by, created_at
            """,
            (
                display_name,
                (description or "").strip() or None,
                (original_filename or "").strip() or None,
                len(rows),
                bool(select),
                uploaded_by,
            ),
        )
        standard = dict(cur.fetchone())
        standard_id = standard["id"]

        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO classification_standard_codes (
                standard_id, nco_code, occupation_title,
                division_code, division_title,
                subdivision_code, subdivision_title,
                group_code, group_title,
                family_code, family_title,
                qp_nos_reference
            ) VALUES %s
            """,
            [(standard_id, *row) for row in rows],
            page_size=500,
        )

    if select:
        _reload_active_into_nco_table(conn, standard_id)
    conn.commit()

    if standard.get("created_at") is not None:
        standard["created_at"] = standard["created_at"].isoformat()
    return standard


def select_standard(conn, standard_id: int) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, name, row_count FROM classification_standards WHERE id = %s",
            (standard_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("Classification standard not found")
        cur.execute("UPDATE classification_standards SET is_selected = FALSE")
        cur.execute(
            "UPDATE classification_standards SET is_selected = TRUE WHERE id = %s",
            (standard_id,),
        )
    loaded = _reload_active_into_nco_table(conn, standard_id)
    conn.commit()
    return {"id": row["id"], "name": row["name"], "row_count": row["row_count"], "loaded": loaded}


def delete_standard(conn, standard_id: int) -> dict:
    next_id = None
    was_selected = False
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, name, is_selected FROM classification_standards WHERE id = %s",
            (standard_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("Classification standard not found")
        was_selected = bool(row["is_selected"])
        cur.execute("DELETE FROM classification_standards WHERE id = %s", (standard_id,))
        if was_selected:
            cur.execute("DELETE FROM nco_2015_codes")
            cur.execute(
                """
                SELECT id FROM classification_standards
                 ORDER BY created_at DESC, id DESC
                 LIMIT 1
                """
            )
            nxt = cur.fetchone()
            if nxt:
                next_id = nxt["id"]
                cur.execute(
                    "UPDATE classification_standards SET is_selected = TRUE WHERE id = %s",
                    (next_id,),
                )
    if next_id is not None:
        _reload_active_into_nco_table(conn, next_id)
    elif was_selected:
        _clear_matching_cache()
    conn.commit()
    return {"deleted": standard_id, "name": row["name"]}


def ensure_selected_loaded(conn) -> int:
    """If a standard is selected but nco_2015_codes is empty, reload it."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM nco_2015_codes")
        if cur.fetchone()[0] > 0:
            return 0
        cur.execute(
            "SELECT id FROM classification_standards WHERE is_selected = TRUE LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return 0
    count = _reload_active_into_nco_table(conn, row[0])
    conn.commit()
    return count
