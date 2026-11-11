"""Local NCO occupation matching.

Hybrid retrieval over the master rows in ``nco_2015_codes``. Exact title,
approved alias, fuzzy match, title unigram BM25, phrase BM25, and semantic
search each return their own candidates. Reciprocal rank fusion merges
those ranked lists. Phrase alignment is applied with the cross-encoder
when the shortlist is scored, not as a fusion multiplier. Hierarchy titles
are a separate index. Medium-confidence rows refresh hierarchy candidates
from parents of the top occupations plus embedding nearest neighbours,
then re-apply specificity rules. The chat model is not called here.

Does not write PDF grouping embeddings.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher

# Conservative expansions only. Related jobs are not treated as synonyms.
_ABBREV = {
    "sr": "senior",
    "jr": "junior",
    "asst": "assistant",
    "engr": "engineer",
    "engg": "engineer",
    "mgr": "manager",
    "dev": "developer",
}
# Function words only. Residual markers (other, nec, support, worker, …)
# stay in occupation titles and in the value being classified.
_GENERIC_STOP = frozenset({
    "a", "an", "and", "the", "of", "or", "etc", "related",
})
# Dropped only from column names and table headings, not from official titles.
_NON_TITLE_STOP = frozenset({"worker", "workers"})
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_NEC_PHRASE_RE = re.compile(r"\bnot elsewhere classified\b")
_NEC_INITIALS_RE = re.compile(r"\bn e c\b")

# Initial weights from the matching design. Renormalized over signals
# that are actually present so a missing table heading does not cap the score.
_WEIGHTS = {
    "semantic": 0.30,
    "rerank": 0.30,
    "lexical": 0.15,
    "alias": 0.10,
    "context": 0.10,
    "hierarchy": 0.05,
}
_AUTO_SCORE = 0.90
_REVIEW_SCORE = 0.75
_MARGIN = 0.05
_UNMATCHED_LEXICAL = 0.42
# Each method contributes its own top hits. The merged shortlist is capped
# after deduplication; these sizes are benchmarks, not a recall guarantee.
_FUZZY_K = 10
_BM25_K = 10
_PHRASE_K = 10
_SEMANTIC_K = 10
# Title-only documents are short, so the usual length penalty is unchanged.
# Hierarchy wording is not mixed into this index.
_TITLE_BM25_B = 0.75
_SHORTLIST = 25
# Standard reciprocal-rank smoothing. Ranks are 1-based.
_RRF_K = 60
# Deepest first. A broader level is used only when it has its own evidence.
_LEVELS = ("occupation", "family", "group", "subdivision", "division")
# Overlap on these words alone does not identify a classification node.
_GENERIC_EVIDENCE = frozenset({"worker", "other", "support"})
# A broader heading may contain the query plus one of these structural words.
# A content word such as "street" or "sale" is a different classification.
_STRUCTURAL_EXTRA = frozenset({"support", "other"})
_LEVEL_WEIGHTS = {
    "occupation": {
        "semantic": 0.30, "rerank": 0.30, "lexical": 0.15,
        "alias": 0.10, "context": 0.10, "hierarchy": 0.05,
    },
    # Broader titles are judged on their own wording, not on a short-title bonus.
    "family": {
        "semantic": 0.15, "rerank": 0.35, "lexical": 0.35,
        "alias": 0.00, "context": 0.10, "hierarchy": 0.05,
    },
    "group": {
        "semantic": 0.15, "rerank": 0.35, "lexical": 0.35,
        "alias": 0.00, "context": 0.10, "hierarchy": 0.05,
    },
    "subdivision": {
        "semantic": 0.10, "rerank": 0.40, "lexical": 0.40,
        "alias": 0.00, "context": 0.05, "hierarchy": 0.05,
    },
    "division": {
        "semantic": 0.10, "rerank": 0.40, "lexical": 0.40,
        "alias": 0.00, "context": 0.05, "hierarchy": 0.05,
    },
}
_LEVEL_AUTO = {
    "occupation": 0.90,
    "family": 0.80,
    "group": 0.82,
    "subdivision": 0.84,
    "division": 0.86,
}
# Review pass: parents of the top occupations + hierarchy neighbours.
_REVIEW_OCC_PARENTS = 5
_REVIEW_HIERARCHY_K = 20
_REVIEW_EMBED_FLOOR = 0.62

_INDEX_CACHE = {"key": None, "index": None}
_EMBEDDER = None
_EMBEDDER_TRIED = False
_CROSS = None
_CROSS_TRIED = False


def clear_index_cache():
    global _EMBEDDER, _EMBEDDER_TRIED, _CROSS, _CROSS_TRIED
    _INDEX_CACHE["key"] = None
    _INDEX_CACHE["index"] = None
    _EMBEDDER = None
    _EMBEDDER_TRIED = False
    _CROSS = None
    _CROSS_TRIED = False


def normalize_text(text) -> str:
    """Lowercase, strip punctuation, and collapse NEC forms to one marker."""
    s = _PUNCT_RE.sub(" ", (text or "").lower())
    s = re.sub(r"\s+", " ", s).strip()
    s = _NEC_PHRASE_RE.sub("nec", s)
    s = _NEC_INITIALS_RE.sub("nec", s)
    return s


def expand_abbreviations(normalized: str) -> str:
    """Expand a short abbreviation list. Leaves the source cell untouched."""
    if not normalized:
        return ""
    return " ".join(_ABBREV.get(tok, tok) for tok in normalized.split())


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(text: str, *, classification_sensitive: bool = True) -> list[str]:
    """Tokenize a field.

    Official titles and the value being classified keep worker/workers.
    Column names and table headings do not.
    """
    out = []
    for raw in (text or "").split():
        if not raw or raw in _GENERIC_STOP:
            continue
        if not classification_sensitive and raw in _NON_TITLE_STOP:
            continue
        stemmed = _stem(raw)
        if not stemmed or stemmed in _GENERIC_STOP:
            continue
        if not classification_sensitive and stemmed in _NON_TITLE_STOP:
            continue
        out.append(stemmed)
    return out


def _word_ngrams(tokens: list[str], max_n: int = 3) -> list[str]:
    """Unigrams plus ordered word sequences, joined so a phrase is one feature."""
    features = list(tokens)
    for n in range(2, max_n + 1):
        features.extend(
            "_".join(tokens[i:i + n])
            for i in range(len(tokens) - n + 1)
        )
    return features


def _phrase_features(tokens: list[str], max_n: int = 3) -> list[str]:
    """Bigrams and trigrams only. Unigrams stay in the title BM25 index."""
    return [feat for feat in _word_ngrams(tokens, max_n) if "_" in feat]


def _phrase_alignment_score(query: str, title: str) -> float:
    """How much of the query survives as an ordered token span in the title.

    A full title match is stronger than a multi-word phrase inside a longer
    title. A single shared word inside a longer title is weak evidence.
    """
    q = _tokens(expand_abbreviations(normalize_text(query)))
    d = _tokens(expand_abbreviations(normalize_text(title)))
    if not q or not d:
        return 0.0
    if q == d:
        return 1.0
    if len(q) > len(d):
        return 0.0
    span = len(q)
    for i in range(len(d) - span + 1):
        if d[i:i + span] == q:
            return 0.85 if span >= 2 else 0.45
    return 0.0


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    compact = (text or "").replace(" ", "")
    if len(compact) < n:
        return {compact} if compact else set()
    return {compact[i:i + n] for i in range(len(compact) - n + 1)}


def _fuzzy(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    try:
        from rapidfuzz import fuzz
        return float(fuzz.WRatio(a, b)) / 100.0
    except Exception:
        seq = SequenceMatcher(None, a, b).ratio()
        sort_a = " ".join(sorted(a.split()))
        sort_b = " ".join(sorted(b.split()))
        return max(seq, SequenceMatcher(None, sort_a, sort_b).ratio())


def _f1(query_tokens: set, doc_tokens: set) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    inter = len(query_tokens & doc_tokens)
    if not inter:
        return 0.0
    precision = inter / len(doc_tokens)
    recall = inter / len(query_tokens)
    return 2 * precision * recall / (precision + recall)


class _BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = _TITLE_BM25_B):
        self.k1 = k1
        self.b = b
        self.N = len(docs)
        self.tf = []
        self.dl = []
        df = Counter()
        total = 0
        for doc in docs:
            counts = Counter(doc)
            self.tf.append(counts)
            self.dl.append(len(doc))
            total += len(doc)
            df.update(counts.keys())
        self.avgdl = (total / self.N) if self.N else 0.0
        self.idf = {
            term: math.log(1.0 + (self.N - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def scores(self, query: list[str]) -> dict[int, float]:
        out = {}
        if not self.N or not self.avgdl:
            return out
        seen = set()
        for term in query:
            if term in seen:
                continue
            seen.add(term)
            idf = self.idf.get(term)
            if not idf:
                continue
            for idx, counts in enumerate(self.tf):
                freq = counts.get(term)
                if not freq:
                    continue
                denom = freq + self.k1 * (1 - self.b + self.b * self.dl[idx] / self.avgdl)
                out[idx] = out.get(idx, 0.0) + idf * (freq * (self.k1 + 1) / denom)
        return out


def _unit(vec: dict[str, float]) -> tuple[dict[str, float], float]:
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / norm for k, v in vec.items()}, norm


def _cosine_sparse(query: dict[str, float], doc: dict[str, float]) -> float:
    if not query or not doc:
        return 0.0
    return sum(query[k] * doc.get(k, 0.0) for k in query)


def _load_embedder():
    """Optional local model. Unset NCO_EMBEDDING_MODEL keeps matching offline and instant.

    Recommended: ``google/embeddinggemma-300m``. Set ``HF_TOKEN`` if Hub access is gated.
    """
    global _EMBEDDER, _EMBEDDER_TRIED
    if _EMBEDDER_TRIED:
        return _EMBEDDER
    _EMBEDDER_TRIED = True
    name = os.environ.get("NCO_EMBEDDING_MODEL", "").strip()
    if not name:
        _EMBEDDER = None
        return None
    try:
        import torch
        from sentence_transformers import SentenceTransformer

        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or None
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        model_kwargs = {
            "torch_dtype": dtype,
            "low_cpu_mem_usage": True,
        }
        _EMBEDDER = SentenceTransformer(
            name,
            trust_remote_code=True,
            token=token,
            model_kwargs=model_kwargs,
        )
        if not torch.cuda.is_available():
            _EMBEDDER = _EMBEDDER.to("cpu")
    except Exception:
        _EMBEDDER = None
    return _EMBEDDER


def _load_cross_encoder():
    global _CROSS, _CROSS_TRIED
    if _CROSS_TRIED:
        return _CROSS
    _CROSS_TRIED = True
    name = os.environ.get("NCO_CROSS_ENCODER_MODEL", "").strip()
    if not name:
        _CROSS = None
        return None
    try:
        from sentence_transformers import CrossEncoder
        _CROSS = CrossEncoder(name)
    except Exception:
        _CROSS = None
    return _CROSS


def build_index(rows, extra_aliases=None):
    """One search record per occupation, hierarchy attached to the record."""
    docs = []
    by_title = defaultdict(list)
    postings = defaultdict(list)
    char_postings = defaultdict(list)
    token_docs = []
    title_token_docs = []
    phrase_docs = []
    for row in rows or []:
        title = str(row.get("occupation_title") or "").strip()
        code = str(row.get("nco_code") or "").strip()
        if not title or not code:
            continue
        norm = normalize_text(title)
        expanded = expand_abbreviations(norm)
        title_tokens = _tokens(expanded)
        family_tokens = set(_tokens(normalize_text(row.get("family_title"))))
        group_tokens = set(_tokens(normalize_text(row.get("group_title"))))
        subdivision_tokens = set(_tokens(normalize_text(row.get("subdivision_title"))))
        division_tokens = set(_tokens(normalize_text(row.get("division_title"))))
        search_tokens = list(dict.fromkeys(
            title_tokens
            + list(family_tokens)
            + list(group_tokens)
            + list(subdivision_tokens)
            + list(division_tokens)
        ))
        search_text = " | ".join(filter(None, [
            title,
            str(row.get("family_title") or ""),
            str(row.get("group_title") or ""),
            str(row.get("subdivision_title") or ""),
            str(row.get("division_title") or ""),
        ]))
        idx = len(docs)
        docs.append({
            "level": "occupation",
            "code": code,
            "row": row,
            "nco_code": code,
            "title": title,
            "norm_title": expanded,
            "search_text": search_text,
            "title_tokens": set(title_tokens),
            "family_tokens": family_tokens,
            "group_tokens": group_tokens,
            "subdivision_tokens": subdivision_tokens,
            "division_tokens": division_tokens,
        })
        token_docs.append(search_tokens)
        title_token_docs.append(list(title_tokens))
        phrase_docs.append(_phrase_features(title_tokens))
        by_title[expanded].append(idx)
        if norm != expanded:
            by_title[norm].append(idx)
        for tok in set(search_tokens):
            postings[tok].append(idx)
        for gram in _char_ngrams(expanded):
            char_postings[gram].append(idx)

    alias_to_idx = defaultdict(list)
    for alias in extra_aliases or []:
        norm_alias = expand_abbreviations(normalize_text(alias.get("normalized_alias") or alias.get("alias_text")))
        code = str(alias.get("nco_code") or "").strip()
        if not norm_alias or not code:
            continue
        for idx, doc in enumerate(docs):
            if doc["nco_code"] == code:
                alias_to_idx[norm_alias].append(idx)
                break

    bm25 = _BM25(title_token_docs)
    phrase_bm25 = _BM25(phrase_docs)
    df = Counter()
    for doc in token_docs:
        df.update(set(doc))
    n = len(token_docs) or 1
    idf = {term: math.log((n + 1) / (freq + 0.5)) + 1.0 for term, freq in df.items()}
    tfidf = []
    for doc in token_docs:
        counts = Counter(doc)
        raw = {}
        for term, freq in counts.items():
            weight = idf.get(term)
            if weight:
                raw[term] = (1.0 + math.log(freq)) * weight
        vec, _ = _unit(raw)
        tfidf.append(vec)

    embeddings = None
    embedder = _load_embedder()
    if embedder is not None and docs:
        try:
            texts = [d["search_text"] for d in docs]
            embeddings = embedder.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        except Exception:
            embeddings = None

    return {
        "docs": docs,
        "by_title": by_title,
        "postings": postings,
        "alias_to_idx": alias_to_idx,
        "bm25": bm25,
        "phrase_bm25": phrase_bm25,
        "idf": idf,
        "tfidf": tfidf,
        "embeddings": embeddings,
        "norm_titles": [d["norm_title"] for d in docs],
        "char_postings": char_postings,
        "query_embeddings": {},
        "query_tfidf": {},
        "hierarchy": _pack_level_index(_hierarchy_docs(rows)),
    }


def _hierarchy_docs(rows):
    """One node per division, subdivision, group, and family code."""
    specs = (
        ("division", ("division",)),
        ("subdivision", ("division", "subdivision")),
        ("group", ("division", "subdivision", "group")),
        ("family", ("division", "subdivision", "group", "family")),
    )
    seen = set()
    docs = []
    for row in rows or []:
        for level, parts in specs:
            code = str(row.get(f"{level}_code") or "").strip()
            title = str(row.get(f"{level}_title") or "").strip()
            if not code or not title or (level, code) in seen:
                continue
            seen.add((level, code))
            docs.append(_hierarchy_doc(row, level, code, title, parts))
    return docs


def _hierarchy_doc(row, level, code, title, parts):
    expanded = expand_abbreviations(normalize_text(title))
    ordered_title = _tokens(expanded)
    title_tokens = set(ordered_title)
    token_sets = {part: set() for part in ("division", "subdivision", "group", "family")}
    titles = []
    stored = {}
    for part in ("division", "subdivision", "group", "family"):
        part_code = str(row.get(f"{part}_code") or "").strip()
        part_title = str(row.get(f"{part}_title") or "").strip()
        if part not in parts:
            stored[f"{part}_code"] = None
            stored[f"{part}_title"] = None
            continue
        stored[f"{part}_code"] = part_code or None
        stored[f"{part}_title"] = part_title or None
        token_sets[part] = set(_tokens(normalize_text(part_title)))
        if part_title:
            titles.append(part_title)
    if level == "family":
        token_sets["family"] = set(title_tokens)
        stored["family_code"] = code
        stored["family_title"] = title
    stored["nco_code"] = None
    stored["occupation_title"] = None
    return {
        "level": level,
        "code": code,
        "row": stored,
        "nco_code": f"{level}:{code}",
        "title": title,
        "norm_title": expanded,
        "search_text": " | ".join(dict.fromkeys(titles)),
        "title_token_seq": ordered_title,
        "title_tokens": title_tokens,
        "family_tokens": token_sets["family"],
        "group_tokens": token_sets["group"],
        "subdivision_tokens": token_sets["subdivision"],
        "division_tokens": token_sets["division"],
    }


def _pack_level_index(docs):
    """Search structures for one hierarchy layer. Separate from occupation retrieval."""
    by_title = defaultdict(list)
    char_postings = defaultdict(list)
    token_docs = []
    phrase_docs = []
    for idx, doc in enumerate(docs):
        ordered = list(doc.get("title_token_seq") or doc["title_tokens"])
        token_docs.append(ordered)
        phrase_docs.append(_phrase_features(ordered))
        by_title[doc["norm_title"]].append(idx)
        for gram in _char_ngrams(doc["norm_title"]):
            char_postings[gram].append(idx)
    bm25 = _BM25(token_docs)
    phrase_bm25 = _BM25(phrase_docs)
    df = Counter()
    for doc in token_docs:
        df.update(set(doc))
    n = len(token_docs) or 1
    idf = {term: math.log((n + 1) / (freq + 0.5)) + 1.0 for term, freq in df.items()}
    tfidf = []
    for doc in token_docs:
        counts = Counter(doc)
        raw = {}
        for term, freq in counts.items():
            weight = idf.get(term)
            if weight:
                raw[term] = (1.0 + math.log(freq)) * weight
        vec, _norm = _unit(raw)
        tfidf.append(vec)
    by_level_code = {
        (doc["level"], doc["code"]): idx for idx, doc in enumerate(docs)
    }
    embeddings = None
    embedder = _load_embedder()
    if embedder is not None and docs:
        try:
            texts = [d["search_text"] or d["title"] for d in docs]
            embeddings = embedder.encode(
                texts, normalize_embeddings=True, show_progress_bar=False,
            )
        except Exception:
            embeddings = None
    return {
        "docs": docs,
        "by_title": by_title,
        "postings": defaultdict(list),
        "alias_to_idx": defaultdict(list),
        "bm25": bm25,
        "phrase_bm25": phrase_bm25,
        "idf": idf,
        "tfidf": tfidf,
        "embeddings": embeddings,
        "norm_titles": [d["norm_title"] for d in docs],
        "char_postings": char_postings,
        "by_level_code": by_level_code,
        "query_embeddings": {},
        "query_tfidf": {},
    }


def get_index(rows, extra_aliases=None):
    key = (
        len(rows or []),
        str((rows or [{}])[0].get("nco_code") or "") if rows else "",
        str((rows or [{}])[-1].get("nco_code") or "") if rows else "",
        len(extra_aliases or []),
    )
    if _INDEX_CACHE["key"] == key and _INDEX_CACHE["index"] is not None:
        return _INDEX_CACHE["index"]
    index = build_index(rows, extra_aliases=extra_aliases)
    _INDEX_CACHE["key"] = key
    _INDEX_CACHE["index"] = index
    return index


def _query_vector(index, tokens: list[str]) -> dict[str, float]:
    counts = Counter(tokens)
    raw = {}
    for term, freq in counts.items():
        weight = index["idf"].get(term)
        if weight:
            raw[term] = (1.0 + math.log(freq)) * weight
    vec, _ = _unit(raw)
    return vec


def _cached_query_embedding(index, embedder, query_text):
    """Encode the query once per distinct text and reuse it for every candidate."""
    cache = index.setdefault("query_embeddings", {})
    cached = cache.get(query_text)
    if cached is not None:
        return cached
    vector = embedder.encode(
        [query_text],
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0]
    cache[query_text] = vector
    return vector


def _cached_query_tfidf(index, query_tokens, query_text):
    cache = index.setdefault("query_tfidf", {})
    cached = cache.get(query_text)
    if cached is not None:
        return cached
    vector = _query_vector(index, query_tokens)
    cache[query_text] = vector
    return vector


def _top_dense(query, matrix, k):
    """Cosine-style dot product of one query against every occupation vector."""
    try:
        import numpy as np
        scores = np.asarray(matrix, dtype=float) @ np.asarray(query, dtype=float)
        count = int(scores.shape[0])
        take = min(k, count)
        if count > take:
            part = np.argpartition(scores, -take)[-take:]
            order = part[np.argsort(scores[part])[::-1]]
        else:
            order = np.argsort(scores)[::-1]
        return [(int(i), max(0.0, min(1.0, float(scores[i])))) for i in order]
    except Exception:
        scored = []
        for i, row in enumerate(matrix):
            scored.append((
                max(0.0, min(1.0, sum(float(a) * float(b) for a, b in zip(query, row)))),
                i,
            ))
        scored.sort(reverse=True)
        return [(i, score) for score, i in scored[:k]]


def _dense_selected(query, matrix, idxs):
    """Cosine of one query against specific rows. Does not sort the registry."""
    if not idxs:
        return []
    try:
        import numpy as np
        rows = np.asarray(matrix, dtype=float)[list(idxs)]
        scores = rows @ np.asarray(query, dtype=float)
        return [
            (idx, max(0.0, min(1.0, float(scores[pos]))))
            for pos, idx in enumerate(idxs)
        ]
    except Exception:
        out = []
        for idx in idxs:
            row = matrix[idx]
            score = sum(float(a) * float(b) for a, b in zip(query, row))
            out.append((idx, max(0.0, min(1.0, score))))
        return out


def _semantic_hits(index, query_text, query_tokens, k):
    """Top semantic candidates over the full registry, not a lexical shortlist."""
    embeddings = index.get("embeddings")
    embedder = _load_embedder()
    if embeddings is not None and embedder is not None:
        try:
            query = _cached_query_embedding(index, embedder, query_text)
            hits = _top_dense(query, embeddings, k)
            return [(idx, score) for idx, score in hits if score > 0.05], "embedding"
        except Exception:
            pass
    query = _cached_query_tfidf(index, query_tokens, query_text)
    scored = [
        (_cosine_sparse(query, doc), idx)
        for idx, doc in enumerate(index["tfidf"])
    ]
    scored.sort(reverse=True)
    hits = [(idx, max(0.0, score)) for score, idx in scored[:k] if score > 0.05]
    return hits, "tfidf"


def _fuzzy_top(index, normalized, k):
    """Fuzzy hits independent of the token postings used by BM25."""
    titles = index.get("norm_titles") or []
    if not titles or not normalized:
        return []
    try:
        from rapidfuzz import fuzz, process
        found = process.extract(normalized, titles, scorer=fuzz.WRatio, limit=k)
        return [
            (idx, float(score) / 100.0)
            for _title, score, idx in found
            if score and float(score) > 0
        ]
    except Exception:
        pass
    counts = Counter()
    for gram in _char_ngrams(normalized):
        for idx in index.get("char_postings", {}).get(gram, ()):
            counts[idx] += 1
    pool = [idx for idx, _count in counts.most_common(80)]
    if not pool:
        pool = list(range(min(len(titles), k)))
    scored = [(_fuzzy(normalized, titles[idx]), idx) for idx in pool]
    scored.sort(reverse=True)
    return [(idx, score) for score, idx in scored[:k] if score > 0.3]


def _hierarchy_consistency(query_tokens: set, doc) -> float:
    """Parent agreement for a node. A parent match is not evidence for the child."""
    if not query_tokens:
        return 0.0
    level = doc.get("level") or "occupation"
    if level != "occupation":
        own = doc.get("title_tokens") or set()
        if not own or not (query_tokens & own):
            return 0.0
        own_cover = len(query_tokens & own) / len(query_tokens)
        parents = set()
        for key in ("division_tokens", "subdivision_tokens", "group_tokens", "family_tokens"):
            parents |= doc.get(key) or set()
        parents -= own
        parent_cover = (len(query_tokens & parents) / len(query_tokens)) if parents else 0.0
        return min(1.0, 0.85 * own_cover + 0.15 * parent_cover)
    levels = (
        doc["division_tokens"],
        doc["subdivision_tokens"],
        doc["group_tokens"],
        doc["family_tokens"],
        doc["title_tokens"],
    )
    path = set()
    for tokens in levels:
        path |= tokens
    cover = len(query_tokens & path) / len(query_tokens)
    parent = 0.0
    for tokens in levels[:-1]:
        if tokens and query_tokens <= tokens:
            parent = 1.0
            break
    return 0.5 * cover + 0.5 * parent


def _add_hit(found, idx, method, rank, score):
    slot = found.setdefault(idx, [])
    slot.append({"method": method, "rank": rank, "score": float(score)})


def _rrf_score(hits) -> float:
    """Reciprocal rank fusion. ``rank`` is 1-based within each method."""
    return sum(1.0 / (_RRF_K + hit["rank"]) for hit in hits)


def _fill_semantic_scores(index, normalized, query_tokens, ordered, semantic_scores, semantic_name):
    """Cosine only for merged candidates that were outside the semantic top-k."""
    missing = [idx for idx, _hits in ordered if idx not in semantic_scores]
    if not missing:
        return
    if semantic_name == "embedding" and index.get("embeddings") is not None:
        embedder = _load_embedder()
        if embedder is None:
            return
        try:
            query = _cached_query_embedding(index, embedder, normalized)
            for idx, score in _dense_selected(query, index["embeddings"], missing):
                semantic_scores[idx] = score
        except Exception:
            return
        return
    if semantic_name == "tfidf":
        query = _cached_query_tfidf(index, query_tokens, normalized)
        for idx in missing:
            semantic_scores[idx] = max(0.0, _cosine_sparse(query, index["tfidf"][idx]))


def _retrieve(index, normalized, query_tokens):
    """Run each retriever on its own, then fuse ranks and dedupe by NCO code."""
    found = {}
    for rank, idx in enumerate(dict.fromkeys(index["by_title"].get(normalized, ())), start=1):
        _add_hit(found, idx, "exact", rank, 1.0)
    for rank, idx in enumerate(dict.fromkeys(index["alias_to_idx"].get(normalized, ())), start=1):
        _add_hit(found, idx, "alias", rank, 0.98)
    for rank, (idx, score) in enumerate(_fuzzy_top(index, normalized, _FUZZY_K), start=1):
        _add_hit(found, idx, "fuzzy", rank, score)

    bm25_raw = index["bm25"].scores(query_tokens)
    bm25_top = sorted(bm25_raw.items(), key=lambda item: item[1], reverse=True)[:_BM25_K]
    max_bm25 = bm25_top[0][1] if bm25_top else 0.0
    for rank, (idx, score) in enumerate(bm25_top, start=1):
        if score <= 0:
            continue
        _add_hit(found, idx, "bm25", rank, (score / max_bm25) if max_bm25 else 0.0)

    phrase_raw = {}
    max_phrase = 0.0
    phrase_index = index.get("phrase_bm25")
    phrase_query = _phrase_features(query_tokens)
    if phrase_index is not None and phrase_query:
        phrase_raw = phrase_index.scores(phrase_query)
        phrase_top = sorted(phrase_raw.items(), key=lambda item: item[1], reverse=True)[:_PHRASE_K]
        max_phrase = phrase_top[0][1] if phrase_top else 0.0
        for rank, (idx, score) in enumerate(phrase_top, start=1):
            if score <= 0:
                continue
            _add_hit(found, idx, "phrase_bm25", rank, (score / max_phrase) if max_phrase else 0.0)

    semantic_hits, semantic_name = _semantic_hits(index, normalized, query_tokens, _SEMANTIC_K)
    semantic_scores = {}
    for rank, (idx, score) in enumerate(semantic_hits, start=1):
        semantic_scores[idx] = score
        _add_hit(found, idx, semantic_name, rank, score)

    def sort_key(item):
        _idx, hits = item
        return (-_rrf_score(hits), min(hit["rank"] for hit in hits))

    ordered = []
    seen_codes = set()
    for idx, hits in sorted(found.items(), key=sort_key):
        code = index["docs"][idx]["nco_code"]
        if code in seen_codes:
            continue
        seen_codes.add(code)
        ordered.append((idx, hits))
        if len(ordered) >= _SHORTLIST:
            break
    _fill_semantic_scores(
        index, normalized, query_tokens, ordered, semantic_scores, semantic_name,
    )
    return ordered, bm25_raw, max_bm25, semantic_scores, semantic_name, phrase_raw, max_phrase


def _batch_rerank(query_text, query_tokens, idxs, index):
    """Score every shortlist pair in one cross-encoder call when a model is configured."""
    docs = [index["docs"][idx] for idx in idxs]
    cross = _load_cross_encoder()
    if cross is not None and docs:
        try:
            pairs = [(query_text, doc["search_text"]) for doc in docs]
            raw = cross.predict(pairs, batch_size=32, show_progress_bar=False)
            scores = []
            for value in raw:
                score = float(value)
                if score < 0.0 or score > 1.0:
                    score = 1.0 / (1.0 + math.exp(-score))
                scores.append(max(0.0, min(1.0, score)))
            return scores, "cross_encoder"
        except Exception:
            pass
    scores = []
    for doc in docs:
        title_f = _f1(query_tokens, doc["title_tokens"])
        path = (
            doc["family_tokens"]
            | doc["group_tokens"]
            | doc["subdivision_tokens"]
            | doc["division_tokens"]
        )
        scores.append(max(title_f, 0.85 * _f1(query_tokens, path)))
    return scores, "lexical_rerank"


def _combine(signals: dict[str, float], use_context: bool, use_hierarchy: bool, level: str = "occupation") -> float:
    weights = _LEVEL_WEIGHTS.get(level) or _WEIGHTS
    names = ["semantic", "rerank", "lexical"]
    if level == "occupation" or signals.get("alias"):
        names.append("alias")
    if use_context and weights.get("context"):
        names.append("context")
    if use_hierarchy and weights.get("hierarchy"):
        names.append("hierarchy")
    total_w = sum(weights[name] for name in names) or 1.0
    return sum(weights[name] * signals.get(name, 0.0) for name in names) / total_w


def _result_from_doc(doc, *, status, score, methods, reason, normalized, source_value, alternatives):
    row = doc.get("row") or {}
    level = doc.get("level") or "occupation"
    high = status in ("exact_match", "alias_match", "auto_matched")
    confidence = "high" if high else ("low" if status == "unmatched" else "medium")
    if status == "unmatched":
        code = None
    elif level == "occupation":
        code = doc.get("nco_code") or doc.get("code")
    else:
        code = doc.get("code")
    title = None if status == "unmatched" else doc.get("title")
    occupation_code = code if level == "occupation" else None
    return {
        "level": level,
        "nco_code": occupation_code,
        "occupation_code": occupation_code,
        "code": code,
        "title": title,
        "occupation_title": title if level == "occupation" else None,
        "family_code": row.get("family_code"),
        "family_title": row.get("family_title"),
        "group_code": row.get("group_code"),
        "group_title": row.get("group_title"),
        "subdivision_code": row.get("subdivision_code"),
        "subdivision_title": row.get("subdivision_title"),
        "division_code": row.get("division_code"),
        "division_title": row.get("division_title"),
        "score": round(float(score), 3),
        "confidence_score": round(float(score), 3),
        "confidence": confidence,
        "auto_fill": high,
        "needs_manual_review": not high,
        "source": "nco_pipeline",
        "status": status,
        "matching_method": methods,
        "reason": reason,
        "normalized_value": normalized,
        "source_value": source_value,
        "alternatives": alternatives,
        "needs_llm": status == "needs_review" and score >= _REVIEW_SCORE,
    }


def _title_evidence(qset, title_tokens):
    """Evidence from a node's own title. Parent words are not counted."""
    title_tokens = set(title_tokens or ())
    overlap = set(qset or ()) & title_tokens
    extra = title_tokens - set(qset or ())
    if not qset or not title_tokens:
        recall = precision = 0.0
    else:
        recall = len(overlap) / len(qset)
        precision = len(overlap) / len(title_tokens)
    return {
        "recall": recall,
        "precision": precision,
        "title_subset": bool(title_tokens) and title_tokens <= set(qset or ()),
        "query_subset": bool(qset) and set(qset) <= title_tokens,
        "token_exact": bool(qset) and title_tokens == set(qset),
        "extra": extra,
        "distinctive": bool(overlap - _GENERIC_EVIDENCE),
    }


