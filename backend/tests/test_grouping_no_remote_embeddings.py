"""Grouping must never call remote OpenAI embeddings; untitled stay singletons."""

from app.services.grouping.embeddings import embed_texts, suggest_untitled_merges
from app.services.grouping.pdf_grouping import propose_groups_from_table_dicts


def test_embed_texts_never_needs_api_key_and_returns_pseudo():
    vecs = embed_texts(["Birth rate urban", "Birth rate rural"], api_key="sk-fake")
    assert len(vecs) == 2
    assert len(vecs[0]) == len(vecs[1]) > 0


def test_untitled_stay_singletons_no_embed_merge():
    tables = [
        {"id": "a", "title": "", "domain": "health", "entity": "state", "table_type": "indicator"},
        {"id": "b", "title": "", "domain": "health", "entity": "state", "table_type": "indicator"},
        {"id": "c", "title": "Births URBAN", "domain": "health", "entity": "state", "table_type": "indicator"},
        {"id": "d", "title": "Births RURAL", "domain": "health", "entity": "state", "table_type": "indicator"},
    ]
    result = propose_groups_from_table_dicts(tables, api_key="ollama")
    assert "embed" not in (result.get("method") or "")
    untitled = [
        g for g in result["groups"]
        if (g.get("name") or "").startswith("Untitled (")
    ]
    assert len(untitled) == 2
    assert all(len(g["tables"]) == 1 for g in untitled)

    suggestions = result.get("suggested_merges") or []
    assert len(suggestions) == 1
    assert set(suggestions[0]["table_ids"]) == {"a", "b"}


def test_suggest_untitled_requires_all_cues():
    tables = [
        {"id": "a", "title": "", "domain": "health", "entity": "", "table_type": "indicator"},
        {"id": "b", "title": "", "domain": "health", "entity": "", "table_type": "indicator"},
    ]
    assert suggest_untitled_merges(tables) == []
