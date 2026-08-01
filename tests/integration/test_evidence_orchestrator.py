"""Integration tests for the PR9 evidence-query orchestrator.

No network and no LLM API: a fake provider serves the sample JATS, and the KB path uses
the deterministic template backend. Exercises the whole KB-miss -> literature ->
verification -> canonical -> weak-ingestion flow, and the tier discipline that keeps
literature evidence weak.
"""

from __future__ import annotations

from datetime import UTC, datetime

from virtualcell.agents.literature_discovery.agent import LiteratureDiscoveryAgent
from virtualcell.core.agent import AgentContext
from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.literature.contracts import (
    ArticleIdentifier,
    ArticleRecord,
    LiteratureSearchResult,
    ProviderProvenance,
)
from virtualcell.orchestration.query import (
    EvidenceQueryOrchestrator,
    QuerySource,
    _derive_targets,
)


class _FakeProvider:
    name = "fake"

    def __init__(self, *, articles: int = 1) -> None:
        self._articles = articles

    def search(self, query) -> LiteratureSearchResult:
        records = [
            ArticleRecord(
                identifiers=ArticleIdentifier(pmcid="PMC1", pmid="1", provider_id="PMC1"),
                title="TERT in bovine preadipocyte",
                abstract="TERT",
                is_open_access=True,
                has_full_text=True,
                provider="fake",
                retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
            )
        ][: self._articles]
        return LiteratureSearchResult(
            provenance=ProviderProvenance(
                provider="fake",
                query_sent="q",
                retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
                hit_count=len(records),
            ),
            articles=records,
        )

    def fetch_record(self, identifier):  # pragma: no cover - unused
        raise NotImplementedError

    def fetch_open_full_text(self, identifier):
        return self._xml

    _xml = ""


def _lit_agent(jats_xml, *, articles: int = 1) -> LiteratureDiscoveryAgent:
    provider = _FakeProvider(articles=articles)
    provider._xml = jats_xml
    return LiteratureDiscoveryAgent(AgentContext(services={"literature_provider": provider}))


def _seeded_store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    source = ImmortalizationSeedSource()
    for entity in source.entities():
        store.upsert(entity)
    for interaction in source.interactions():
        store.add_interaction(interaction)
    return store


# --- target derivation -------------------------------------------------------


def test_derive_targets_is_conservative() -> None:
    assert _derive_targets("What is known about TERT and CDK4 in 2024?") == ["TERT", "CDK4"]
    assert _derive_targets("how does telomere maintenance work") == []  # no symbols
    assert _derive_targets("p16 and p21 status") == ["p16", "p21"]


# --- KB hit ------------------------------------------------------------------


async def test_kb_hit_answers_from_knowledge_base(jats_xml) -> None:
    store = _seeded_store()
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    result = await orch.answer("What is TERT?")
    assert result.source is QuerySource.KNOWLEDGE_BASE
    assert result.kb_facts and result.kb_entity_ids
    assert not result.literature_consulted
    # A KB hit never reaches for literature, so no lit: nodes are added.
    assert not any(e.id.startswith("lit:") for e in store.all_entities())


# --- KB miss, no literature --------------------------------------------------


async def test_kb_miss_without_literature_is_no_evidence() -> None:
    orch = EvidenceQueryOrchestrator(InMemoryKnowledgeStore())  # no agent
    result = await orch.answer("What is XYZ123nonexistent?")
    assert result.source is QuerySource.NO_EVIDENCE
    assert not result.literature_consulted


async def test_allow_literature_false_disables_augmentation(jats_xml) -> None:
    orch = EvidenceQueryOrchestrator(
        InMemoryKnowledgeStore(), literature_agent=_lit_agent(jats_xml)
    )
    result = await orch.answer("known about TERT?", allow_literature=False)
    assert result.source is QuerySource.NO_EVIDENCE
    assert not result.literature_consulted


# --- KB miss, literature augmentation ----------------------------------------


async def test_kb_miss_augments_with_weak_literature_evidence(jats_xml) -> None:
    store = InMemoryKnowledgeStore()
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    result = await orch.answer("known about TERT?", target_measurements=["TERT", "CDK4"])

    assert result.source is QuerySource.LITERATURE_AUGMENTED
    assert result.literature_consulted
    assert result.literature_facts and result.ingestion is not None
    # The literature evidence was ingested into the same store, namespaced and weak.
    assert any(e.id.startswith("lit:") for e in store.all_entities())
    assert "pending review" in result.answer.lower()


async def test_literature_evidence_is_never_established(jats_xml) -> None:
    store = InMemoryKnowledgeStore()
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    result = await orch.answer("known about TERT?", target_measurements=["TERT"])
    assert result.literature_facts
    # The domain's tier discipline: a single literature measurement is weak, never a fact.
    assert all(f.tier is EvidenceTier.HYPOTHESIS for f in result.literature_facts)
    assert all(f.tier is not EvidenceTier.ESTABLISHED for f in result.literature_facts)