def _lexically_supported(level, evidence, score) -> bool:
    """True when this node, not its parent or its child, is supported by the input."""
    if not evidence["distinctive"]:
        return False
    if level == "occupation":
        return evidence["title_subset"] and evidence["recall"] >= 0.34 and score >= 0.45
    if evidence["token_exact"] and evidence["recall"] >= 0.67 and score >= 0.45:
        return True
    if evidence["title_subset"] and evidence["recall"] >= 0.67 and score >= 0.5:
        return True
    # A slightly longer official heading may still be the class that was named
    # when the only added words are structural (support, other).
    return (
        evidence["query_subset"]
        and evidence["recall"] >= 0.67
        and evidence["precision"] >= 0.5
        and set(evidence["extra"]) <= _STRUCTURAL_EXTRA
        and score >= 0.5
    )


_LEVEL_REASON = {
    "occupation": "The input names this occupation and it is separated from the next candidate.",
    "family": "The input supports the family classification, but does not provide sufficient evidence for a specific occupation.",
    "group": "The input supports the group classification, but does not provide sufficient evidence for a family or occupation.",
    "subdivision": "The input supports the subdivision classification, but does not provide sufficient evidence for a more specific code.",
    "division": "The input supports the division classification, but does not provide sufficient evidence for a more specific code.",
}


