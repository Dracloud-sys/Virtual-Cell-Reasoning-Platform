"""End-to-end: discovery -> open-access JATS -> extraction -> unverified bundle.

Fixture-driven: a fake provider serves both the search page and the full-text XML.
No network, no LLM API.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tests.unit.test_literature_documents import JATS

from virtualcell.agents.literature_discovery.agent import LiteratureDiscoveryAgent
from virtualcell.core.agent import AgentContext
from virtualcell.core.contracts import AgentInput
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.literature.contracts import (
    ArticleIdentifier,
    ArticleRecord,
    ExtractionMethod,
    LiteratureEvidenceBundle,
    LiteratureSearchResult,
    ProviderProvenance,
    SourceKind,
    SourceLocator,
)
from virtualcell.literature.extraction import (
    ExtractedMeasurementCandidate,
    LiteratureExtractionResult,
)

_IDENT = ArticleIdentifier(pmcid="PMC1", pmid="1", provider_id="PMC1")


class _FakeProvider:
    """Serves one open-access article plus its JATS full text."""

    name = "fake"

    def __init__(self, *, full_text: str | None = JATS) -> None:
        self.full_text = full_text

    def search(self, query) -> LiteratureSearchResult:
        return LiteratureSearchResult(
            provenance=ProviderProvenance(
                provider=self.name,
                query_sent="q",
                retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
                hit_count=1,
            ),
            articles=[
                ArticleRecord(
                    identifiers=_IDENT,
                    title="TERT in bovine preadipocyte senescence",
                    abstract="bovine preadipocyte TERT escape",
                    is_open_access=True,
                    has_full_text=True,
                    provider=self.name,
                    source_url="https://europepmc.org/article/PMC/PMC1",
                    retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
                )
            ],
        )

    def fetch_record(self, identifier):  # pragma: no cover - unused
        raise NotImplementedError

    def fetch_open_full_text(self, identifier) -> str | None:
        return self.full_text


class _FakeExtractor:
    """A fake structured extractor: one honest candidate, one hallucinated."""

    name = "fake_structured"

    def extract(self, document, task) -> LiteratureExtractionResult:
        def measurement(text: str, value: float) -> ExtractedMeasurementCandidate:
            return ExtractedMeasurementCandidate(
                measurement_name="TERT",
                raw_value=text,
                parsed_value=value,
                parse_status="parsed",
                extraction_method=ExtractionMethod.LLM_STRUCTURED,
                source_locator=SourceLocator(
                    article=document.article,
                    source_kind=SourceKind.TABLE,
                    table_id="T1",
                    row_label="TERT",
                    column_label="P35",
                    source_text=text,
                ),
            )

        return LiteratureExtractionResult(
            measurements=[measurement("2.4", 2.4), measurement("9.9", 9.9)]  # 2nd is fabricated
        )


def _agent(provider=None, extractor=None) -> LiteratureDiscoveryAgent:
    services = {"literature_provider": provider or _FakeProvider()}
    if extractor is not None:
        services["literature_extractor"] = extractor
    return LiteratureDiscoveryAgent(AgentContext(services=services))


def _inputs(**over) -> AgentInput:
    context = {"extract": True, "target_measurements": ["TERT", "CDK4"]}
    context.update(over)
    return AgentInput(query="TERT bovine preadipocyte", context=context)


async def test_end_to_end_discovery_to_unverified_candidates() -> None:
    out = await _agent().run(_inputs())
    bundle = LiteratureEvidenceBundle.model_validate(out.result)  # JSON round-trips

    assert bundle.measurements, "expected deterministic candidates from the JATS table"
    assert {m.measurement_name for m in bundle.measurements} == {"TERT", "CDK4"}
    tert = next(m for m in bundle.measurements if m.sample_group == "P35" and m.parsed_value == 2.4)
    assert tert.source_locator.table_id == "T1"
    assert tert.source_locator.source_text == "2.4"
    assert tert.source_locator.source_text_hash

    # Document metadata is carried; the body text is not.
    assert len(bundle.documents) == 1
    assert bundle.documents[0].content_hash
    assert "escaped senescence" not in str(out.result)

    # PR8c invariants: everything is unverified, nothing is canonical.
    assert bundle.verification_decisions == []
    assert bundle.canonical_runs == []
    assert out.claims == []  # no biological Claim from discovery/extraction


async def test_candidate_ids_are_stable_across_runs() -> None:
    first = LiteratureEvidenceBundle.model_validate((await _agent().run(_inputs())).result)
    second = LiteratureEvidenceBundle.model_validate((await _agent().run(_inputs())).result)
    assert [m.candidate_id for m in first.measurements] == [
        m.candidate_id for m in second.measurements
    ]


async def test_llm_candidates_are_accepted_only_when_source_anchored() -> None:
    out = await _agent(extractor=_FakeExtractor()).run(_inputs())
    bundle = LiteratureEvidenceBundle.model_validate(out.result)
    llm = [m for m in bundle.measurements if m.extraction_method.value == "llm_structured"]
    assert [m.parsed_value for m in llm] == [2.4]  # the fabricated 9.9 was rejected
    assert any("rejected candidate" in w for w in bundle.warnings)


async def test_extraction_is_opt_in() -> None:
    out = await _agent().run(AgentInput(query="TERT", context={}))  # no extract flag
    bundle = LiteratureEvidenceBundle.model_validate(out.result)
    assert bundle.measurements == [] and bundle.documents == []


async def test_malformed_full_text_fails_safely() -> None:
    out = await _agent(_FakeProvider(full_text="<article><body>")).run(_inputs())
    bundle = LiteratureEvidenceBundle.model_validate(out.result)
    assert bundle.measurements == []
    assert any("could not parse full text" in w for w in bundle.warnings)


async def test_abstract_only_fallback_when_no_full_text() -> None:
    out = await _agent(_FakeProvider(full_text=None)).run(_inputs())
    bundle = LiteratureEvidenceBundle.model_validate(out.result)
    assert len(bundle.documents) == 1
    assert bundle.documents[0].source_format.value == "abstract"
    assert bundle.measurements == []  # no tables in an abstract-only document


async def test_knowledge_store_is_untouched() -> None:
    store = InMemoryKnowledgeStore()
    agent = LiteratureDiscoveryAgent(
        AgentContext(services={"literature_provider": _FakeProvider(), "knowledge_store": store})
    )
    await agent.run(_inputs())
    assert store.all_entities() == []
    assert store.all_interactions() == []
