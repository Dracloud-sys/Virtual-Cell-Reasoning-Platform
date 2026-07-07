"""Tests for the natural-language reasoning layer (offline backend, hermetic)."""

from __future__ import annotations

import pytest

from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.sample import SampleDataSource
from virtualcell.reasoning.llm import AnthropicBackend, TemplateBackend, get_backend
from virtualcell.reasoning.qa import QuestionAnswerer


@pytest.fixture
def store() -> InMemoryKnowledgeStore:
    s = InMemoryKnowledgeStore()
    load_into(SampleDataSource(), s)
    return s


def test_answer_is_grounded_in_the_knowledge_base(store: InMemoryKnowledgeStore) -> None:
    qa = QuestionAnswerer(store, backend=TemplateBackend())
    result = qa.answer("What is TP53 and what does it do?")

    assert result.backend == "offline-template"
    assert result.grounded_entity_ids  # something was retrieved
    assert any("TP53" in eid or "P04637" in eid for eid in result.grounded_entity_ids)
    assert result.facts
    # Every fact is knowledge-base backed, hence established with a kb citation.
    assert all(f.tier == EvidenceTier.ESTABLISHED for f in result.facts)
    assert all(f.citation.startswith("kb:") for f in result.facts)
    # The offline answer surfaces the retrieved evidence.
    assert "kb:" in result.answer


def test_neighbor_context_is_included(store: InMemoryKnowledgeStore) -> None:
    qa = QuestionAnswerer(store, backend=TemplateBackend())
    result = qa.answer("MDM2")
    # At least one fact should express a graph connection (relational context).
    assert any("connected to" in f.statement for f in result.facts)


def test_no_match_returns_honest_answer(store: InMemoryKnowledgeStore) -> None:
    qa = QuestionAnswerer(store, backend=TemplateBackend())
    result = qa.answer("zzzz-nonexistent-entity")
    assert result.facts == []
    assert result.grounded_entity_ids == []
    assert "no grounded evidence" in result.answer.lower()


def test_backend_selection_falls_back_offline_without_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(get_backend(), TemplateBackend)


def test_backend_selection_uses_anthropic_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.setattr("virtualcell.reasoning.llm._anthropic_available", lambda: True)
    assert isinstance(get_backend(model="claude-sonnet-5"), AnthropicBackend)