def _mixed_alternatives(items, chosen, limit=4):
    alts = []
    seen = set()
    if chosen is not None:
        seen.add((chosen.get("level"), chosen.get("code")))
    for item in sorted(items, key=lambda it: it["score"], reverse=True):
        key = (item["level"], item["code"])
        if key in seen:
            continue
        seen.add(key)
        row = item["doc"].get("row") or {}
        alts.append({
            "level": item["level"],
            "code": item["code"],
            "title": item["title"],
            "score": round(float(item["score"]), 3),
            "family_code": row.get("family_code"),
            "group_code": row.get("group_code"),
            "subdivision_code": row.get("subdivision_code"),
            "division_code": row.get("division_code"),
        })
        if len(alts) >= limit:
            break
    return alts


def _score_pool(
    level_index, normalized, qset, shortlist, bm25_raw, max_bm25, semantic_scores,
    context_tokens, use_context, phrase_raw=None, max_phrase=0.0,
):
    pool = [idx for idx, _hits in shortlist]
    if not pool:
        return []
    phrase_raw = phrase_raw or {}
    hit_map = {idx: hits for idx, hits in shortlist}
    rerank_scores, rerank_name = _batch_rerank(normalized, qset, pool, level_index)
    scored = []
    for idx, rerank in zip(pool, rerank_scores):
        doc = level_index["docs"][idx]
        level = doc.get("level") or "occupation"
        hits = hit_map.get(idx, [])
        fuzzy = next((hit["score"] for hit in hits if hit["method"] == "fuzzy"), None)
        if fuzzy is None:
            fuzzy = _fuzzy(normalized, doc["norm_title"])
        bm25 = (bm25_raw.get(idx, 0.0) / max_bm25) if max_bm25 else 0.0
        phrase_bm25 = (phrase_raw.get(idx, 0.0) / max_phrase) if max_phrase else 0.0
        lexical = max(fuzzy, bm25, phrase_bm25)
        alignment = _phrase_alignment_score(normalized, doc.get("norm_title") or "")
        # Phrase alignment reranks the fused shortlist. It does not vote in RRF.
        if rerank_name == "cross_encoder":
            rerank_signal = (0.7 * rerank) + (0.3 * alignment)
        else:
            rerank_signal = max(rerank, alignment)
        semantic = semantic_scores.get(idx, 0.0)
        # A shared word inside a different title is weak. Down-weight it when
        # the ordered query is not actually present.
        if len(qset) >= 2 and alignment < 0.85 and qset:
            recall = len(qset & doc["title_tokens"]) / len(qset)
            # Partial overlap only. A paraphrase with no shared words keeps its semantic score.
            if 0 < recall < 1.0:
                semantic *= recall
                rerank_signal *= recall
                lexical = max(bm25, phrase_bm25, min(fuzzy, recall))
        alias_signal = 1.0 if any(hit["method"] == "alias" for hit in hits) else 0.0
        hierarchy = _hierarchy_consistency(qset, doc)
        context_score = _f1(
            context_tokens,
            doc["title_tokens"] | doc["family_tokens"] | doc["group_tokens"] | doc["subdivision_tokens"] | doc["division_tokens"],
        ) if use_context else 0.0
        signals = {
            "semantic": semantic,
            "rerank": rerank_signal,
            "lexical": lexical,
            "alias": alias_signal,
            "context": context_score,
            "hierarchy": hierarchy,
        }
        score = _combine(signals, use_context=use_context, use_hierarchy=True, level=level)
        title_tokens = doc["title_tokens"]
        if level == "occupation" and qset and qset <= title_tokens:
            score = min(1.0, score + 0.04)
        elif qset and title_tokens and title_tokens <= qset:
            score = min(1.0, score + 0.04)
        if fuzzy >= 0.96:
            score = max(score, 0.93)
        methods = []
        for hit in hits:
            if hit["method"] not in methods:
                methods.append(hit["method"])
        if rerank_name not in methods:
            methods.append(rerank_name)
        if alignment >= 0.85 and "phrase_alignment" not in methods:
            methods.append("phrase_alignment")
        scored.append({
            "level": level,
            "code": doc.get("code") or doc.get("nco_code"),
            "title": doc.get("title"),
            "score": score,
            "lexical": lexical,
            "semantic": semantic,
            "fuzzy": fuzzy,
            "methods": methods,
            "doc": doc,
            "evidence": _title_evidence(qset, title_tokens),
        })
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored


def _embedding_supported(level, evidence, score, semantic) -> bool:
    """Hierarchy-only. A strong embedding hit still needs some title evidence."""
    if level == "occupation":
        return False
    if semantic < _REVIEW_EMBED_FLOOR or score < 0.55:
        return False
    if evidence.get("token_exact"):
        return True
    # Extra content words mean a narrower class than the input named.
    extras = set(evidence.get("extra") or ())
    if extras and not extras <= _STRUCTURAL_EXTRA:
        return False
    if evidence.get("distinctive") and (
        evidence.get("query_subset") or evidence.get("recall", 0.0) >= 0.5
    ):
        return True
    return False


def _supported_groups(occupation_scored, hierarchy_scored):
    grouped = {level: [] for level in _LEVELS}
    for item in occupation_scored:
        if _lexically_supported("occupation", item["evidence"], item["score"]):
            grouped["occupation"].append(item)
    for item in hierarchy_scored:
        level = item["level"]
        if level not in grouped:
            continue
        if _lexically_supported(level, item["evidence"], item["score"]) or _embedding_supported(
            level, item["evidence"], item["score"], item.get("semantic", 0.0),
        ):
            grouped[level].append(item)
    for level in _LEVELS:
        if grouped[level]:
            grouped[level].sort(key=lambda item: item["score"], reverse=True)
            return level, grouped[level]
    return None, []


