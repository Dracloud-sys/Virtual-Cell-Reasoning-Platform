"""Tests for the natural-language reasoning layer (offline backend, hermetic)."""

from __future__ import annotations

import pytest

from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import Gene, Interaction, Marker, RelationType
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.sample import SampleDataSource
from virtualcell.reasoning.llm import AnthropicBackend, TemplateBackend, get_backend
from virtualcell.reasoning.qa import UNREVIEWED_LABEL, QuestionAnswerer


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
    # Every fact is knowledge-base backed (kb citation), and direct facts are established.
    assert all(f.citation.startswith("kb:") for f in result.facts)
    assert any(f.tier == EvidenceTier.ESTABLISHED for f in result.facts)
    # The offline answer surfaces the retrieved evidence.
    assert "kb:" in result.answer


def test_multi_hop_mechanistic_paths_are_cited(store: InMemoryKnowledgeStore) -> None:
    qa = QuestionAnswerer(store, backend=TemplateBackend())
    result = qa.answer("MDM2")
    # Grounding now includes directed mechanistic paths, and a 2-hop inference is
    # honestly downgraded below established.
    assert any("->" in f.statement for f in result.facts)
    assert any(f.tier == EvidenceTier.HYPOTHESIS for f in result.facts)


def test_no_match_returns_honest_answer(store: InMemoryKnowledgeStore) -> None:
    qa = QuestionAnswerer(store, backend=TemplateBackend())
    result = qa.answer("zzzz-nonexistent-entity")
    assert result.facts == []
    assert result.grounded_entity_ids == []
    assert "no grounded evidence" in result.answer.lower()


# --- unreviewed evidence is classified before synthesis (PR10a) --------------


class _SpyBackend:
    """Captures the exact evidence block handed to the backend for synthesis."""

    name = "spy"

    def __init__(self) -> None:
        self.blocks: list[str] = []

    def answer(self, question: str, evidence: str) -> str:
        self.blocks.append(evidence)
        return "synthesized answer"


def _pending(store: InMemoryKnowledgeStore, entity_id: str, name: str) -> None:
    store.upsert(Marker(id=entity_id, name=name, properties={"review_status": "pending_review"}))


def test_unreviewed_node_is_never_grounded_as_established(store) -> None:
    # Direct QuestionAnswerer callers (the /reasoning/qa route, the CLI) must get the
    # same protection as the orchestrator: the cap lives in grounding, not in a caller.
    _pending(store, "lit:marker:tp53", "TP53")
    qa = QuestionAnswerer(store, backend=TemplateBackend())
    result = qa.answer("TP53")

    unreviewed = [f for f in result.facts if "lit:" in f.citation]
    assert unreviewed, "the pending-review node should still be retrieved, not hidden"
    assert all(f.tier is not EvidenceTier.ESTABLISHED for f in unreviewed)
    # It stays visible and is explicitly labelled rather than silently dropped.
    assert all(UNREVIEWED_LABEL in f.statement for f in unreviewed)
    # Curated evidence is unaffected.
    assert any(f.tier is EvidenceTier.ESTABLISHED for f in result.facts)


def test_backend_never_receives_unreviewed_evidence_as_established(store) -> None:
    _pending(store, "lit:marker:tp53", "TP53")
    spy = _SpyBackend()
    QuestionAnswerer(store, backend=spy).answer("TP53")

    assert spy.blocks, "the backend must have been asked to synthesize"
    offending = [
        line
        for line in spy.blocks[0].splitlines()
        if "lit:" in line and f"[{EvidenceTier.ESTABLISHED.value}]" in line
    ]
    assert not offending, f"unreviewed evidence sent as established: {offending}"


def test_ground_and_synthesize_compose_into_answer(store) -> None:
    # The split seam must be behaviour-preserving: answer() == ground() + synthesize().
    qa = QuestionAnswerer(store, backend=TemplateBackend())
    seeds = qa.retrieve("TP53")
    composed = qa.synthesize("TP53", qa.ground(seeds), [e.id for e in seeds])
    assert composed.model_dump() == qa.answer("TP53").model_dump()


def test_synthesize_without_facts_is_honest(store) -> None:
    qa = QuestionAnswerer(store, backend=TemplateBackend())
    result = qa.synthesize("anything", [], [])
    assert "no grounded evidence" in result.answer.lower()
    assert result.facts == []


