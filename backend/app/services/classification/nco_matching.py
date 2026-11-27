"""NCO 2015 matching.

Each occupation label is normalized, checked against steward aliases, then
scored locally against official occupation rows (exact, alias, fuzzy, BM25,
TF-IDF or an optional local embedding model). The chat model confirms only
a small number of ambiguous rows and may choose only retrieved codes.
"""

from __future__ import annotations

import json
import re
from typing import Optional

_CODES_CACHE = None
_NODES_CACHE = None
_EMBED_CACHE = None  # list of vectors aligned with _NODES_CACHE


def clear_codes_cache():
    """Drop in-memory indexes after Settings reloads nco_2015_codes."""
    global _CODES_CACHE, _NODES_CACHE, _EMBED_CACHE
    _CODES_CACHE = None
    _NODES_CACHE = None
    _EMBED_CACHE = None
    from app.services.classification.nco_pipeline import clear_index_cache
    clear_index_cache()

_STOP = frozenset({
    "a", "an", "and", "the", "of", "or", "etc", "other", "not", "elsewhere",
    "classified", "nec", "worker", "workers", "related", "support",
})
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
# Hierarchy codes are 1–4 digits; specific occupations may be dotted (2.1.0100).
_NCO_CODE_RE = re.compile(r"^\d{1,4}(?:\.\d+)*$")
# Row totals / stub aggregates that appear in occupation columns — never map to NCO.
_AGGREGATE_LABELS = frozenset({
    "all",
    "total",
    "grand total",
    "sub total",
    "subtotal",
    "overall",
    "sum",
    "all occupations",
    "all categories",
    "all workers",
    "total workers",
    "total occupations",
})
# Residual / non-response catch-alls (Others, Not stated, N.A., …) — never map to NCO.
# These otherwise fuzzy-match onto "… Not Elsewhere Classified" families.
_RESIDUAL_LABELS = frozenset({
    "other",
    "others",
    "other not stated",
    "others not stated",
    "not stated",
    "not reported",
    "not available",
    "not known",
    "not specified",
    "not classified",
    "not ascertained",
    "not mentioned",
    "not applicable",
    "unclassified",
    "unknown",
    "n a",
    "na",
    "n r",
    "nr",
    "n s",
    "ns",
    "misc",
    "miscellaneous",
    "residual",
    "remaining",
    "rest",
    "others specify",
    "other specify",
    "not elsewhere classified",
    "nec",
})
# Vocabulary that only builds residual/non-response labels (no real occupation words).
_RESIDUAL_TOKENS = frozenset({
    "other", "others", "misc", "miscellaneous", "residual", "remaining", "rest",
    "unknown", "na", "nr", "ns", "nec", "n", "a", "r", "s",
    "not", "stated", "reported", "available", "known", "specified",
    "classified", "elsewhere", "specify", "mentioned", "applicable",
    "ascertained", "response", "unclassified",
})
_RESIDUAL_MARKERS = frozenset({
    "other", "others", "misc", "miscellaneous", "residual", "remaining",
    "rest", "unknown", "na", "nr", "ns", "nec", "unclassified",
    "stated", "reported", "available", "known", "specified",
})

# Tunable gates (not vocabulary) — auto_fill only above these.
_EMBED_HIGH = 0.52
_EMBED_MED = 0.38
_FUZZY_HIGH = 0.55
_FUZZY_MED = 0.38

# Employment-status / non-worker phrases — exact normalized forms only.
# Extra content tokens (e.g. "student welfare officer") must NOT match.
_NON_OCCUPATION_EXACT = frozenset({
    "housewife",
    "housewives",
    "homemaker",
    "homemakers",
    "housewife non workers",
    "housewife non worker",
    "housewives non workers",
    "housewife nonworkers",
    "non workers",
    "non worker",
    "nonworkers",
    "nonworker",
    "student",
    "students",
    "dependent",
    "dependents",
    "dependant",
    "dependants",
    "retired",
    "pensioner",
    "pensioners",
    "unemployed",
    "not in labour force",
    "not in labor force",
    "not in the labour force",
    "not in the labor force",
})
_NON_OCCUPATION_STATUS_TOKENS = frozenset({
    "housewife", "housewives", "homemaker", "homemakers",
    "student", "students",
    "dependent", "dependents", "dependant", "dependants",
    "retired", "pensioner", "pensioners",
    "unemployed",
    "non", "worker", "workers", "nonworker", "nonworkers",
    "not", "in", "labour", "labor", "force", "the",
})
_CROSSWALK_CACHE = None
_DEFAULT_NCO_VERSION = "2015"