def _status_for_group(level, group):
    best = group[0]
    second = group[1]["score"] if len(group) > 1 else 0.0
    margin = best["score"] - second
    token_exact = best["evidence"]["token_exact"]
    separated = margin >= _MARGIN
    if level == "occupation":
        if best["score"] >= _AUTO_SCORE and separated:
            return "auto_matched", _LEVEL_REASON["occupation"]
        if token_exact and separated and best["score"] >= 0.80:
            return "auto_matched", _LEVEL_REASON["occupation"]
        return "needs_review", "More than one occupation is plausible, so the code is not assigned automatically."
    if token_exact and separated and best["score"] >= 0.60:
        return "auto_matched", _LEVEL_REASON[level]
    if best["score"] >= _LEVEL_AUTO[level] and separated:
        return "auto_matched", _LEVEL_REASON[level]
    return (
        "needs_review",
        f"The {level} is the most specific classification with independent evidence, but it is not separated enough to assign automatically.",
    )


def _weak_occupation(item) -> bool:
    """A shortlist row with no lexical, fuzzy, or semantic support."""
    return (
        item["lexical"] < _UNMATCHED_LEXICAL
        and item["semantic"] < 0.55
        and item["score"] < _REVIEW_SCORE
        and item["fuzzy"] < 0.55
    )


