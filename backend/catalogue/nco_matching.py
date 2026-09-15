"""NCO 2015 matching — dynamic retrieval + constrained LLM (no hardcoded labels).

Pipeline for each occupation value:
  1. Normalize (case / punctuation / whitespace only)
  2. Learned alias hit (steward verifies from Classify)
  3. Shortlist hierarchy nodes via embeddings (OpenAI) or fuzzy+token score
  4. LLM picks level/code from the shortlist only — trusted when valid
  5. Else top shortlist hit as fallback
  6. Confidence gate: auto_fill only when confidence is high

Indexes unique NCO hierarchy nodes (division / subdivision / group / family),
never the 3,445 specific .xxxx occupation codes.
"""

from __future__ import annotations

import json
import math
import re
from difflib import SequenceMatcher

_CODES_CACHE = None
_NODES_CACHE = None
_EMBED_CACHE = None  # list of vectors aligned with _NODES_CACHE

_STOP = frozenset({
    "a", "an", "and", "the", "of", "or", "etc", "other", "not", "elsewhere",
    "classified", "nec", "worker", "workers", "related", "support",
})
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_INPUT_SPLIT_RE = re.compile(r"[,/;]|\s+and\s+|\s+or\s+", re.I)

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


def _load_from_csv():
    import csv
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "nco_2015_concordance.csv")
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            code = (r.get("NCO_2015_Code") or "").strip()
            title = (r.get("Occupation_Title") or "").strip()
            if not code or not title:
                continue
            rows.append({
                "nco_code": code,
                "occupation_title": title,
                "division_code": (r.get("Division_Code") or "").strip(),
                "division_title": (r.get("Division_Title") or "").strip(),
                "subdivision_code": (r.get("SubDivision_Code") or "").strip(),
                "subdivision_title": (r.get("SubDivision_Title") or "").strip(),
                "group_code": (r.get("Group_Code") or "").strip(),
                "group_title": (r.get("Group_Title") or "").strip(),
                "family_code": (r.get("Family_Code") or "").strip(),
                "family_title": (r.get("Family_Title") or "").strip(),
            })
    return rows


def _load_all_codes(conn):
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
    if not _CODES_CACHE:
        _CODES_CACHE = _load_from_csv()
    _NODES_CACHE = None
    _EMBED_CACHE = None
    return _CODES_CACHE


def _normalize(text):
    return normalize_occupation_value(text)


def _stem(token):
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _content_tokens(text):
    out = []
    for t in _normalize(text).split():
        if not t or t in _STOP:
            continue
        out.append(t)
        st = _stem(t)
        if st != t and st not in _STOP:
            out.append(st)
    return out


def _input_phrases(occupation_text):
    parts = []
    for chunk in _INPUT_SPLIT_RE.split(occupation_text or ""):
        t = re.sub(r"\betc\.?\b", "", chunk, flags=re.I).strip()
        if t:
            parts.append(t)
    return parts or [(occupation_text or "").strip()]


def _hierarchy_nodes(rows):
    """One node per unique division / subdivision / group / family."""
    global _NODES_CACHE
    if _NODES_CACHE is not None:
        return _NODES_CACHE
    seen = set()
    nodes = []
    for r in rows:
        specs = (
            ("division", r["division_code"], r["division_title"],
             r["division_title"] or ""),
            ("subdivision", r["subdivision_code"], r["subdivision_title"],
             " ".join(filter(None, [r["division_title"], r["subdivision_title"]]))),
            ("group", r["group_code"], r["group_title"],
             " ".join(filter(None, [r["division_title"], r["subdivision_title"], r["group_title"]]))),
            ("family", r["family_code"], r["family_title"],
             " ".join(filter(None, [
                 r["division_title"], r["subdivision_title"],
                 r["group_title"], r["family_title"],
             ]))),
        )
        for level, code, title, search_text in specs:
            key = (level, code)
            if not code or key in seen:
                continue
            seen.add(key)
            nodes.append({
                "level": level,
                "code": str(code),
                "title": title or "",
                "search_text": search_text,
                "division_code": r["division_code"],
                "division_title": r["division_title"],
                "subdivision_code": r["subdivision_code"],
                "subdivision_title": r["subdivision_title"],
                "group_code": r["group_code"],
                "group_title": r["group_title"],
                "family_code": r["family_code"],
                "family_title": r["family_title"],
            })
    _NODES_CACHE = nodes
    return nodes


