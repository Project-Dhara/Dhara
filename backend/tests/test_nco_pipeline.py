"""Local NCO occupation pipeline: abbreviations, exact titles, and no forced codes."""
from __future__ import annotations

from app.services.classification.nco_pipeline import (
    _rrf_score,
    _tokens,
    build_index,
    expand_abbreviations,
    normalize_text,
    rank_occupation,
)


def _row(code, title, division="2", division_title="Professionals", family="2512", family_title="Software Developers"):
    return {
        "nco_code": code,
        "occupation_title": title,
        "division_code": division,
        "division_title": division_title,
        "subdivision_code": division + "5",
        "subdivision_title": division_title,
        "group_code": family[:3],
        "group_title": family_title,
        "family_code": family,
        "family_title": family_title,
    }


def test_abbreviation_expansion_keeps_seniority():
    expanded = expand_abbreviations(normalize_text("Sr. Software Engr."))
    assert expanded == "senior software engineer"
    assert expand_abbreviations(normalize_text("Asst. Accountant")) == "assistant accountant"


def test_exact_title_assigns_occupation_code():
    index = build_index([
        _row("2512.0100", "Software Developer"),
        _row("2512.0200", "Software Engineer"),
    ])
    result = rank_occupation("Software Developer", index)
    assert result["status"] == "exact_match"
    assert result["code"] == "2512.0100"
    assert result["auto_fill"] is True
    assert result["division_code"] == "2"


def test_approved_alias_is_not_a_related_job():
    rows = [
        _row("2512.0100", "Software Developer"),
        _row("2511.0100", "Data Scientist", family="2511", family_title="Systems Analysts"),
    ]
    index = build_index(rows, extra_aliases=[{
        "normalized_alias": "application developer",
        "nco_code": "2512.0100",
        "alias_text": "Application Developer",
    }])
    result = rank_occupation("Application Developer", index)
    assert result["status"] == "alias_match"
    assert result["code"] == "2512.0100"
    assert result["auto_fill"] is True


def test_embedding_retrieval_does_not_require_shared_tokens():
    """A paraphrase with no shared words can still enter the shortlist via embeddings."""
    import app.services.classification.nco_pipeline as pipe

    index = build_index([
        _row("2512.0100", "Software Developer"),
        _row(
            "2212.0100",
            "Cardiologist",
            family="2212",
            family_title="Medical Doctors",
        ),
    ])
    index["embeddings"] = [[1.0, 0.0], [0.0, 1.0]]
    calls = {"n": 0}

    class FakeEmbedder:
        def encode(self, texts, **kwargs):
            calls["n"] += 1
            return [[0.0, 1.0] for _ in texts]

    original = pipe._load_embedder
    pipe._load_embedder = lambda: FakeEmbedder()
    try:
        query = "Person responsible for diagnosing and treating diseases of the heart"
        result = rank_occupation(query, index)
        rank_occupation(query, index)
    finally:
        pipe._load_embedder = original

    assert result["code"] == "2212.0100"
    assert "embedding" in result["matching_method"]
    assert calls["n"] == 1


def test_cross_encoder_scores_the_shortlist_in_one_call():
    import app.services.classification.nco_pipeline as pipe

    index = build_index([
        _row("2512.0100", "Software Developer"),
        _row("2512.0200", "Software Engineer"),
        _row(
            "7411.0100",
            "Electrician",
            division="7",
            division_title="Craft and Related Trades Workers",
            family="7411",
            family_title="Electricians",
        ),
    ])
    seen = {}

    class FakeCross:
        def predict(self, pairs, batch_size=32, show_progress_bar=False):
            seen["pairs"] = list(pairs)
            seen["batch_size"] = batch_size
            return [0.2 for _ in pairs]

    original = pipe._load_cross_encoder
    pipe._load_cross_encoder = lambda: FakeCross()
    try:
        rank_occupation("senior software enginer", index)
    finally:
        pipe._load_cross_encoder = original

    assert seen["batch_size"] == 32
    assert len(seen["pairs"]) >= 2
    assert all(len(pair) == 2 for pair in seen["pairs"])


def test_classification_markers_stay_in_occupation_titles():
    assert normalize_text("Sales Workers, n.e.c.") == "sales workers nec"
    assert normalize_text("Sales Workers, Not Elsewhere Classified") == "sales workers nec"
    tokens = _tokens(normalize_text("Other Sales Support Workers, Not Elsewhere Classified"))
    assert tokens == ["other", "sale", "support", "worker", "nec"]
    assert "worker" in _tokens(normalize_text("Service Workers"))
    heading = _tokens(normalize_text("Workers by sector"), classification_sensitive=False)
    assert "worker" not in heading
    assert "sector" in heading

    index = build_index([
        _row("5223.0100", "Sales Workers", family="5223", family_title="Shop Salespersons"),
        _row("5223.9900", "Other Sales Workers", family="5223", family_title="Shop Salespersons"),
        _row("5222.0100", "Sales Workers, Not Elsewhere Classified", family="5222", family_title="Shop Supervisors"),
        _row("5222.0200", "Sales Support Workers", family="5222", family_title="Shop Supervisors"),
    ])
    assert rank_occupation("Other Sales Workers", index)["code"] == "5223.9900"
    assert rank_occupation("Sales Workers, n.e.c.", index)["code"] == "5222.0100"
    assert rank_occupation("Sales Support Workers", index)["code"] == "5222.0200"