async def test_literature_facts_carry_provenance(jats_xml) -> None:
    store = InMemoryKnowledgeStore()
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    result = await orch.answer("known about TERT?", target_measurements=["TERT"])
    assert all(f.citation.startswith("lit:") for f in result.literature_facts)
    assert all("source" in f.statement.lower() for f in result.literature_facts)


async def test_zero_result_literature_is_consulted_but_no_evidence(jats_xml) -> None:
    store = InMemoryKnowledgeStore()
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml, articles=0))
    result = await orch.answer("known about TERT?", target_measurements=["TERT"])
    assert result.source is QuerySource.NO_EVIDENCE
    assert result.literature_consulted  # we did look
    assert not any(e.id.startswith("lit:") for e in store.all_entities())


async def test_repeat_query_keeps_prior_literature_evidence_weak(jats_xml) -> None:
    # After literature augments the store, a repeat query must NOT present that evidence
    # as an established KB fact — it stays weak and is not re-discovered.
    store = InMemoryKnowledgeStore()
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    await orch.answer("known about TERT?", target_measurements=["TERT"])
    repeat = await orch.answer("known about TERT?", target_measurements=["TERT"])
    assert repeat.source is QuerySource.LITERATURE_AUGMENTED
    assert not repeat.literature_consulted  # surfaced from the store, not re-discovered
    assert all(f.tier is EvidenceTier.HYPOTHESIS for f in repeat.literature_facts)


async def test_curated_hit_downgrades_any_matched_literature_nodes(jats_xml) -> None:
    # A curated KB entity answers the question, but ingested lit: nodes for the same
    # symbol must be surfaced separately as weak, never inheriting the established tier.
    store = _seeded_store()  # curated gene:TERT etc.
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    # First, a KB miss on a lit-only symbol would ingest; instead pre-ingest via a miss
    # path on an empty store is unnecessary — ingest directly through a prior augment.
    empty = InMemoryKnowledgeStore()
    await EvidenceQueryOrchestrator(empty, literature_agent=_lit_agent(jats_xml)).answer(
        "known about TERT?", target_measurements=["TERT"]
    )
    for entity in empty.all_entities():
        if entity.id.startswith("lit:"):
            store.upsert(entity)
    for interaction in empty.all_interactions():
        store.add_interaction(interaction)

    result = await orch.answer("What is TERT?")
    assert result.source is QuerySource.KNOWLEDGE_BASE
    # Curated facts remain (at least one established), and none of them cite a lit: node.
    assert any(f.tier is EvidenceTier.ESTABLISHED for f in result.kb_facts)
    assert all("lit:" not in f.citation for f in result.kb_facts)
    # Any literature fact pulled in is weak, never established.
    assert all(f.tier is EvidenceTier.HYPOTHESIS for f in result.literature_facts)


async def test_augmentation_is_deterministic_and_idempotent(jats_xml) -> None:
    store = InMemoryKnowledgeStore()
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    first = await orch.answer("known about TERT?", target_measurements=["TERT"])
    entities_after_first = {e.id for e in store.all_entities()}
    interactions_after_first = len(store.all_interactions())

    second = await orch.answer("known about TERT?", target_measurements=["TERT"])
    assert [f.citation for f in first.literature_facts] == [
        f.citation for f in second.literature_facts
    ]
    # Re-ingesting the same evidence adds nothing new.
    assert {e.id for e in store.all_entities()} == entities_after_first
    assert len(store.all_interactions()) == interactions_after_first


# --- PR9-c: literature markers resolved onto curated nodes -------------------


async def test_augmentation_resolves_markers_onto_curated_nodes(jats_xml) -> None:
    # The question does not name a curated node (a miss), but the target does: the ingested
    # lit:marker is bridged to the curated gene it names.
    store = _seeded_store()  # curated gene:TERT exists
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    result = await orch.answer("summarize any recent measurements", target_measurements=["TERT"])
    assert result.source is QuerySource.LITERATURE_AUGMENTED
    assert result.resolution is not None
    assert ("lit:marker:tert", "gene:TERT") in [tuple(r) for r in result.resolution.resolved]
    # The curated gene now reaches the literature marker (a weak bridge, not a merge).
    assert "lit:marker:tert" in {n.id for n in store.neighbors("gene:TERT")}
    assert store.get("gene:TERT") is not None and store.get("lit:marker:tert") is not None


# --- PR10a: classification precedes synthesis --------------------------------


class _SpyBackend:
    """Captures the exact evidence block handed to the backend for synthesis."""

    name = "spy"

    def __init__(self) -> None:
        self.blocks: list[str] = []

    def answer(self, question: str, evidence: str) -> str:
        self.blocks.append(evidence)
        return "synthesized answer"


_ESTABLISHED_LABEL = f"[{EvidenceTier.ESTABLISHED.value}]"


def _established_lit_lines(text: str) -> list[str]:
    """Lines that present a lit: citation/path under an established label."""
    return [line for line in text.splitlines() if "lit:" in line and _ESTABLISHED_LABEL in line]