def _token_vector(text):
    vec = {}
    for t in _content_tokens(text):
        vec[t] = vec.get(t, 0) + 1
    return vec


def _cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in a)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _fuzzy_ratio(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _dynamic_score(query, node):
    """Score without a hardcoded synonym vocabulary: fuzzy + token cosine + coverage."""
    node_title = _normalize(node.get("title") or "")
    node_search = _normalize(node.get("search_text") or "")
    best = 0.0
    phrases = _input_phrases(query)
    q_full = _normalize(query)

    def _combo(phrase_norm, phrase_raw):
        if not phrase_norm:
            return 0.0
        fuzzy = max(
            _fuzzy_ratio(phrase_norm, node_title),
            0.85 * _fuzzy_ratio(phrase_norm, node_search),
        )
        tok = _cosine(_token_vector(phrase_raw), _token_vector(node.get("title") or ""))
        tok_s = _cosine(_token_vector(phrase_raw), _token_vector(node.get("search_text") or ""))
        # Coverage: how many distinctive query tokens appear in the title.
        qtok = set(_content_tokens(phrase_raw))
        ttok = set(_content_tokens(node.get("title") or ""))
        cov = (len(qtok & ttok) / len(qtok)) if qtok else 0.0
        return 0.35 * fuzzy + 0.35 * max(tok, tok_s) + 0.30 * cov

    for phrase in phrases + [query]:
        best = max(best, _combo(_normalize(phrase), phrase))
    best = max(best, _combo(q_full, query))
    return best


def _embed_texts(extractor, texts):
    if extractor is None or getattr(extractor, "skip_llm", False):
        return None
    if getattr(extractor, "provider", None) != "openai":
        return None
    client = getattr(extractor, "client", None)
    if client is None:
        return None
    try:
        out = []
        for i in range(0, len(texts), 64):
            chunk = texts[i:i + 64]
            resp = client.embeddings.create(model="text-embedding-3-small", input=chunk)
            by_idx = {d.index: d.embedding for d in resp.data}
            out.extend(by_idx[j] for j in range(len(chunk)))
        return out
    except Exception:
        return None


def _vec_cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _ensure_node_embeddings(extractor, nodes):
    global _EMBED_CACHE
    if _EMBED_CACHE is not None:
        return _EMBED_CACHE
    vectors = _embed_texts(extractor, [n["search_text"] for n in nodes])
    _EMBED_CACHE = vectors
    return vectors


def _shortlist_nodes(query, nodes, extractor=None, limit=16):
    """Rank hierarchy nodes. Prefer embeddings; else dynamic fuzzy+token score."""
    q_embed = None
    embed_nodes = None
    use_embed = (
        extractor is not None
        and not getattr(extractor, "skip_llm", False)
        and getattr(extractor, "provider", None) == "openai"
    )
    if use_embed:
        embed_nodes = _ensure_node_embeddings(extractor, nodes)
        if embed_nodes is not None:
            bundled = _embed_texts(extractor, [query])
            if bundled:
                q_embed = bundled[0]

    scored = []
    for i, node in enumerate(nodes):
        if q_embed is not None:
            score = _vec_cosine(q_embed, embed_nodes[i])
        else:
            score = _dynamic_score(query, node)
        if score > 0.05:
            scored.append((score, node))
    scored.sort(key=lambda t: t[0], reverse=True)

    # Balanced sample across levels so LLM sees coarse and fine options.
    def _take(level, k):
        out, seen = [], set()
        for score, node in scored:
            if node["level"] != level or node["code"] in seen:
                continue
            seen.add(node["code"])
            out.append((score, node))
            if len(out) >= k:
                break
        return out

    picked = (
        _take("division", 4)
        + _take("subdivision", 6)
        + _take("group", 3)
        + _take("family", 4)
    )
    # Dedupe by (level, code), keep highest score order
    seen = set()
    ordered = []
    for item in sorted(picked + scored[: limit * 2], key=lambda t: t[0], reverse=True):
        key = (item[1]["level"], item[1]["code"])
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
        if len(ordered) >= limit:
            break
    return ordered


def _result_from_node(node, level=None, score=None):
    level = level or node["level"]
    if level == "group":
        level = "subdivision"
    result = {
        "level": level,
        "nco_code": None,
        "code": None,
        "title": None,
        "family_code": node["family_code"] if level == "family" else None,
        "family_title": node["family_title"] if level == "family" else None,
        "group_code": node["group_code"] if level in ("group", "family", "subdivision") else None,
        "group_title": node["group_title"] if level in ("group", "family", "subdivision") else None,
        "subdivision_code": node["subdivision_code"] if level != "division" else None,
        "subdivision_title": node["subdivision_title"] if level != "division" else None,
        "division_code": node["division_code"],
        "division_title": node["division_title"],
        "occupation_title": None,
    }
    if level == "family":
        result["code"] = str(node["family_code"] or "")
        result["title"] = node["family_title"]
    elif level == "subdivision":
        result["code"] = str(node["subdivision_code"] or node["group_code"] or "")
        result["title"] = node["subdivision_title"] or node["group_title"]
    else:
        result["code"] = str(node["division_code"] or "")
        result["title"] = node["division_title"]
        result["level"] = "division"
    if score is not None:
        result["score"] = round(float(score), 3)
    return result


def _alternatives(scored_nodes, chosen_code, limit=4):
    alts = []
    for score, node in scored_nodes:
        if str(node["code"]) == str(chosen_code):
            continue
        alts.append({
            "level": node["level"] if node["level"] != "group" else "subdivision",
            "code": node["code"],
            "title": node["title"],
            "score": round(float(score), 3),
        })
        if len(alts) >= limit:
            break
    return alts


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


def _alias_result(alias_row):
    level = alias_row.get("level") or "division"
    if level == "group":
        level = "subdivision"
    result = {
        "level": level,
        "nco_code": None,
        "code": str(alias_row.get("code") or ""),
        "title": alias_row.get("title") or "",
        "family_code": None,
        "family_title": None,
        "group_code": None,
        "group_title": None,
        "subdivision_code": str(alias_row["code"]) if level == "subdivision" else None,
        "subdivision_title": alias_row.get("title") if level == "subdivision" else None,
        "division_code": str(alias_row["code"]) if level == "division" else None,
        "division_title": alias_row.get("title") if level == "division" else None,
        "occupation_title": None,
        "score": 1.0,
        "alternatives": [],
    }
    if level == "family":
        result["family_code"] = result["code"]
        result["family_title"] = result["title"]
    return _finalize(result, score=1.0, used_embeddings=False, source="alias")


def _lookup_alias(conn, occupation_text):
    if conn is None:
        return None
    try:
        from catalogue import catalogue as _cat
        return _cat.lookup_nco_alias(conn, normalize_occupation_value(occupation_text))
    except Exception:
        return None


def _fallback_best_match(occupation_text, rows, extractor=None):
    """Top shortlist hit — fully dynamic, no label-specific rules."""
    nodes = _hierarchy_nodes(rows)
    scored = _shortlist_nodes(occupation_text, nodes, extractor=extractor, limit=16)
    if not scored:
        return None
    # Always pick the highest-scoring node (shortlist is score-sorted).
    score, node = scored[0]
    level = node["level"]

    # If several top phrases point at different divisions with similar strength,
    # keep the single best node (LLM path can refine when available).
    # Prefer a high-scoring subdivision/family over a weaker parent division
    # already handled by score sort.

    # Soft coarseness: if the winner is family/group but a parent at nearly
    # the same score exists, prefer parent only when parent score is within 3%.
    if level in ("family", "group"):
        parent_level = "subdivision" if level == "family" else "division"
        parent_code_key = "subdivision_code" if parent_level == "subdivision" else "division_code"
        want = str(node.get(parent_code_key) or "")
        for s, n in scored[1:8]:
            if n["level"] == parent_level and str(n["code"]) == want and s >= score * 0.97:
                node, level, score = n, parent_level, s
                break

    used_embed = (
        extractor is not None
        and not getattr(extractor, "skip_llm", False)
        and getattr(extractor, "provider", None) == "openai"
        and _EMBED_CACHE is not None
    )
    result = _result_from_node(node, level=level, score=score)
    result["alternatives"] = _alternatives(scored, result["code"])
    return _finalize(result, score=score, used_embeddings=used_embed, source="fallback")


def match_occupation(conn, occupation_text, extractor=None, shortlist_size=16):
    """Match a category to the coarsest fitting NCO level (dynamic pipeline)."""
    if not occupation_text or not str(occupation_text).strip():
        return None

    occupation_text = str(occupation_text).strip()

    alias = _lookup_alias(conn, occupation_text)
    if alias and alias.get("code"):
        return _alias_result(alias)

    rows = _load_all_codes(conn)
    if not rows:
        return None

    nodes = _hierarchy_nodes(rows)
    scored = _shortlist_nodes(occupation_text, nodes, extractor=extractor, limit=shortlist_size)
    if not scored:
        return None

    used_embed = (
        extractor is not None
        and not getattr(extractor, "skip_llm", False)
        and getattr(extractor, "provider", None) == "openai"
        and _EMBED_CACHE is not None
    )

    if extractor is None or getattr(extractor, "skip_llm", False):
        return _fallback_best_match(occupation_text, rows, extractor=extractor)

    candidates_text = "\n".join(
        f"{node['level']}\t{node['code']}\t{node['title']}"
        for _, node in scored
    )

    prompt = f"""You map a dataset occupation CATEGORY to the National Classification of Occupations (NCO) 2015.

Input value: "{occupation_text}"

Pick the coarsest level that still fits from the candidate list only:
- division — whole major group or several kinds of work in one major group
- subdivision — a clear slice of a major group
- family — only if one 4-digit family clearly fits

If the value spans two major groups, pick the single best candidate from the list
(do not invent combined codes).

Do NOT pick a specific occupation job code (no .0100 / .9900).

Candidate nodes (level, code, title):
{candidates_text}

Return ONLY JSON:
{{
  "level": "division" or "subdivision" or "family",
  "code": the code from the list above,
  "confidence": "high" or "medium" or "low"
}}"""

    try:
        text = extractor._complete(prompt, max_tokens=120)
        text = re.sub(r"```[a-z]*\n?", "", text).strip().rstrip("`").strip()
        decision = json.loads(text)
    except Exception:
        return _fallback_best_match(occupation_text, rows, extractor=extractor)

    level = decision.get("level")
    if level not in ("division", "subdivision", "family"):
        level = None
    code = str(decision.get("code") or "").strip()
    llm_conf = decision.get("confidence")
    if llm_conf not in ("high", "medium", "low"):
        llm_conf = None

    # Trust LLM only when the pick is on the shortlist.
    node = None
    if level and code:
        node = next((n for _, n in scored if str(n["code"]) == code and n["level"] == level), None)
    if node is None and code:
        node = next((n for _, n in scored if str(n["code"]) == code), None)
        if node is not None:
            level = node["level"]

    if node is None:
        return _fallback_best_match(occupation_text, rows, extractor=extractor)

    score = next((s for s, n in scored if n is node), scored[0][0])
    result = _result_from_node(node, level=level or node["level"], score=score)
    result["alternatives"] = _alternatives(scored, result["code"])
    if llm_conf:
        result["confidence"] = llm_conf
    return _finalize(
        result,
        score=score,
        used_embeddings=used_embed,
        source="llm",
    )


def match_occupations(conn, occupation_texts, extractor=None, shortlist_size=16):
    return {
        text: match_occupation(conn, text, extractor=extractor, shortlist_size=shortlist_size)
        for text in occupation_texts
    }