def test_rrf_uses_every_rank():
    # Same method count. The steadier ranks outscore one best rank plus two weak ones.
    steady = [{"rank": 2}, {"rank": 2}, {"rank": 2}]
    uneven = [{"rank": 1}, {"rank": 10}, {"rank": 10}]
    assert _rrf_score(steady) > _rrf_score(uneven)


def test_semantic_fill_does_not_rescore_the_registry():
    import app.services.classification.nco_pipeline as pipe

    index = build_index([
        _row("2512.0100", "Software Developer"),
        _row("2512.0200", "Software Engineer"),
        _row("7411.0100", "Electrician", division="7", division_title="Craft and Related Trades Workers", family="7411", family_title="Electricians"),
    ])
    index["embeddings"] = [[1.0, 0.0], [0.2, 0.8], [0.0, 1.0]]
    seen = []
    original_top = pipe._top_dense
    original_loader = pipe._load_embedder

    def wrapped(query, matrix, k):
        seen.append(k)
        return original_top(query, matrix, k)

    class FakeEmbedder:
        def encode(self, texts, **kwargs):
            return [[0.0, 1.0] for _ in texts]

    pipe._top_dense = wrapped
    pipe._load_embedder = lambda: FakeEmbedder()
    try:
        rank_occupation("heart specialist", index)
    finally:
        pipe._top_dense = original_top
        pipe._load_embedder = original_loader
        pipe._EMBEDDER = None
        pipe._EMBEDDER_TRIED = False

    assert seen
    assert max(seen) == pipe._SEMANTIC_K
    assert pipe._SEMANTIC_K < 100


def test_phrase_alignment_requires_ordered_tokens():
    from app.services.classification.nco_pipeline import _phrase_alignment_score, _phrase_features, _tokens

    assert _phrase_features(_tokens("personal assistant")) == ["personal_assistant"]
    assert _phrase_alignment_score("Personal Assistant", "Personal Assistant") == 1.0
    assert _phrase_alignment_score(
        "Personal Assistant", "Private Secretary Personal Assistant",
    ) == 0.85
    assert _phrase_alignment_score("Assistant", "Assistant Beautician") == 0.45
    assert _phrase_alignment_score("Personal Assistant", "Assistant") == 0.0


def test_ordered_phrase_outranks_a_shared_word():
    index = build_index([
        _row("4120.0100", "Private Secretary Personal Assistant", division="4", division_title="Clerks", family="4120", family_title="Secretaries"),
        _row("5142.0101", "Assistant Beautician", division="5", division_title="Service and Sales Workers", family="5142", family_title="Beauticians and Related Workers"),
    ])
    result = rank_occupation("Personal Assistant", index)
    assert result["code"] == "4120.0100"
    assert "phrase_alignment" in result["matching_method"] or "phrase_bm25" in result["matching_method"]


def test_chef_uses_the_family_when_no_occupation_is_named():
    index = build_index([
        _row(
            "1120.3100",
            "Executive Chef",
            division="1",
            division_title="Managers",
            family="1120",
            family_title="Managing Directors and Chief Executives",
        ),
        _row(
            "3434.0100",
            "Head Cook",
            division="3",
            division_title="Technicians and Associate Professionals",
            family="3434",
            family_title="Chefs",
        ),
    ])
    chef = rank_occupation("Chef", index)
    assert chef["level"] == "family"
    assert chef["code"] == "3434"
    assert chef["occupation_code"] is None
    assert chef["nco_code"] is None
    assert any(alt["level"] == "occupation" for alt in chef["alternatives"])

    named = rank_occupation("Executive Chef", index)
    assert named["level"] == "occupation"
    assert named["code"] == "1120.3100"
    assert named["occupation_code"] == "1120.3100"


def test_unrelated_text_is_not_forced():
    index = build_index([
        _row("2512.0100", "Software Developer"),
        _row("7411.0100", "Electrician", division="7", division_title="Craft and Related Trades Workers", family="7411", family_title="Electricians"),
    ])
    result = rank_occupation("zzzz qq qq banana", index)
    assert result["status"] == "unmatched"
    assert result["code"] is None
    assert result["auto_fill"] is False