def normalize_occupation_value(text) -> str:
    """Generic normalize for alias keys and comparison — no vocabulary maps."""
    s = _PUNCT_RE.sub(" ", (text or "").lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_non_occupation_status(text) -> bool:
    """True for exact employment-status phrases (not occupation titles).

    Uses normalized exact phrases and status-only token sets. Labels with
    extra content words (e.g. ``Student Welfare Officer``) return False.
    """
    n = normalize_occupation_value(text)
    if not n:
        return False
    if n in _NON_OCCUPATION_EXACT:
        return True
    tokens = n.split()
    if not tokens:
        return False
    # Status-only compounds: every token is status vocabulary, and at least one
    # distinctive status marker is present (not just "worker"/"the").
    status_markers = {
        "housewife", "housewives", "homemaker", "homemakers",
        "student", "students",
        "dependent", "dependents", "dependant", "dependants",
        "retired", "pensioner", "pensioners",
        "unemployed",
        "nonworker", "nonworkers",
    }
    if all(t in _NON_OCCUPATION_STATUS_TOKENS for t in tokens):
        if any(t in status_markers for t in tokens):
            return True
        # "non workers" / "not in labour force"
        if "non" in tokens and ("worker" in tokens or "workers" in tokens):
            return True
        if "unemployed" in tokens:
            return True
        if ("labour" in tokens or "labor" in tokens) and "force" in tokens:
            return True
    return False


def not_an_occupation_result(occupation_text=None):
    """Stable payload for employment-status / non-worker labels."""
    return {
        "status": "not_an_occupation",
        "level": None,
        "nco_code": None,
        "occupation_code": None,
        "code": None,
        "title": None,
        "occupation_title": None,
        "family_code": None,
        "family_title": None,
        "group_code": None,
        "group_title": None,
        "subdivision_code": None,
        "subdivision_title": None,
        "division_code": None,
        "division_title": None,
        "score": 0.0,
        "confidence_score": 0.0,
        "confidence": "high",
        "auto_fill": False,
        "needs_manual_review": False,
        "source": "non_occupation",
        "matching_method": ["non_occupation"],
        "reason": "The supplied value describes an employment status, not an occupation.",
        "normalized_value": normalize_occupation_value(occupation_text) if occupation_text else None,
        "source_value": occupation_text,
        "alternatives": [],
        "candidates": [],
        "ambiguous": False,
        "needs_llm": False,
    }


def is_non_occupation_aggregate(text) -> bool:
    """True for All/Total aggregates and Others/Not-stated residuals — never NCO-map."""
    if is_non_occupation_status(text):
        return True
    n = normalize_occupation_value(text)
    if not n:
        return False
    if n in _AGGREGATE_LABELS or n in _RESIDUAL_LABELS:
        return True
    # "All - Urban", "Total (persons)", etc.
    if re.fullmatch(r"(?:all|total|overall|sum)(?:\s+\w+){0,3}", n):
        # Keep real phrases like "total inspectors" out — only short stubs.
        tokens = n.split()
        if tokens and tokens[0] in {"all", "total", "overall", "sum"} and len(tokens) <= 2:
            if len(tokens) == 1:
                return True
            # Allow "all occupations" / "total workers" via set; reject "all india" etc.
            return n in _AGGREGATE_LABELS or tokens[1] in {
                "occupations", "categories", "workers", "persons", "people",
            }
    # Labels built only from residual vocabulary, e.g. "Others / Not stated", "N.A."
    tokens = n.split()
    if tokens and all(t in _RESIDUAL_TOKENS for t in tokens):
        if any(t in _RESIDUAL_MARKERS for t in tokens):
            return True
        if tokens[0] == "not" and 1 < len(tokens) <= 4:
            return True
        if len(tokens) == 2 and tokens[0] == "n" and tokens[1] in {"a", "r", "s"}:
            return True
    return False


def looks_like_nco_code(code) -> bool:
    """True for real NCO codes (``2``, ``24``, ``2411``, ``2.1.0100``), not labels."""
    s = str(code or "").strip()
    return bool(s and _NCO_CODE_RE.match(s))


def is_usable_nco_alias(alias_row, occupation_text=None) -> bool:
    """Reject aliases that stored the occupation label as the code."""
    if not isinstance(alias_row, dict):
        return False
    code = str(alias_row.get("code") or "").strip()
    if not looks_like_nco_code(code):
        return False
    if occupation_text is not None:
        if normalize_occupation_value(code) == normalize_occupation_value(occupation_text):
            return False
    return True


def _load_all_codes(conn):
    """Load active classification rows from Postgres (bundled NCO or Settings upload)."""
    global _CODES_CACHE, _NODES_CACHE, _EMBED_CACHE
    if _CODES_CACHE is not None:
        return _CODES_CACHE
    try:
        if conn is None:
            raise RuntimeError("no db")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT nco_code, occupation_title, division_code, division_title,
                       subdivision_code, subdivision_title, group_code, group_title,
                       family_code, family_title
                FROM nco_2015_codes
            """)
            cols = [d[0] for d in cur.description]
            _CODES_CACHE = [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        _CODES_CACHE = []
    _NODES_CACHE = None
    _EMBED_CACHE = None
    return _CODES_CACHE


def _confidence_from_score(score, used_embeddings):
    if score is None:
        return "low"
    high = _EMBED_HIGH if used_embeddings else _FUZZY_HIGH
    med = _EMBED_MED if used_embeddings else _FUZZY_MED
    if score >= high:
        return "high"
    if score >= med:
        return "medium"
    return "low"


def _finalize(result, score=None, used_embeddings=False, source="retrieval"):
    if not result:
        return None
    conf = result.get("confidence")
    if conf not in ("high", "medium", "low"):
        conf = _confidence_from_score(score if score is not None else result.get("score"), used_embeddings)
    result["confidence"] = conf
    result["auto_fill"] = conf == "high"
    result["needs_manual_review"] = conf != "high"
    result["source"] = source
    return result


def _alias_result(alias_row, conn=None):
    level = alias_row.get("level") or "division"
    if level == "group":
        level = "subdivision"
    code = str(alias_row.get("code") or "").strip()
    title = str(alias_row.get("title") or "").strip()
    if not title and conn is not None:
        title = _title_for_code(conn, code, level) or ""
    result = {
        "level": level,
        "nco_code": None,
        "code": code,
        "title": title,
        "family_code": None,
        "family_title": None,
        "group_code": None,
        "group_title": None,
        "subdivision_code": code if level == "subdivision" else None,
        "subdivision_title": title if level == "subdivision" else None,
        "division_code": code if level == "division" else None,
        "division_title": title if level == "division" else None,
        "occupation_title": title if level == "occupation" else None,
        "score": 1.0,
        "alternatives": [],
        "status": "alias_match",
        "confidence": "high",
        "confidence_score": 1.0,
        "matching_method": ["alias"],
        "normalized_value": None,
        "source_value": None,
        "reason": "A previously verified occupation mapping was reused.",
    }
    if level == "family":
        result["family_code"] = result["code"]
        result["family_title"] = result["title"]
    if level == "occupation":
        result["nco_code"] = code
        result["occupation_title"] = title
    _attach_hierarchy(result, conn, code)
    return _finalize(result, score=1.0, used_embeddings=False, source="alias")


def _attach_hierarchy(result, conn, code):
    """Fill division, subdivision, and family from the registry when a code is known."""
    if conn is None or not code:
        return
    rows = _load_all_codes(conn)
    level = result.get("level")
    field = {
        "occupation": "nco_code",
        "family": "family_code",
        "subdivision": "subdivision_code",
        "division": "division_code",
    }.get(level, "nco_code")
    row = next((item for item in rows if str(item.get(field) or "").strip() == str(code).strip()), None)
    if row is None:
        return
    keys = ["division_code", "division_title"]
    if level in ("subdivision", "family", "occupation"):
        keys += ["subdivision_code", "subdivision_title", "group_code", "group_title"]
    if level in ("family", "occupation"):
        keys += ["family_code", "family_title"]
    for key in keys:
        if not result.get(key) and row.get(key):
            result[key] = row.get(key)


def _title_for_code(conn, code: str, level: str) -> Optional[str]:
    """Resolve a hierarchy title from the active standard when an alias omitted it."""
    code = str(code or "").strip()
    if not code:
        return None
    rows = _load_all_codes(conn)
    level = (level or "division").lower()
    if level == "group":
        level = "subdivision"
    field = {
        "division": ("division_code", "division_title"),
        "subdivision": ("subdivision_code", "subdivision_title"),
        "family": ("family_code", "family_title"),
        "occupation": ("nco_code", "occupation_title"),
    }.get(level)
    if not field:
        return None
    code_key, title_key = field
    for row in rows:
        if str(row.get(code_key) or "").strip() == code:
            title = str(row.get(title_key) or "").strip()
            if title:
                return title
    return None


def _lookup_alias(conn, occupation_text):
    if conn is None:
        return None
    try:
        from app.services.classification.nco_aliases import lookup_nco_alias
        return lookup_nco_alias(conn, normalize_occupation_value(occupation_text))
    except Exception:
        return None


def _fallback_best_match(occupation_text, rows, extractor=None):
    """Top local occupation hit. No per-label embedding or chat call."""
    from app.services.classification.nco_pipeline import get_index, rank_occupation

    if not rows:
        return None
    result = rank_occupation(occupation_text, get_index(rows))
    if result is not None:
        result.pop("needs_llm", None)
    return result


def _registry_row_for(conn, level, code):
    """Return one registry row that owns this hierarchy node, or None."""
    code = str(code or "").strip()
    level = (level or "occupation").lower()
    if level == "group":
        level = "subdivision"
    if not code:
        return None
    field = {
        "division": "division_code",
        "subdivision": "subdivision_code",
        "family": "family_code",
        "occupation": "nco_code",
    }.get(level)
    if not field:
        return None
    for row in _load_all_codes(conn) or []:
        if str(row.get(field) or "").strip() == code:
            return row
    return None


def validate_and_rebuild_hierarchy(result, conn=None):
    """Validate coded results against the registry and rebuild parent fields.

    Prefix checks are diagnostics only. Authoritative parent links come from
    ``nco_2015_codes``. On failure: demote to needs_review, clear auto_fill.
    """
    if not result or not isinstance(result, dict):
        return result
    if result.get("status") == "not_an_occupation":
        return result
    code = str(result.get("code") or result.get("nco_code") or "").strip()
    if not code:
        return result
    level = (result.get("level") or "occupation").lower()
    if level == "group":
        level = "subdivision"
        result = dict(result)
        result["level"] = level

    row = _registry_row_for(conn, level, code) if conn is not None else None
    if row is None and conn is not None:
        out = dict(result)
        out["status"] = "needs_review"
        out["auto_fill"] = False
        out["needs_manual_review"] = True
        out["confidence"] = "low"
        out["reason"] = (
            (out.get("reason") or "")
            + " Hierarchy validation failed: code not found in the active NCO registry."
        ).strip()
        return out

    if row is not None:
        out = dict(result)
        out["division_code"] = row.get("division_code")
        out["division_title"] = row.get("division_title")
        if level in ("subdivision", "family", "occupation"):
            out["subdivision_code"] = row.get("subdivision_code")
            out["subdivision_title"] = row.get("subdivision_title")
            out["group_code"] = row.get("group_code")
            out["group_title"] = row.get("group_title")
        if level in ("family", "occupation"):
            out["family_code"] = row.get("family_code")
            out["family_title"] = row.get("family_title")
        if level == "occupation":
            out["nco_code"] = row.get("nco_code")
            out["occupation_code"] = row.get("nco_code")
            out["occupation_title"] = row.get("occupation_title")
            out["title"] = row.get("occupation_title") or out.get("title")
        elif level == "family":
            out["title"] = row.get("family_title") or out.get("title")
        elif level == "subdivision":
            out["title"] = row.get("subdivision_title") or out.get("title")
        elif level == "division":
            out["title"] = row.get("division_title") or out.get("title")

        # Cheap prefix diagnostics after registry rebuild.
        div = str(out.get("division_code") or "")
        sub = str(out.get("subdivision_code") or "")
        fam = str(out.get("family_code") or "")
        grp = str(out.get("group_code") or "")
        ok = True
        if sub and div and not sub.startswith(div):
            ok = False
        if grp and sub and not grp.startswith(sub):
            ok = False
        if fam and grp and not fam.startswith(grp):
            ok = False
        if fam and sub and not fam.startswith(sub):
            ok = False
        if not ok:
            out["status"] = "needs_review"
            out["auto_fill"] = False
            out["needs_manual_review"] = True
            out["confidence"] = "medium"
            out["reason"] = (
                (out.get("reason") or "")
                + " Hierarchy validation failed: parent codes are inconsistent."
            ).strip()
        return out
    return result


def _llm_confirm(extractor, occupation_text, result, conn=None):
    """Ask the chat model to pick among retrieved codes only. Never invents a code.

    Rebuilds hierarchy from the registry. Never sets auto_fill from an LLM pick.
    """
    if extractor is None or getattr(extractor, "skip_llm", False) or not result:
        return result
    candidates = [{
        "code": result.get("code"),
        "title": result.get("title"),
        "level": result.get("level"),
        "family_code": result.get("family_code"),
        "group_code": result.get("group_code"),
        "subdivision_code": result.get("subdivision_code"),
        "division_code": result.get("division_code"),
    }]
    for alt in result.get("alternatives") or []:
        if alt.get("code"):
            candidates.append(alt)
    # Prefer explicit candidate list when present (span / ambiguous).
    for alt in result.get("candidates") or []:
        if alt.get("code"):
            candidates.append(alt)
    lines = "\n".join(
        f"{item.get('level') or 'occupation'}\t{item.get('code')}\t{item.get('title')}"
        for item in candidates
        if item.get("code")
    )
    if not lines:
        return result
    prompt = (
        "You are an occupational classification expert.\n\n"
        f"Extracted occupation: \"{occupation_text}\"\n"
        f"Normalized: \"{result.get('normalized_value') or ''}\"\n\n"
        "Choose the single best NCO classification from this retrieved list only.\n"
        "A candidate may be a division, subdivision, group, family, or occupation.\n"
        "Prefer the most specific level that the input itself supports.\n"
        "Do not invent codes. If none fits, set code to null.\n\n"
        f"Candidates (level, code, title):\n{lines}\n\n"
        "Return ONLY JSON:\n"
        "{\"code\": \"code from the list or null\", \"confidence\": \"high\" or \"medium\" or \"low\", "
        "\"reason\": \"short reason\"}"
    )
    try:
        text = extractor._complete(prompt, max_tokens=160)
        text = re.sub(r"```[a-z]*\n?", "", text).strip().rstrip("`").strip()
        decision = json.loads(text)
    except Exception:
        return result
    code = str(decision.get("code") or "").strip()
    allowed = {str(item.get("code")): item for item in candidates if item.get("code")}
    if code not in allowed:
        return result
    picked = allowed[code]
    level = picked.get("level") or result.get("level") or "occupation"
    if level == "group":
        level = "subdivision"
    rebuilt = {
        "level": level,
        "code": code,
        "title": picked.get("title") or result.get("title"),
        "nco_code": code if level == "occupation" else None,
        "occupation_code": code if level == "occupation" else None,
        "occupation_title": picked.get("title") if level == "occupation" else None,
        "family_code": picked.get("family_code"),
        "group_code": picked.get("group_code"),
        "subdivision_code": picked.get("subdivision_code"),
        "division_code": picked.get("division_code"),
        "score": result.get("score"),
        "confidence_score": result.get("confidence_score"),
        "confidence": "medium",
        "auto_fill": False,
        "needs_manual_review": True,
        "source": "llm",
        "status": "needs_review",
        "matching_method": list(dict.fromkeys([*(result.get("matching_method") or []), "llm"])),
        "reason": str(decision.get("reason") or "Chat model selected among retrieved codes (review required)."),
        "normalized_value": result.get("normalized_value"),
        "source_value": result.get("source_value") or occupation_text,
        "alternatives": result.get("alternatives") or [],
        "candidates": result.get("candidates") or [],
        "ambiguous": bool(result.get("ambiguous")),
        "needs_llm": False,
    }
    return validate_and_rebuild_hierarchy(rebuilt, conn=conn)


def _crosswalk_csv_path():
    import os
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "data",
        "nco_legacy_crosswalk.csv",
    )


def load_legacy_crosswalk(csv_path=None):
    """Load versioned legacy→NCO crosswalk rows keyed by normalized source_label."""
    global _CROSSWALK_CACHE
    if csv_path is None and _CROSSWALK_CACHE is not None:
        return _CROSSWALK_CACHE
    import csv
    import os

    path = csv_path or _crosswalk_csv_path()
    by_label = {}
    if not os.path.isfile(path):
        if csv_path is None:
            _CROSSWALK_CACHE = by_label
        return by_label
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            label = normalize_occupation_value(row.get("source_label") or "")
            if not label:
                continue
            by_label.setdefault(label, []).append({
                "source_classification": (row.get("source_classification") or "").strip(),
                "source_version": (row.get("source_version") or "").strip(),
                "source_code": (row.get("source_code") or "").strip(),
                "source_label": (row.get("source_label") or "").strip(),
                "target_code": (row.get("target_code") or "").strip(),
                "target_level": (row.get("target_level") or "").strip().lower(),
                "mapping_type": (row.get("mapping_type") or "").strip().lower(),
                "reason": (row.get("reason") or "").strip(),
                "review_date": (row.get("review_date") or "").strip(),
            })
    if csv_path is None:
        _CROSSWALK_CACHE = by_label
    return by_label


def clear_crosswalk_cache():
    global _CROSSWALK_CACHE
    _CROSSWALK_CACHE = None


def _title_for_target(conn, level, code):
    return _title_for_code(conn, code, level) if conn is not None else None


def _crosswalk_result(label, rows, conn=None):
    """Build a match result from legacy crosswalk rows for one normalized label."""
    if not rows:
        return None
    mapping_type = (rows[0].get("mapping_type") or "").lower()
    raw_norm = normalize_occupation_value(label)
    if mapping_type == "not_an_occupation" or (rows[0].get("target_level") or "") == "not_an_occupation":
        hit = not_an_occupation_result(label)
        if rows[0].get("reason"):
            hit["reason"] = rows[0]["reason"]
        hit["source"] = "seed"
        return hit

    candidates = []
    seen = set()
    for row in rows:
        level = (row.get("target_level") or "division").lower()
        if level == "group":
            level = "subdivision"
        code = str(row.get("target_code") or "").strip()
        if not code and mapping_type != "not_an_occupation":
            continue
        key = (level, code)
        if key in seen:
            continue
        seen.add(key)
        title = _title_for_target(conn, level, code) or ""
        enriched = validate_and_rebuild_hierarchy({
            "level": level,
            "code": code,
            "title": title,
            "nco_code": code if level == "occupation" else None,
            "occupation_code": code if level == "occupation" else None,
            "occupation_title": title if level == "occupation" else None,
            "family_code": code if level == "family" else None,
            "family_title": title if level == "family" else None,
            "group_code": None,
            "group_title": None,
            "subdivision_code": code if level == "subdivision" else None,
            "subdivision_title": title if level == "subdivision" else None,
            "division_code": code if level == "division" else None,
            "division_title": title if level == "division" else None,
        }, conn=conn) or {}
        candidates.append({
            "level": level,
            "code": code,
            "title": enriched.get("title") or title,
            "reason": row.get("reason") or "",
            "source_classification": row.get("source_classification"),
            "source_version": row.get("source_version"),
            "division_code": enriched.get("division_code"),
            "division_title": enriched.get("division_title"),
            "subdivision_code": enriched.get("subdivision_code"),
            "subdivision_title": enriched.get("subdivision_title"),
            "group_code": enriched.get("group_code"),
            "group_title": enriched.get("group_title"),
            "family_code": enriched.get("family_code"),
            "family_title": enriched.get("family_title"),
        })
    if not candidates:
        return None

    # Duplicate source_label casings in the CSV collapse to one candidate after dedupe.
    if mapping_type == "span" or len(candidates) > 1:
        primary = candidates[0]
        result = {
            "level": primary["level"],
            "code": None,
            "title": None,
            "nco_code": None,
            "occupation_code": None,
            "occupation_title": None,
            "family_code": None,
            "family_title": None,
            "group_code": None,
            "group_title": None,
            "subdivision_code": None,
            "subdivision_title": None,
            "division_code": None,
            "division_title": None,
            "score": 0.0,
            "confidence_score": 0.0,
            "confidence": "medium",
            "auto_fill": False,
            "needs_manual_review": True,
            "source": "seed",
            "status": "needs_review",
            "matching_method": ["seed_crosswalk"],
            "reason": primary.get("reason")
                or "Legacy label spans multiple NCO codes — pick the most relevant.",
            "normalized_value": raw_norm,
            "source_value": label,
            "alternatives": candidates[1:],
            "candidates": candidates,
            "ambiguous": True,
            "needs_llm": False,
        }
        return result

    primary = candidates[0]
    level = primary["level"]
    code = primary["code"]
    title = primary["title"]
    result = {
        "level": level,
        "code": code,
        "title": title,
        "nco_code": code if level == "occupation" else None,
        "occupation_code": code if level == "occupation" else None,
        "occupation_title": title if level == "occupation" else None,
        "family_code": primary.get("family_code") or (code if level == "family" else None),
        "family_title": primary.get("family_title") or (title if level == "family" else None),
        "group_code": primary.get("group_code"),
        "group_title": primary.get("group_title"),
        "subdivision_code": primary.get("subdivision_code") or (code if level == "subdivision" else None),
        "subdivision_title": primary.get("subdivision_title") or (title if level == "subdivision" else None),
        "division_code": primary.get("division_code") or (code if level == "division" else None),
        "division_title": primary.get("division_title") or (title if level == "division" else None),
        "score": 1.0,
        "confidence_score": 1.0,
        "confidence": "high",
        "auto_fill": True,
        "needs_manual_review": False,
        "source": "seed",
        "status": "seed_match",
        "matching_method": ["seed_crosswalk"],
        "reason": primary.get("reason") or "Matched via curated legacy crosswalk seed.",
        "normalized_value": raw_norm,
        "source_value": label,
        "alternatives": [],
        "candidates": candidates,
        "ambiguous": False,
        "needs_llm": False,
    }
    return validate_and_rebuild_hierarchy(result, conn=conn)


def match_occupation(conn, occupation_text, extractor=None, shortlist_size=16, context=None):
    """Match one occupation label to an NCO 2015 occupation code."""
    matches = match_occupations(
        conn,
        [occupation_text] if occupation_text is not None else [],
        extractor=extractor,
        shortlist_size=shortlist_size,
        context=context,
    )
    return matches.get(occupation_text)


def match_occupations(conn, occupation_texts, extractor=None, shortlist_size=16, context=None):
    """Score every label locally, then confirm at most a few ambiguous rows with the LLM."""
    from app.services.classification.nco_pipeline import (
        expand_abbreviations,
        get_index,
        load_enrichment_aliases,
        normalize_text,
        rank_occupation,
    )

    del shortlist_size  # hybrid retrieval uses a fixed shortlist
    results = {}
    pending = []
    rows = None
    index = None
    crosswalk = load_legacy_crosswalk()
    for text in occupation_texts:
        if not text or not str(text).strip():
            results[text] = None
            continue
        label = str(text).strip()
        raw_norm = normalize_occupation_value(label)
        # Non-occupation / status phrases before aliases and crosswalk.
        if is_non_occupation_status(label):
            results[text] = not_an_occupation_result(label)
            continue
        if is_non_occupation_aggregate(label):
            results[text] = None
            continue
        alias = _lookup_alias(conn, label)
        if alias and not is_usable_nco_alias(alias, label):
            alias = None
        expanded = expand_abbreviations(normalize_text(label))
        if alias is None and expanded and expanded != raw_norm and conn is not None:
            try:
                from app.services.classification.nco_aliases import lookup_nco_alias
                alias = lookup_nco_alias(conn, expanded)
            except Exception:
                alias = None
            if alias and not is_usable_nco_alias(alias, label):
                alias = None
        if alias and is_usable_nco_alias(alias, label):
            hit = _alias_result(alias, conn=conn)
            hit["source_value"] = label
            hit["normalized_value"] = raw_norm
            results[text] = validate_and_rebuild_hierarchy(hit, conn=conn)
            continue
        seed_rows = crosswalk.get(raw_norm) or []
        if not seed_rows and expanded and expanded != raw_norm:
            seed_rows = crosswalk.get(normalize_occupation_value(expanded)) or []
        if seed_rows:
            hit = _crosswalk_result(label, seed_rows, conn=conn)
            if hit is not None:
                results[text] = hit
                continue
        if rows is None:
            rows = _load_all_codes(conn)
            aliases = load_enrichment_aliases(conn) if rows else []
            index = get_index(rows, extra_aliases=aliases) if rows else None
        if not index:
            results[text] = None
            continue
        ranked = rank_occupation(label, index, context=context)
        if ranked:
            ranked = validate_and_rebuild_hierarchy(ranked, conn=conn)
        if ranked and ranked.pop("needs_llm", False):
            pending.append((text, ranked))
        else:
            results[text] = ranked

    llm_budget = 12
    for text, ranked in pending:
        if (
            llm_budget > 0
            and extractor is not None
            and not getattr(extractor, "skip_llm", False)
        ):
            llm_budget -= 1
            results[text] = _llm_confirm(extractor, str(text), ranked, conn=conn)
        else:
            results[text] = ranked
    return results


