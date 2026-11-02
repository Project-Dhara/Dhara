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


def normalize_occupation_value(text) -> str:
    """Generic normalize for alias keys and comparison — no vocabulary maps."""
    s = _PUNCT_RE.sub(" ", (text or "").lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_non_occupation_aggregate(text) -> bool:
    """True for All/Total aggregates and Others/Not-stated residuals — never NCO-map."""
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


def _llm_confirm(extractor, occupation_text, result):
    """Ask the chat model to pick among retrieved codes only. Never invents a code."""
    if extractor is None or getattr(extractor, "skip_llm", False) or not result:
        return result
    candidates = [{"code": result.get("code"), "title": result.get("title")}]
    for alt in result.get("alternatives") or []:
        if alt.get("code"):
            candidates.append(alt)
    lines = "\n".join(
        f"{item.get('code')}\t{item.get('title')}"
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
        "Do not invent codes. If none fits, set code to null.\n\n"
        f"Candidates (code, title):\n{lines}\n\n"
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
    if decision.get("confidence") != "high":
        return result
    picked = allowed[code]
    result = dict(result)
    level = picked.get("level") or result.get("level") or "occupation"
    result["level"] = level
    result["code"] = code
    result["title"] = picked.get("title") or result.get("title")
    if level == "occupation":
        result["nco_code"] = code
        result["occupation_code"] = code
        result["occupation_title"] = result["title"]
    else:
        result["nco_code"] = None
        result["occupation_code"] = None
        result["occupation_title"] = None
    for key in ("family_code", "group_code", "subdivision_code", "division_code"):
        if picked.get(key):
            result[key] = picked[key]
    result["status"] = "auto_matched"
    result["confidence"] = "high"
    result["auto_fill"] = True
    result["needs_manual_review"] = False
    result["source"] = "llm"
    methods = list(result.get("matching_method") or [])
    if "llm" not in methods:
        methods.append("llm")
    result["matching_method"] = methods
    if decision.get("reason"):
        result["reason"] = str(decision["reason"])
    return result


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
    for text in occupation_texts:
        if not text or not str(text).strip():
            results[text] = None
            continue
        label = str(text).strip()
        if is_non_occupation_aggregate(label):
            results[text] = None
            continue
        alias = _lookup_alias(conn, label)
        if alias and not is_usable_nco_alias(alias, label):
            alias = None
        expanded = expand_abbreviations(normalize_text(label))
        raw_norm = normalize_occupation_value(label)
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
            results[text] = _llm_confirm(extractor, str(text), ranked)
        else:
            results[text] = ranked
    return results