async def _store_with_resolved_literature(jats_xml) -> InMemoryKnowledgeStore:
    """A curated seed graph that has also ingested + resolved TERT literature evidence."""
    store = _seeded_store()
    await EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml)).answer(
        "summarize any recent measurements", target_measurements=["TERT"]
    )
    assert any(e.id.startswith("lit:") for e in store.all_entities())
    return store


async def test_backend_never_receives_literature_as_established(jats_xml) -> None:
    # The blocker: classification used to happen *after* synthesis, so the backend saw
    # lit: evidence labelled established. Prove it now cannot.
    store = await _store_with_resolved_literature(jats_xml)
    spy = _SpyBackend()
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml), backend=spy)
    result = await orch.answer("What is TERT?")

    assert result.source is QuerySource.KNOWLEDGE_BASE
    assert spy.blocks, "the backend must have been asked to synthesize"
    block = spy.blocks[0]
    assert "lit:" in block, "literature evidence must stay visible, not be hidden"
    assert not _established_lit_lines(block), (
        f"literature sent to the backend as established: {_established_lit_lines(block)}"
    )


async def test_answer_never_renders_literature_under_an_established_label(jats_xml) -> None:
    store = await _store_with_resolved_literature(jats_xml)
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    result = await orch.answer("What is TERT?")

    assert not _established_lit_lines(result.answer)
    # Still present, and clearly marked as weak/pending rather than dropped.
    assert "lit:" in result.answer
    assert "pending review" in result.answer.lower()


async def test_curated_hit_keeps_curated_established_and_literature_weak(jats_xml) -> None:
    store = await _store_with_resolved_literature(jats_xml)
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    result = await orch.answer("What is TERT?")

    # The curated TERT gene remains established evidence...
    curated = [f for f in result.kb_facts if "gene:TERT" in f.citation]
    assert any(f.tier is EvidenceTier.ESTABLISHED for f in curated)
    # ...while the resolved literature measurement stays a hypothesis.
    assert result.literature_facts
    assert all(f.tier is EvidenceTier.HYPOTHESIS for f in result.literature_facts)
    assert all("lit:" not in f.citation for f in result.kb_facts)


async def test_answer_and_structured_facts_share_one_classification(jats_xml) -> None:
    store = await _store_with_resolved_literature(jats_xml)
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    result = await orch.answer("What is TERT?")

    # Every fact reported structurally is rendered in the answer at the same tier.
    for fact in [*result.kb_facts, *result.literature_facts]:
        assert f"[{fact.tier.value}] {fact.statement} [{fact.citation}]" in result.answer


async def test_literature_only_answer_stays_weak_and_pending(jats_xml) -> None:
    store = InMemoryKnowledgeStore()  # no curated knowledge at all
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    result = await orch.answer("known about TERT?", target_measurements=["TERT"])

    assert result.source is QuerySource.LITERATURE_AUGMENTED
    assert result.kb_facts == []
    assert result.literature_facts
    assert all(f.tier is EvidenceTier.HYPOTHESIS for f in result.literature_facts)
    assert not _established_lit_lines(result.answer)
    assert "pending review" in result.answer.lower()


async def test_repeat_queries_do_not_upgrade_literature_evidence(jats_xml) -> None:
    store = await _store_with_resolved_literature(jats_xml)
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))

    first = await orch.answer("What is TERT?")
    second = await orch.answer("What is TERT?")

    # Deterministic, and repetition never promotes literature toward established.
    assert first.answer == second.answer
    assert [(f.citation, f.tier) for f in first.literature_facts] == [
        (f.citation, f.tier) for f in second.literature_facts
    ]
    assert all(f.tier is EvidenceTier.HYPOTHESIS for f in second.literature_facts)
    assert not _established_lit_lines(second.answer)


async def test_curated_only_store_answer_is_unchanged(jats_xml) -> None:
    # Regression guard: with no literature in the store the KB path is untouched.
    store = _seeded_store()
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    result = await orch.answer("What is TERT?")

    assert result.source is QuerySource.KNOWLEDGE_BASE
    assert result.literature_facts == []
    assert any(f.tier is EvidenceTier.ESTABLISHED for f in result.kb_facts)
    assert "lit:" not in result.answer


async def test_resolved_literature_stays_weak_from_the_curated_node(jats_xml) -> None:
    store = _seeded_store()
    orch = EvidenceQueryOrchestrator(store, literature_agent=_lit_agent(jats_xml))
    await orch.answer("summarize any recent measurements", target_measurements=["TERT"])
    # A later curated hit on TERT can now reach the ingested literature evidence — and it
    # stays weak (downgraded to hypothesis), never an established KB fact.
    followup = await orch.answer("What is TERT?")
    assert followup.source is QuerySource.KNOWLEDGE_BASE
    assert followup.literature_facts  # the resolved literature evidence is reachable
    assert all(f.tier is EvidenceTier.HYPOTHESIS for f in followup.literature_facts)
    assert all("lit:" not in f.citation for f in followup.kb_facts)
