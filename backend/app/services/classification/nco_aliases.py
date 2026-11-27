"""NCO-2015 occupation code seeding + steward-learned value aliases."""
import os

import psycopg2.extras

# backend/data/… (this file lives under app/services/classification/)
NCO_2015_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data",
    "nco_2015_concordance.csv",
)

DEFAULT_NCO_VERSION = "2015"

# Labels that span multiple NCO nodes — never auto-learn into single-code aliases.
_AMBIGUOUS_LEGACY_NORMS = frozenset({
    "professional technical related workers",
    "service workers",
    "production and other related workers",
})


def seed_nco_2015(conn, csv_path=NCO_2015_CSV_PATH):
    """Optional local bootstrap: register bundled NCO 2015 as a standard.

    Prefer Settings → Classification code configuration for steward uploads.
    When backend NCO data exists, this creates the ``NCO 2015`` list entry
    (and loads ``nco_2015_codes`` if nothing is selected).
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
        try:
            cur.execute(
                """
                SELECT normalized_value, level, code, title, source, nco_version, updated_at
                  FROM nco_value_aliases
                 WHERE normalized_value = %s
                """,
                (normalized_value,),
            )
        except Exception:
            conn.rollback()
            cur.execute(
                """
                SELECT normalized_value, level, code, title, source, updated_at
                  FROM nco_value_aliases
                 WHERE normalized_value = %s
                """,
                (normalized_value,),
            )
        row = cur.fetchone()
    if not row:
        return None
    out = dict(row)
    out.setdefault("nco_version", DEFAULT_NCO_VERSION)
    return out


def list_nco_aliases(conn):
    """Return all alias rows newest-first."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        try:
            cur.execute(
                """
                SELECT normalized_value, level, code, title, source, nco_version, updated_at
                  FROM nco_value_aliases
                 ORDER BY updated_at DESC NULLS LAST, normalized_value
                """
            )
        except Exception:
            conn.rollback()
            cur.execute(
                """
                SELECT normalized_value, level, code, title, source, updated_at
                  FROM nco_value_aliases
                 ORDER BY updated_at DESC NULLS LAST, normalized_value
                """
            )
        rows = [dict(r) for r in cur.fetchall()]
    for row in rows:
        row.setdefault("nco_version", DEFAULT_NCO_VERSION)
    return rows


def delete_nco_alias(conn, normalized_value: str) -> bool:
    from app.services.classification.nco_matching import normalize_occupation_value

    norm = normalize_occupation_value(normalized_value)
    if not norm:
        return False
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM nco_value_aliases WHERE normalized_value = %s",
            (norm,),
        )
        deleted = cur.rowcount > 0
        if deleted:
            cur.execute(
                "INSERT INTO nco_steward_alias_counter (id, counter, updated_at) "
                "VALUES (1, 1, now()) "
                "ON CONFLICT (id) DO UPDATE SET "
                "counter = nco_steward_alias_counter.counter + 1, updated_at = now()"
            )
    conn.commit()
    return deleted


def clear_learned_nco_aliases(conn, *, keep_seed: bool = True) -> int:
    """Delete steward/auto learned aliases. Seed rows kept when keep_seed=True."""
    with conn.cursor() as cur:
        if keep_seed:
            cur.execute(
                "DELETE FROM nco_value_aliases WHERE COALESCE(source, '') <> 'seed'"
            )
        else:
            cur.execute("DELETE FROM nco_value_aliases")
        deleted = cur.rowcount
        if deleted:
            cur.execute(
                "INSERT INTO nco_steward_alias_counter (id, counter, updated_at) "
                "VALUES (1, 1, now()) "
                "ON CONFLICT (id) DO UPDATE SET "
                "counter = nco_steward_alias_counter.counter + 1, updated_at = now()"
            )
    conn.commit()
    return int(deleted or 0)


def is_ambiguous_learn_label(normalized_value: str) -> bool:
    return normalize_occupation_value_safe(normalized_value) in _AMBIGUOUS_LEGACY_NORMS


def normalize_occupation_value_safe(raw: str) -> str:
    from app.services.classification.nco_matching import normalize_occupation_value
    return normalize_occupation_value(raw)