def test_curated_only_graph_has_no_unreviewed_labelling(store) -> None:
    # Regression guard: the new rule must not touch a purely curated knowledge base.
    qa = QuestionAnswerer(store, backend=TemplateBackend())
    result = qa.answer("What is TP53 and what does it do?")
    assert all(UNREVIEWED_LABEL not in f.statement for f in result.facts)
    assert any(f.tier is EvidenceTier.ESTABLISHED for f in result.facts)


# --- namespace protection without a review_status marker (PR10a hardening) ---
#
# The two provisional-evidence signals are independent: a lit: node can reach the store
# with no review_status at all (fixture, migration, hand-built graph). Direct
# QuestionAnswerer callers — /reasoning/qa and the CLI — must still be protected.


@pytest.fixture
def mixed_store() -> InMemoryKnowledgeStore:
    """A curated gene, an unflagged lit: node, and a non-lit node flagged pending."""
    s = InMemoryKnowledgeStore()
    s.upsert(Gene(id="gene:TERT", name="TERT", symbol="TERT", description="Telomerase."))
    s.upsert(Marker(id="lit:marker:tert", name="TERT"))  # NO review_status
    s.upsert(
        Marker(
            id="marker:experimental",
            name="TERT",
            properties={"review_status": "pending_review"},  # not lit:, but pending
        )
    )
    s.add_interaction(
        Interaction(
            source_id="gene:TERT",
            target_id="lit:marker:tert",
            relation=RelationType.ASSOCIATED_WITH,
            confidence=0.9,
        )
    )
    return s


def _facts_citing(result, fragment: str):
    return [f for f in result.facts if fragment in f.citation]


def test_lit_node_without_review_status_is_weak_to_the_backend(mixed_store) -> None:
    spy = _SpyBackend()
    QuestionAnswerer(mixed_store, backend=spy).answer("TERT")

    assert spy.blocks, "the backend must have been asked to synthesize"
    offending = [
        line
        for line in spy.blocks[0].splitlines()
        if "lit:" in line and f"[{EvidenceTier.ESTABLISHED.value}]" in line
    ]
    assert not offending, f"unflagged lit: evidence sent as established: {offending}"


def test_lit_node_without_review_status_answer_has_no_established_line(mixed_store) -> None:
    result = QuestionAnswerer(mixed_store, backend=TemplateBackend()).answer("TERT")
    established_lit = [
        line
        for line in result.answer.splitlines()
        if "lit:" in line and f"[{EvidenceTier.ESTABLISHED.value}]" in line
    ]
    assert not established_lit
    assert "lit:" in result.answer  # still surfaced, just never as established


def test_path_anchored_to_unflagged_lit_node_is_weak(mixed_store) -> None:
    result = QuestionAnswerer(mixed_store, backend=TemplateBackend()).answer("TERT")
    paths = _facts_citing(result, "->")
    lit_paths = [f for f in paths if "lit:" in f.citation]
    assert lit_paths, "the curated seed should reach the lit: marker"
    assert all(f.tier is not EvidenceTier.ESTABLISHED for f in lit_paths)


def test_curated_node_without_review_status_stays_established(mixed_store) -> None:
    result = QuestionAnswerer(mixed_store, backend=TemplateBackend()).answer("TERT")
    curated = _facts_citing(result, "kb:gene:TERT")
    direct = [f for f in curated if "->" not in f.citation]
    assert direct and all(f.tier is EvidenceTier.ESTABLISHED for f in direct)


def test_non_lit_node_marked_pending_review_stays_weak(mixed_store) -> None:
    result = QuestionAnswerer(mixed_store, backend=TemplateBackend()).answer("TERT")
    pending = _facts_citing(result, "marker:experimental")
    assert pending, "the pending-review node should still be retrieved, not hidden"
    assert all(f.tier is not EvidenceTier.ESTABLISHED for f in pending)


def test_repeated_calls_never_upgrade_either_case(mixed_store) -> None:
    qa = QuestionAnswerer(mixed_store, backend=TemplateBackend())
    first, second = qa.answer("TERT"), qa.answer("TERT")

    assert first.answer == second.answer  # deterministic
    for result in (first, second):
        provisional = [
            f for f in result.facts if "lit:" in f.citation or "marker:experimental" in f.citation
        ]
        assert provisional
        assert all(f.tier is not EvidenceTier.ESTABLISHED for f in provisional)


def test_backend_selection_falls_back_offline_without_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(get_backend(), TemplateBackend)


def test_backend_selection_uses_anthropic_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.setattr("virtualcell.reasoning.llm._anthropic_available", lambda: True)
    assert isinstance(get_backend(model="claude-sonnet-5"), AnthropicBackend)