def _exact_hierarchy_node(index, normalized):
    hierarchy = index.get("hierarchy") or {}
    ids = list(dict.fromkeys((hierarchy.get("by_title") or {}).get(normalized, ())))
    if not ids:
        return None
    nodes = [hierarchy["docs"][idx] for idx in ids]
    for level in ("family", "group", "subdivision", "division"):
        found = [node for node in nodes if node["level"] == level]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            return None
    return None


def _ensure_hierarchy_embeddings(hierarchy):
    """Lazy-fill hierarchy vectors when a local model is configured after index build."""
    if hierarchy is None or hierarchy.get("embeddings") is not None:
        return
    docs = hierarchy.get("docs") or []
    embedder = _load_embedder()
    if embedder is None or not docs:
        return
    try:
        texts = [d.get("search_text") or d.get("title") or "" for d in docs]
        hierarchy["embeddings"] = embedder.encode(
            texts, normalize_embeddings=True, show_progress_bar=False,
        )
    except Exception:
        hierarchy["embeddings"] = None


def _hierarchy_level_code_map(hierarchy):
    mapping = hierarchy.get("by_level_code")
    if mapping is not None:
        return mapping
    mapping = {
        (doc["level"], doc["code"]): idx
        for idx, doc in enumerate(hierarchy.get("docs") or [])
    }
    hierarchy["by_level_code"] = mapping
    return mapping