def upsert_nco_aliases(conn, aliases: list, source: str = "steward", nco_version: str = DEFAULT_NCO_VERSION) -> dict:
    """Persist steward-verified occupation → NCO mappings.

    Never silently overwrites a different code. Returns::
        {"saved": int, "skipped": int, "conflicts": [...], "rejected_ambiguous": [...]}
    """
    from app.services.classification.nco_matching import (
        is_non_occupation_aggregate,
        is_usable_nco_alias,
        looks_like_nco_code,
        normalize_occupation_value,
    )

    saved = 0
    skipped = 0
    conflicts = []
    rejected_ambiguous = []
    if not aliases:
        return {
            "saved": 0,
            "skipped": 0,
            "conflicts": [],
            "rejected_ambiguous": [],
        }

    version = (nco_version or DEFAULT_NCO_VERSION).strip() or DEFAULT_NCO_VERSION
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for a in aliases:
            if not isinstance(a, dict):
                continue
            raw = a.get("normalized_value") or a.get("value") or ""
            norm = normalize_occupation_value(raw)
            level = str(a.get("level") or "").strip().lower()
            code = str(a.get("code") or "").strip()
            title = a.get("title")
            if not norm or not code or level not in (
                "division", "subdivision", "group", "family", "occupation",
            ):
                continue
            if is_non_occupation_aggregate(raw):
                continue
            if not looks_like_nco_code(code):
                continue
            if not is_usable_nco_alias({"code": code}, raw):
                continue
            if level == "group":
                level = "subdivision"
            # Do not auto-learn generic/span-class labels in 0.1.0.
            if norm in _AMBIGUOUS_LEGACY_NORMS or a.get("ambiguous"):
                rejected_ambiguous.append({
                    "normalized_value": norm,
                    "attempted_code": code,
                    "reason": "Generic or ambiguous label is not auto-learned into a single-code alias.",
                })
                continue

            try:
                cur.execute(
                    """
                    SELECT normalized_value, level, code, title, source, nco_version
                      FROM nco_value_aliases
                     WHERE normalized_value = %s
                    """,
                    (norm,),
                )
            except Exception:
                conn.rollback()
                cur.execute(
                    """
                    SELECT normalized_value, level, code, title, source
                      FROM nco_value_aliases
                     WHERE normalized_value = %s
                    """,
                    (norm,),
                )
            existing = cur.fetchone()
            if existing and str(existing.get("code") or "").strip() != code:
                conflicts.append({
                    "normalized_value": norm,
                    "existing_code": existing.get("code"),
                    "existing_level": existing.get("level"),
                    "existing_title": existing.get("title"),
                    "attempted_code": code,
                    "attempted_level": level,
                    "attempted_title": title,
                    "reason": "An existing verified mapping uses a different code; not overwritten.",
                })
                continue
            if existing and str(existing.get("code") or "").strip() == code:
                # Idempotent metadata refresh only.
                try:
                    cur.execute(
                        """
                        UPDATE nco_value_aliases
                           SET title = COALESCE(%s, title),
                               source = %s,
                               nco_version = %s,
                               updated_at = NOW()
                         WHERE normalized_value = %s
                        """,
                        (title, source, version, norm),
                    )
                except Exception:
                    conn.rollback()
                    cur.execute(
                        """
                        UPDATE nco_value_aliases
                           SET title = COALESCE(%s, title),
                               source = %s,
                               updated_at = NOW()
                         WHERE normalized_value = %s
                        """,
                        (title, source, norm),
                    )
                skipped += 1
                continue

            try:
                cur.execute(
                    """
                    INSERT INTO nco_value_aliases (
                        normalized_value, level, code, title, source, nco_version, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (norm, level, code, title, source, version),
                )
            except Exception:
                conn.rollback()
                cur.execute(
                    """
                    INSERT INTO nco_value_aliases (
                        normalized_value, level, code, title, source, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    """,
                    (norm, level, code, title, source),
                )
            saved += 1
    if saved > 0 and source == "steward":
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO nco_steward_alias_counter (id, counter, updated_at) "
                "VALUES (1, 1, now()) "
                "ON CONFLICT (id) DO UPDATE SET "
                "counter = nco_steward_alias_counter.counter + 1, updated_at = now()"
            )
    conn.commit()
    return {
        "saved": saved,
        "skipped": skipped,
        "conflicts": conflicts,
        "rejected_ambiguous": rejected_ambiguous,
    }
