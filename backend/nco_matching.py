"""NCO 2015 matching at hierarchy level (division / subdivision / family).

Dataset occupation values are almost always broad categories, not job titles.
This module therefore:

  1. Indexes unique NCO *nodes* (division, subdivision, group, family) from
     nco_2015_codes — not the 3,445 specific occupation codes.
  2. Retrieves a shortlist with semantic similarity (OpenAI embeddings when
     the caller is using OpenAI; otherwise content-word cosine — not
     character-level fuzzy matching).
  3. Picks the coarsest fitting level: division for a whole major group,
     subdivision for a slice of one, family only when it uniquely fits.
     Specific .xxxx jobs are never returned.

Public API is still match_occupation / match_occupations.
"""

import json
import math
import re

_CODES_CACHE = None
_NODES_CACHE = None
_EMBED_CACHE = None  # list of (node, vector) aligned with _NODES_CACHE

_STOP = frozenset({
    "a", "an", "and", "the", "of", "or", "etc", "other", "workers", "worker",
    "officials", "official", "support", "related", "not", "elsewhere",
    "classified", "nec", "skilled", "market", "oriented", "related",
})
# Census-style labels use different words than NCO 2015 titles.
_SYNONYMS = {
    "farmer": ("agricultural", "agriculture"),
    "farmers": ("agricultural", "agriculture"),
    "fisherman": ("fishery", "fisher", "fishing"),
    "fishermen": ("fishery", "fisher", "fishing"),
    "hunter": ("hunting", "forestry"),
    "hunters": ("hunting", "forestry"),
    "clerical": ("clerk", "clerks"),
    "sale": ("sales",),
    "managerial": ("manager", "managers"),
    "executive": ("executives", "chief"),
    "professional": ("professionals",),
    "technical": ("technician", "technicians"),
}
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_INPUT_SPLIT_RE = re.compile(r"[,/;]|\s+and\s+|\s+or\s+", re.I)


def _load_from_csv():
    import csv
    import os
    path = os.path.join(os.path.dirname(__file__), "data", "nco_2015_concordance.csv")
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
    return _PUNCT_RE.sub(" ", (text or "").lower()).strip()


def _stem(token):
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _content_tokens(text):
    out = []
    for t in _normalize(text).split():
        if not t or t in _STOP:
            continue
        variants = [t, _stem(t), *(_SYNONYMS.get(t) or ())]
        for v in variants:
            if v and v not in _STOP:
                out.append(v)
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


def _semantic_score_tokens(query, node):
    """Content-word cosine against the node's hierarchy titles.

    Phrases in a comma-joined input are scored separately and the best is
    kept — closer to meaning than character-level fuzzy matching."""
    node_vec = _token_vector(node["search_text"])
    best = 0.0
    for phrase in _input_phrases(query):
        best = max(best, _cosine(_token_vector(phrase), node_vec))
        best = max(best, _cosine(_token_vector(query), node_vec))
    return best


def _embed_texts(extractor, texts):
    """OpenAI embeddings when the extractors's client supports them."""
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


def _shortlist_nodes(query, nodes, extractor=None, limit=12):
    """Rank hierarchy nodes. Prefer OpenAI embeddings; else token cosine."""
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
            score = _semantic_score_tokens(query, node)
        if score > 0:
            scored.append((score, node))
    scored.sort(key=lambda t: t[0], reverse=True)

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
        _take("division", 3)
        + _take("subdivision", 8)
        + _take("group", 2)
        + _take("family", max(4, limit // 3))
    )
    return picked or scored[:limit]


def _result_from_node(node, level=None, score=None):
    level = level or node["level"]
    result = {
        "level": level,
        "nco_code": None,  # never a specific occupation .xxxx code
        "code": None,
        "title": None,
        "family_code": node["family_code"] if level == "family" else None,
        "family_title": node["family_title"] if level == "family" else None,
        "group_code": node["group_code"] if level in ("group", "family") else None,
        "group_title": node["group_title"] if level in ("group", "family") else None,
        "subdivision_code": node["subdivision_code"] if level != "division" else None,
        "subdivision_title": node["subdivision_title"] if level != "division" else None,
        "division_code": node["division_code"],
        "division_title": node["division_title"],
        "occupation_title": None,
    }
    if level == "family":
        result["code"] = str(node["family_code"] or "")
        result["title"] = node["family_title"]
    elif level == "group":
        result["code"] = str(node["group_code"] or "")
        result["title"] = node["group_title"]
    elif level == "subdivision":
        result["code"] = str(node["subdivision_code"] or "")
        result["title"] = node["subdivision_title"]
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
            "level": node["level"],
            "code": node["code"],
            "title": node["title"],
            "score": round(float(score), 3),
        })
        if len(alts) >= limit:
            break
    return alts


def _title_score(query, node):
    fake = dict(node, search_text=node.get("title") or "")
    return _semantic_score_tokens(query, fake)


def _token_overlap(query, title):
    return len(set(_content_tokens(query)) & set(_content_tokens(title)))


def _competing_divisions(query, div_nodes):
    """If slash/comma-joined phrases map to different major groups, return both.

    'PROFESSIONAL / TECHNICAL RELATED WORKERS' is NCO divisions 2 and 3.
    """
    phrases = _input_phrases(query)
    if len(phrases) < 2:
        return None
    picked, seen = [], set()
    for phrase in phrases:
        ranked = sorted(
            ((_title_score(phrase, n), n) for n in div_nodes),
            key=lambda t: t[0],
            reverse=True,
        )
        if not ranked or ranked[0][0] <= 0:
            continue
        node = ranked[0][1]
        if node["code"] in seen:
            continue
        seen.add(node["code"])
        picked.append(ranked[0])
    if len(picked) >= 2:
        return picked
    return None


def _result_from_divisions(pairs, scored):
    pairs = sorted(pairs, key=lambda t: str(t[1]["code"]))
    codes = [str(n["code"]) for _, n in pairs]
    titles = [n["title"] for _, n in pairs]
    result = _result_from_node(pairs[0][1], level="division", score=pairs[0][0])
    result["code"] = " or ".join(codes)
    result["title"] = " / ".join(titles)
    result["codes"] = codes
    result["titles"] = titles
    result["division_code"] = codes[0]
    result["confidence"] = "medium"
    result["alternatives"] = _alternatives(scored, result["code"])
    result["needs_manual_review"] = True
    return result


def _choose_hierarchy_level(query, scored, all_nodes=None):
    """Coarsest NCO level that still fits the category.

    Division when the value is a whole major group (Clerical Workers;
    Farmers, Fishermen, Hunters). Subdivision when it is a slice of a
    major group (Sales Workers; Service Workers; Administrative /
    Executive). Family only when one 4-digit family uniquely fits.
    """
    if not scored:
        return None
    pool = all_nodes or [n for _, n in scored]

    div_nodes = [n for n in pool if n["level"] == "division"]
    if not div_nodes:
        score, node = scored[0]
        level = node["level"] if node["level"] != "group" else "subdivision"
        return node, level, score

    div_ranked = sorted(
        ((_title_score(query, n), n) for n in div_nodes),
        key=lambda t: t[0],
        reverse=True,
    )
    dscore, dnode = div_ranked[0]
    competing_divs = _competing_divisions(query, div_nodes)
    if competing_divs:
        return competing_divs

    dcode = dnode["code"]

    sub_nodes = [n for n in pool if n["level"] == "subdivision" and n["division_code"] == dcode]
    sub_ranked = sorted(
        ((_title_score(query, n), n) for n in sub_nodes),
        key=lambda t: t[0],
        reverse=True,
    )
    competing = [x for x in sub_ranked if x[0] >= sub_ranked[0][0] * 0.85] if sub_ranked else []

    extra = set(_content_tokens(dnode["title"])) - set(_content_tokens(query))
    qtok = set(_content_tokens(query))
    dtok = set(_content_tokens(dnode["title"]))
    covered_by_div = bool(qtok) and (len(qtok & dtok) / len(qtok) >= 0.6)
    spans_major_list = bool(re.search(r"\betc\b", query or "", re.I)) and len(_input_phrases(query)) >= 2
    unique_sub = bool(sub_ranked) and len(competing) == 1 and sub_ranked[0][0] > 0

    if spans_major_list and dscore > 0:
        return dnode, "division", dscore

    if covered_by_div and not extra and dscore > 0:
        return dnode, "division", dscore

    if unique_sub and sub_ranked[0][0] >= dscore * 0.9:
        sscore, snode = sub_ranked[0]
        return snode, "subdivision", sscore

    if extra and sub_ranked:
        sscore, snode = sub_ranked[0]
        return snode, "subdivision", sscore

    if sub_ranked and len(competing) >= 2:
        sscore, snode = sub_ranked[0]
        if _token_overlap(query, snode["title"]) > _token_overlap(query, dnode["title"]):
            return snode, "subdivision", sscore
        if dscore > 0:
            return dnode, "division", dscore
        return snode, "subdivision", sscore

    if sub_ranked and sub_ranked[0][0] > dscore:
        sscore, snode = sub_ranked[0]
        return snode, "subdivision", sscore

    if dscore > 0:
        return dnode, "division", dscore
    if sub_ranked:
        sscore, snode = sub_ranked[0]
        return snode, "subdivision", sscore
    score, node = scored[0]
    return node, node["level"], score


def _fallback_best_match(occupation_text, rows, extractor=None):
    nodes = _hierarchy_nodes(rows)
    scored = _shortlist_nodes(occupation_text, nodes, extractor=extractor, limit=16)
    if not scored:
        return None
    chosen = _choose_hierarchy_level(occupation_text, scored, all_nodes=nodes)
    if not chosen:
        return None
    if isinstance(chosen, list):
        return _result_from_divisions(chosen, scored)
    node, level, score = chosen
    if level == "group":
        level = "subdivision"
    result = _result_from_node(node, level=level, score=score)
    result["confidence"] = "low"
    result["alternatives"] = _alternatives(scored, result["code"])
    result["needs_manual_review"] = True
    return result


def match_occupation(conn, occupation_text, extractor=None, shortlist_size=12):
    """Match a category to the coarsest fitting NCO level (division, subdivision, or family)."""
    if not occupation_text or not occupation_text.strip():
        return None

    rows = _load_all_codes(conn)
    if not rows:
        return None

    nodes = _hierarchy_nodes(rows)
    scored = _shortlist_nodes(occupation_text, nodes, extractor=extractor, limit=shortlist_size)
    if not scored:
        return None

    if extractor is None or getattr(extractor, "skip_llm", False):
        return _fallback_best_match(occupation_text, rows, extractor=extractor)

    candidates_text = "\n".join(
        f"{node['level']}\t{node['code']}\t{node['title']}"
        for _, node in scored
    )

    prompt = f"""You map a dataset occupation CATEGORY to the National Classification of Occupations (NCO) 2015.

Input value: "{occupation_text}"

Pick the coarsest level that still fits:
- division if the value names a whole major group or lists several kinds of
  work in that group (e.g. "Clerical Workers"; "Farmers, Fishermen, Hunters")
- if the value names two major groups (e.g. "Professional / Technical Workers"),
  say so — that is divisions 2 and 3, not only 2
- subdivision if the value is a slice of a major group
  (e.g. "Sales Workers"; "Service Workers"; "Administrative, Executive and Managerial")
- family only if one 4-digit family clearly fits

Do NOT pick a specific occupation (no .0100 / .9900 job codes).

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
        level = "subdivision"
    code = str(decision.get("code") or "").strip()
    node = next((n for _, n in scored if str(n["code"]) == code and n["level"] == level), None)
    if node is None:
        node = next((n for _, n in scored if str(n["code"]) == code), None)
    if node is None:
        node = scored[0][1]
        level = node["level"]
    chosen = _choose_hierarchy_level(occupation_text, scored, all_nodes=nodes)
    if chosen and isinstance(chosen, list):
        result = _result_from_divisions(chosen, scored)
        result["confidence"] = decision.get("confidence", "medium")
        return result
    if chosen:
        node, level, score = chosen
    else:
        score = next((s for s, n in scored if n is node), None)
    if level == "group":
        level = "subdivision"
    result = _result_from_node(node, level=level, score=score)
    result["confidence"] = decision.get("confidence", "medium")
    result["alternatives"] = _alternatives(scored, result["code"])
    result["needs_manual_review"] = True
    return result


def match_occupations(conn, occupation_texts, extractor=None, shortlist_size=12):
    return {
        text: match_occupation(conn, text, extractor=extractor, shortlist_size=shortlist_size)
        for text in occupation_texts
    }