def _parent_hierarchy_idxs(occupation_scored, hierarchy):
    """Parents of the top occupation hits. Wrong tops still contribute several paths."""
    lookup = _hierarchy_level_code_map(hierarchy)
    idxs = []
    for item in occupation_scored[:_REVIEW_OCC_PARENTS]:
        row = (item.get("doc") or {}).get("row") or {}
        for level in ("family", "group", "subdivision", "division"):
            code = str(row.get(f"{level}_code") or "").strip()
            if not code:
                continue
            idx = lookup.get((level, code))
            if idx is not None:
                idxs.append(idx)
    return idxs


def _hierarchy_review_idxs(occupation_scored, hierarchy_scored, hierarchy, normalized, query_tokens):
    """Mixed hierarchy pool for medium/low confidence: parents + shortlist + neighbours."""
    lookup = _hierarchy_level_code_map(hierarchy)
    idxs = []
    idxs.extend(_parent_hierarchy_idxs(occupation_scored, hierarchy))
    for item in hierarchy_scored:
        idx = lookup.get((item["level"], item["code"]))
        if idx is not None:
            idxs.append(idx)
    _ensure_hierarchy_embeddings(hierarchy)
    semantic_hits, _name = _semantic_hits(
        hierarchy, normalized, query_tokens, _REVIEW_HIERARCHY_K,
    )
    for idx, _score in semantic_hits:
        idxs.append(idx)
    return list(dict.fromkeys(idxs))[:_REVIEW_HIERARCHY_K]


def _hierarchy_review_refresh(
    hierarchy,
    normalized,
    query_tokens,
    qset,
    occupation_scored,
    hierarchy_scored,
    context_tokens,
    use_context,
):
    """Rescore a mixed hierarchy pool with embeddings (or TF-IDF) for review rows."""
    if not hierarchy or not hierarchy.get("docs"):
        return hierarchy_scored
    idxs = _hierarchy_review_idxs(
        occupation_scored, hierarchy_scored, hierarchy, normalized, query_tokens,
    )
    if not idxs:
        return hierarchy_scored

    _ensure_hierarchy_embeddings(hierarchy)
    semantic_scores = {}
    semantic_name = "tfidf"
    embeddings = hierarchy.get("embeddings")
    embedder = _load_embedder()
    if embeddings is not None and embedder is not None:
        try:
            query = _cached_query_embedding(hierarchy, embedder, normalized)
            for idx, score in _dense_selected(query, embeddings, idxs):
                semantic_scores[idx] = score
            semantic_name = "embedding"
        except Exception:
            semantic_scores = {}
    if not semantic_scores:
        query = _cached_query_tfidf(hierarchy, query_tokens, normalized)
        for idx in idxs:
            semantic_scores[idx] = max(0.0, _cosine_sparse(query, hierarchy["tfidf"][idx]))
        semantic_name = "tfidf"

    shortlist = []
    for rank, idx in enumerate(idxs, start=1):
        shortlist.append((
            idx,
            [{
                "method": "hierarchy_review",
                "rank": rank,
                "score": float(semantic_scores.get(idx, 0.0)),
            }],
        ))

    bm25_raw = hierarchy["bm25"].scores(query_tokens)
    max_bm25 = max((bm25_raw.get(idx, 0.0) for idx in idxs), default=0.0)
    phrase_raw = {}
    max_phrase = 0.0
    phrase_index = hierarchy.get("phrase_bm25")
    phrase_query = _phrase_features(query_tokens)
    if phrase_index is not None and phrase_query:
        phrase_raw = phrase_index.scores(phrase_query)
        max_phrase = max((phrase_raw.get(idx, 0.0) for idx in idxs), default=0.0)

    refreshed = _score_pool(
        hierarchy, normalized, qset, shortlist, bm25_raw, max_bm25, semantic_scores,
        context_tokens, use_context, phrase_raw, max_phrase,
    )
    for item in refreshed:
        if semantic_name not in item["methods"]:
            item["methods"].append(semantic_name)
        if "hierarchy_review" not in item["methods"]:
            item["methods"].append("hierarchy_review")
        # A strong hierarchy embedding is review evidence even when lexical overlap is thin.
        sem = item.get("semantic", 0.0)
        if sem >= _REVIEW_EMBED_FLOOR:
            item["score"] = max(item["score"], min(0.89, 0.45 + 0.5 * sem))

    by_key = {}
    for item in hierarchy_scored + refreshed:
        key = (item["level"], item["code"])
        prev = by_key.get(key)
        if prev is None or item["score"] > prev["score"]:
            by_key[key] = item
    return sorted(by_key.values(), key=lambda item: item["score"], reverse=True)


def _decide_from_pools(
    occupation_scored,
    hierarchy_scored,
    *,
    normalized,
    source_value,
):
    """Pick a result from scored occupation and hierarchy pools."""
    combined = occupation_scored + hierarchy_scored
    level, group = _supported_groups(occupation_scored, hierarchy_scored)
    if level is not None:
        best = group[0]
        status, reason = _status_for_group(level, group)
        result = _result_from_doc(
            best["doc"],
            status=status,
            score=best["score"],
            methods=best["methods"],
            reason=reason,
            normalized=normalized,
            source_value=source_value,
            alternatives=_mixed_alternatives(combined, best),
        )
        if status == "needs_review":
            result["needs_llm"] = True
        return result

    if not occupation_scored and not hierarchy_scored:
        return _unmatched(
            normalized,
            source_value,
            "No classification in the registry shares terms with this value.",
        )

    best_occ = next((item for item in occupation_scored if not _weak_occupation(item)), None)
    phrase_hierarchy = [
        item for item in hierarchy_scored
        if _phrase_alignment_score(normalized, item["doc"].get("norm_title") or "") >= 0.85
    ]
    alternatives = _mixed_alternatives(combined, None)
    if phrase_hierarchy and (best_occ is None or phrase_hierarchy[0]["score"] >= best_occ["score"]):
        best = phrase_hierarchy[0]
        result = _result_from_doc(
            best["doc"],
            status="needs_review",
            score=best["score"],
            methods=best["methods"],
            reason="The input appears in order inside this title, but the title adds words the input does not name, so the code is not assigned automatically.",
            normalized=normalized,
            source_value=source_value,
            alternatives=_mixed_alternatives(combined, best),
        )
        result["needs_llm"] = True
        return result

    strong_hierarchy = [
        item for item in hierarchy_scored
        if item.get("semantic", 0.0) >= _REVIEW_EMBED_FLOOR
    ]
    # Prefer the deepest level when embedding scores are tied.
    _depth = {level: i for i, level in enumerate(_LEVELS)}
    strong_hierarchy.sort(
        key=lambda item: (
            item.get("semantic", 0.0),
            item["score"],
            -_depth.get(item["level"], 99),
        ),
        reverse=True,
    )
    occupation_has_strong_semantic = (
        best_occ is not None
        and best_occ.get("semantic", 0.0) >= _REVIEW_EMBED_FLOOR
        and not _weak_occupation(best_occ)
    )
    # Hierarchy embedding may win only when the occupation hit is weak or absent.
    if strong_hierarchy and not occupation_has_strong_semantic and (
        best_occ is None
        or _weak_occupation(best_occ)
        or (
            strong_hierarchy[0].get("semantic", 0.0) >= best_occ.get("semantic", 0.0) + 0.08
            and strong_hierarchy[0]["score"] >= best_occ["score"]
        )
    ):
        best = strong_hierarchy[0]
        result = _result_from_doc(
            best["doc"],
            status="needs_review",
            score=best["score"],
            methods=best["methods"],
            reason="A broader classification is a closer semantic match than any occupation, but it is not assigned automatically.",
            normalized=normalized,
            source_value=source_value,
            alternatives=_mixed_alternatives(combined, best),
        )
        result["needs_llm"] = True
        return result

    if best_occ is None:
        return _unmatched(
            normalized,
            source_value,
            "No classification in the registry is close enough to assign a code.",
            alternatives=alternatives,
        )

    result = _result_from_doc(
        best_occ["doc"],
        status="needs_review",
        score=best_occ["score"],
        methods=best_occ["methods"],
        reason="The closest occupation is below the evidence bar for automatic assignment, and no broader title is independently supported.",
        normalized=normalized,
        source_value=source_value,
        alternatives=_mixed_alternatives(combined, best_occ),
    )
    result["needs_llm"] = True
    return result


def _unmatched(normalized, source_value, reason, alternatives=None):
    return {
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
        "confidence": "low",
        "auto_fill": False,
        "needs_manual_review": True,
        "source": "nco_pipeline",
        "status": "unmatched",
        "matching_method": [],
        "reason": reason,
        "normalized_value": normalized,
        "source_value": source_value,
        "alternatives": alternatives or [],
        "needs_llm": False,
    }


def classify_occupation(text, index, context=None):
    """Assign the most specific NCO level that the input itself supports."""
    source_value = str(text or "").strip()
    normalized = expand_abbreviations(normalize_text(source_value))
    if not normalized or not index or not index.get("docs"):
        return None

    exact_ids = list(dict.fromkeys(index["by_title"].get(normalized, ())))
    if len(exact_ids) == 1:
        doc = index["docs"][exact_ids[0]]
        return _result_from_doc(
            doc,
            status="exact_match",
            score=1.0,
            methods=["exact"],
            reason="Normalized text matches one official occupation title.",
            normalized=normalized,
            source_value=source_value,
            alternatives=[],
        )

    alias_ids = list(dict.fromkeys(index["alias_to_idx"].get(normalized, ())))
    if len(alias_ids) == 1 and not exact_ids:
        doc = index["docs"][alias_ids[0]]
        return _result_from_doc(
            doc,
            status="alias_match",
            score=0.98,
            methods=["alias"],
            reason="Normalized text matches one approved occupation alias.",
            normalized=normalized,
            source_value=source_value,
            alternatives=[],
        )

    hierarchy_exact = _exact_hierarchy_node(index, normalized)
    if hierarchy_exact is not None:
        level = hierarchy_exact["level"]
        return _result_from_doc(
            hierarchy_exact,
            status="exact_match",
            score=1.0,
            methods=["exact"],
            reason=f"Normalized text matches one official {level} title.",
            normalized=normalized,
            source_value=source_value,
            alternatives=[],
        )

    query_tokens = _tokens(normalized)
    qset = set(query_tokens)
    context_text = " ".join(
        str((context or {}).get(key) or "")
        for key in ("column", "table_heading", "table_title")
    )
    context_tokens = set(_tokens(
        expand_abbreviations(normalize_text(context_text)),
        classification_sensitive=False,
    ))
    use_context = bool(context_tokens)

    shortlist, bm25_raw, max_bm25, semantic_scores, _semantic_name, phrase_raw, max_phrase = _retrieve(
        index, normalized, query_tokens,
    )
    occupation_scored = _score_pool(
        index, normalized, qset, shortlist, bm25_raw, max_bm25, semantic_scores,
        context_tokens, use_context, phrase_raw, max_phrase,
    )
    hierarchy = index.get("hierarchy")
    hierarchy_scored = []
    if hierarchy and hierarchy.get("docs"):
        h_short, h_bm25, h_max, h_semantic, _h_name, h_phrase, h_max_phrase = _retrieve(
            hierarchy, normalized, query_tokens,
        )
        hierarchy_scored = _score_pool(
            hierarchy, normalized, qset, h_short, h_bm25, h_max, h_semantic,
            context_tokens, use_context, h_phrase, h_max_phrase,
        )

    result = _decide_from_pools(
        occupation_scored,
        hierarchy_scored,
        normalized=normalized,
        source_value=source_value,
    )
    # Medium/low confidence: refresh hierarchy from parents of the top
    # occupations and embedding neighbours, then decide again.
    if (
        result
        and result.get("status") in ("needs_review", "unmatched")
        and hierarchy
        and hierarchy.get("docs")
        and (occupation_scored or hierarchy_scored)
    ):
        refreshed = _hierarchy_review_refresh(
            hierarchy,
            normalized,
            query_tokens,
            qset,
            occupation_scored,
            hierarchy_scored,
            context_tokens,
            use_context,
        )
        if refreshed is not hierarchy_scored:
            reviewed = _decide_from_pools(
                occupation_scored,
                refreshed,
                normalized=normalized,
                source_value=source_value,
            )
            keep_occupation_embedding = (
                result.get("level") == "occupation"
                and reviewed
                and reviewed.get("level") not in (None, "occupation")
                and "embedding" in (result.get("matching_method") or [])
            )
            if reviewed and not keep_occupation_embedding and (
                reviewed.get("status") == "auto_matched"
                or (
                    reviewed.get("status") == "needs_review"
                    and reviewed.get("score", 0.0) >= result.get("score", 0.0)
                )
                or (
                    result.get("status") == "unmatched"
                    and reviewed.get("status") != "unmatched"
                )
            ):
                result = reviewed
            elif reviewed and result.get("status") in ("needs_review", "unmatched"):
                # Keep the first choice, but surface refreshed hierarchy alternatives.
                merged = _mixed_alternatives(
                    occupation_scored + refreshed,
                    {
                        "level": result.get("level"),
                        "code": result.get("code"),
                    },
                )
                result = dict(result)
                result["alternatives"] = merged
                if result.get("status") == "needs_review":
                    result["needs_llm"] = True
    return result


def rank_occupation(text, index, context=None):
    """Score one label. Returns the deepest supported NCO level."""
    return classify_occupation(text, index, context=context)


def ensure_enrichment_table(conn):
    """Approved alias rows. Empty until a steward validates them."""
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS nco_occupation_aliases (
                    normalized_alias TEXT NOT NULL,
                    nco_code TEXT NOT NULL,
                    alias_text TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'alias',
                    source TEXT NOT NULL DEFAULT 'curated',
                    PRIMARY KEY (normalized_alias, nco_code)
                )
                """
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def load_enrichment_aliases(conn):
    if conn is None:
        return []
    ensure_enrichment_table(conn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT normalized_alias, nco_code, alias_text, kind, source
                  FROM nco_occupation_aliases
                """
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []
