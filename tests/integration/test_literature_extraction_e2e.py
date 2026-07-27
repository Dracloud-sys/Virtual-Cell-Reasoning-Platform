"""End-to-end: discovery -> open-access JATS -> extraction -> unverified bundle.

Fixture-driven: a fake provider serves both the search page and the full-text XML.
No network, no LLM API. The JATS sample comes from the ``jats_xml`` conftest fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from virtualcell.agents.literature_discovery.agent import (
    LiteratureDiscoveryAgent,
    LiteratureQueryError,
)
from virtualcell.core.agent import AgentContext
from virtualcell.core.contracts import AgentInput
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.literature.contracts import (
    ArticleIdentifier,
    ArticleRecord,
    ExtractedMeasurementCandidate,
    ExtractionMethod,
    LiteratureEvidenceBundle,
    LiteratureSearchResult,
    ProviderProvenance,
    SourceKind,
    SourceLocator,
)
from virtualcell.literature.extraction import LiteratureExtractionResult
from virtualcell.literature.providers.base import ProviderError

_IDENT = ArticleIdentifier(pmcid="PMC1", pmid="1", provider_id="PMC1")


def _record(
    identifiers=_IDENT,
    *,
    title="TERT in bovine preadipocyte senescence",
    abstract="bovine preadipocyte TERT escape",
    full=True,
    provider="fake",
):
    return ArticleRecord(
        identifiers=identifiers,
        title=title,
        abstract=abstract,
        is_open_access=full,
        has_full_text=full,
        provider=provider,
        source_url="https://europepmc.org/article/PMC/PMC1",
        retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


class _FakeProvider:
    """Serves configurable articles plus their JATS full text."""

    name = "fake"

    def __init__(self, xml: str | None, *, records=None, raise_fetch=False) -> None:
        self.xml = xml
        self.records = records if records is not None else [_record()]
        self.raise_fetch = raise_fetch

    def search(self, query) -> LiteratureSearchResult:
        return LiteratureSearchResult(
            provenance=ProviderProvenance(
                provider=self.name,
                query_sent="q",
                retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
                hit_count=len(self.records),
            ),
            articles=list(self.records),
        )

    def fetch_record(self, identifier):  # pragma: no cover - unused
        raise NotImplementedError

    def fetch_open_full_text(self, identifier) -> str | None:
        if self.raise_fetch:
            raise ProviderError("network down")
        return self.xml


class _FakeExtractor:
    """One honest candidate, one hallucinated."""

    name = "fake_structured"

    def extract(self, document, task) -> LiteratureExtractionResult:
        def measurement(text: str, value: float, **loc):
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
                    source_text=text,
                    **loc,
                ),
            )

        return LiteratureExtractionResult(
            measurements=[
                measurement(
                    "2.4", 2.4, row_index=0, column_index=2, row_label="TERT", column_label="P35"
                ),
                measurement("9.9", 9.9),  # fabricated span
            ]
        )


class _ExplodingExtractor:
    name = "exploding"

    def extract(self, document, task):
        raise RuntimeError("model unavailable")


class _ConfidenceDuplicateExtractor:
    """Returns many candidates that differ only in extraction_confidence — an identity
    field is excluded from candidate_id, so these all collapse to ONE candidate."""

    name = "dupes"

    def extract(self, document, task) -> LiteratureExtractionResult:
        return LiteratureExtractionResult(
            measurements=[
                ExtractedMeasurementCandidate(
                    measurement_name="TERT",
                    sample_group="P35",
                    raw_value="2.4",
                    parsed_value=2.4,
                    parse_status="parsed",
                    extraction_confidence=i / 1000,  # varies a non-identity field only
                    extraction_method=ExtractionMethod.LLM_STRUCTURED,
                    source_locator=SourceLocator(
                        article=document.article,
                        source_kind=SourceKind.TABLE,
                        table_id="T1",
                        row_index=0,
                        column_index=2,
                        row_label="TERT",
                        column_label="P35",
                        source_text="2.4",
                    ),
                )
                for i in range(50)
            ]
        )


# A table with many distinct marker rows, so deterministic extraction alone yields
# many DISTINCT candidates (real flooding, not identity-duplicated).
_MARKERS = [f"M{i}" for i in range(1, 7)]
_BIG_TABLE = (
    '<article><back><table-wrap id="T1"><table>'
    "<thead><tr><th>Marker</th><th>P35</th></tr></thead><tbody>"
    + "".join(f"<tr><td>{m}</td><td>{i + 1}.0</td></tr>" for i, m in enumerate(_MARKERS))
    + "</tbody></table></table-wrap></back></article>"
)


def _big_inputs(**over) -> AgentInput:
    context = {"extract": True, "target_measurements": _MARKERS}
    context.update(over)
    return AgentInput(query="markers", context=context)


def _agent(provider, extractor=None) -> LiteratureDiscoveryAgent:
    services = {"literature_provider": provider}
    if extractor is not None:
        services["literature_extractor"] = extractor
    return LiteratureDiscoveryAgent(AgentContext(services=services))


def _inputs(**over) -> AgentInput:
    context = {"extract": True, "target_measurements": ["TERT", "CDK4"]}
    context.update(over)
    return AgentInput(query="TERT bovine preadipocyte", context=context)


async def _bundle(
    provider, extractor=None, *, over_inputs=_inputs, **over
) -> LiteratureEvidenceBundle:
    out = await _agent(provider, extractor).run(over_inputs(**over))
    return LiteratureEvidenceBundle.model_validate(out.result)


# --- the happy path -----------------------------------------------------------


async def test_end_to_end_discovery_to_unverified_candidates(jats_xml) -> None:
    out = await _agent(_FakeProvider(jats_xml)).run(_inputs())
    bundle = LiteratureEvidenceBundle.model_validate(out.result)  # JSON round-trips

    assert {m.measurement_name for m in bundle.measurements} == {"TERT", "CDK4"}
    tert = next(m for m in bundle.measurements if m.sample_group == "P35" and m.parsed_value == 2.4)
    assert tert.source_locator.table_id == "T1"
    assert (tert.source_locator.row_index, tert.source_locator.column_index) == (0, 2)

    assert len(bundle.documents) == 1 and bundle.documents[0].content_hash
    assert "escaped senescence" not in str(out.result)  # no body text in the output

    # PR8c invariants.
    assert bundle.verification_decisions == []
    assert bundle.canonical_runs == []
    assert out.claims == []


async def test_candidate_ids_are_stable_across_runs(jats_xml) -> None:
    first = await _bundle(_FakeProvider(jats_xml))
    second = await _bundle(_FakeProvider(jats_xml))
    assert [m.candidate_id for m in first.measurements] == [
        m.candidate_id for m in second.measurements
    ]


async def test_extraction_is_opt_in(jats_xml) -> None:
    out = await _agent(_FakeProvider(jats_xml)).run(AgentInput(query="TERT", context={}))
    bundle = LiteratureEvidenceBundle.model_validate(out.result)
    assert bundle.measurements == [] and bundle.documents == []


# --- article identity ---------------------------------------------------------


async def test_doi_only_articles_are_not_collapsed(jats_xml) -> None:
    # Two DOI-only records previously collided on one identity key: one paper was
    # silently dropped and the other extracted twice.
    records = [
        _record(ArticleIdentifier(doi="10.1/a"), abstract="TERT a", full=False),
        _record(ArticleIdentifier(doi="10.1/b"), abstract="TERT b", full=False),
    ]
    bundle = await _bundle(_FakeProvider(jats_xml, records=records))
    assert sorted(d.article.doi for d in bundle.documents) == ["10.1/a", "10.1/b"]


async def test_pmcid_only_article_is_extracted(jats_xml) -> None:
    records = [_record(ArticleIdentifier(pmcid="PMC9"), abstract="TERT only", full=False)]
    bundle = await _bundle(_FakeProvider(jats_xml, records=records))
    assert [d.article.pmcid for d in bundle.documents] == ["PMC9"]


async def test_provider_id_only_article_is_extracted(jats_xml) -> None:
    records = [_record(ArticleIdentifier(provider_id="X1"), abstract="TERT only", full=False)]
    bundle = await _bundle(_FakeProvider(jats_xml, records=records))
    assert [d.article.provider_id for d in bundle.documents] == ["X1"]


async def test_provider_id_only_ranking_picks_the_higher_score(jats_xml) -> None:
    # A provider_id-only record's relevance score must resolve (was: 0, so the wrong
    # paper won). The higher-scoring paper is selected when only one is extracted.
    records = [
        _record(
            ArticleIdentifier(provider_id="A"), title="Unrelated", abstract="nothing", full=False
        ),
        _record(
            ArticleIdentifier(provider_id="B"),
            title="TERT bovine preadipocyte",
            abstract="TERT bovine preadipocyte escape",
            full=False,
        ),
    ]
    out = await _agent(_FakeProvider(jats_xml, records=records)).run(
        _inputs(max_extract_articles=1)
    )
    bundle = LiteratureEvidenceBundle.model_validate(out.result)
    assert [d.article.provider_id for d in bundle.documents] == ["B"]


async def test_same_provider_id_from_different_providers_do_not_collide(jats_xml) -> None:
    # Distinct titles (so title-fallback dedup keeps both) but the SAME provider_id.
    records = [
        _record(
            ArticleIdentifier(provider_id="7"), title="TERT paper one", full=False, provider="p1"
        ),
        _record(
            ArticleIdentifier(provider_id="7"), title="TERT paper two", full=False, provider="p2"
        ),
    ]
    bundle = await _bundle(_FakeProvider(jats_xml, records=records), max_extract_articles=5)
    # Namespaced by provider (provider:p1:7 vs provider:p2:7), so both are extracted.
    assert len(bundle.documents) == 2


# --- abstract fallback --------------------------------------------------------


async def test_fetch_failure_falls_back_to_the_abstract(jats_xml) -> None:
    bundle = await _bundle(_FakeProvider(jats_xml, raise_fetch=True))
    assert len(bundle.documents) == 1
    assert bundle.documents[0].source_format.value == "abstract"
    assert any("full text unavailable" in w and "fell back" in w for w in bundle.warnings)


async def test_malformed_full_text_falls_back_to_the_abstract() -> None:
    bundle = await _bundle(_FakeProvider("<article><body>"))
    assert len(bundle.documents) == 1
    assert bundle.documents[0].source_format.value == "abstract"  # not recorded as JATS
    assert any("could not parse full text" in w for w in bundle.warnings)


async def test_no_full_text_and_no_abstract_is_skipped_with_a_warning() -> None:
    records = [_record(abstract=None)]
    bundle = await _bundle(_FakeProvider(None, records=records))
    assert bundle.documents == []
    assert any("no open-access full text and no abstract" in w for w in bundle.warnings)


# --- bounds and LLM isolation -------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, 999, "many"])
async def test_max_extract_articles_is_validated(jats_xml, bad) -> None:
    with pytest.raises(LiteratureQueryError):
        await _agent(_FakeProvider(jats_xml)).run(_inputs(max_extract_articles=bad))


@pytest.mark.parametrize("bad", [0, -1, 10_000])
async def test_max_candidates_is_validated(jats_xml, bad) -> None:
    with pytest.raises(LiteratureQueryError):
        await _agent(_FakeProvider(jats_xml)).run(_inputs(max_candidates=bad))


async def test_llm_candidates_are_accepted_only_when_source_anchored(jats_xml) -> None:
    bundle = await _bundle(_FakeProvider(jats_xml), _FakeExtractor())
    llm = [m for m in bundle.measurements if m.extraction_method.value == "llm_structured"]
    assert [m.parsed_value for m in llm] == [2.4]  # the fabricated 9.9 was rejected
    assert any("rejected candidate" in w for w in bundle.warnings)


async def test_llm_candidate_for_an_unrequested_target_is_rejected(jats_xml) -> None:
    class _OffTarget:
        name = "off_target"

        def extract(self, document, task) -> LiteratureExtractionResult:
            # Cites the real TERT/P35 cell but names a measurement no one requested.
            return LiteratureExtractionResult(
                measurements=[
                    ExtractedMeasurementCandidate(
                        measurement_name="NOT_REQUESTED",
                        raw_value="2.4",
                        parsed_value=2.4,
                        parse_status="parsed",
                        extraction_method=ExtractionMethod.LLM_STRUCTURED,
                        source_locator=SourceLocator(
                            article=document.article,
                            source_kind=SourceKind.TABLE,
                            table_id="T1",
                            row_index=0,
                            column_index=2,
                            row_label="TERT",
                            column_label="P35",
                            source_text="2.4",
                        ),
                    )
                ]
            )

    bundle = await _bundle(_FakeProvider(jats_xml), _OffTarget())
    assert all(m.measurement_name != "NOT_REQUESTED" for m in bundle.measurements)
    assert any("not a requested target" in w for w in bundle.warnings)


async def test_llm_failure_is_isolated_and_keeps_deterministic_results(jats_xml) -> None:
    bundle = await _bundle(_FakeProvider(jats_xml), _ExplodingExtractor())
    assert bundle.measurements, "deterministic candidates must survive an extractor failure"
    assert all(m.extraction_method.value == "deterministic_table" for m in bundle.measurements)
    assert any("structured extractor failed" in w for w in bundle.warnings)


async def test_confidence_only_duplicates_collapse_to_one(jats_xml) -> None:
    bundle = await _bundle(_FakeProvider(jats_xml), _ConfidenceDuplicateExtractor())
    llm = [m for m in bundle.measurements if m.extraction_method.value == "llm_structured"]
    assert len(llm) == 1  # 50 confidence-varied proposals share one candidate_id


async def test_distinct_candidates_hit_the_per_document_cap() -> None:
    # A single big table yields 6 distinct deterministic candidates; the per-document
    # cap keeps 3.
    bundle = await _bundle(_FakeProvider(_BIG_TABLE), max_candidates=3, over_inputs=_big_inputs)
    assert len(bundle.measurements) == 3
    assert any("max_candidates" in w for w in bundle.warnings)


async def test_global_cap_spans_documents() -> None:
    # Two documents, each with 6 distinct candidates and a per-document cap of 10 (never
    # hit), but a global cap of 8: 6 from the first document, 2 from the second.
    records = [
        _record(ArticleIdentifier(doi="10.1/a"), full=True),
        _record(ArticleIdentifier(doi="10.1/b"), full=True),
    ]
    bundle = await _bundle(
        _FakeProvider(_BIG_TABLE, records=records),
        max_candidates=10,
        max_total_candidates=8,
        over_inputs=_big_inputs,
    )
    assert len(bundle.measurements) == 8
    assert any("max_total_candidates" in w for w in bundle.warnings)


class _ClaimExtractor:
    """Adds two abstract-anchored claim candidates (valid source spans)."""

    name = "claims"

    def extract(self, document, task) -> LiteratureExtractionResult:
        from virtualcell.literature.contracts import ExtractedClaimCandidate

        def claim(obj: str):
            return ExtractedClaimCandidate(
                subject="TERT",
                predicate="increased",
                object=obj,
                extraction_method=ExtractionMethod.LLM_STRUCTURED,
                source_locator=SourceLocator(
                    article=document.article,
                    source_kind=SourceKind.ABSTRACT,
                    source_text="TERT expression increased",
                ),
            )

        return LiteratureExtractionResult(claims=[claim("after culture"), claim("with passage")])


class _ThreeBucketExtractor:
    """Returns one claim and one author interpretation, both abstract-anchored."""

    name = "three_bucket"

    def extract(self, document, task) -> LiteratureExtractionResult:
        from virtualcell.literature.contracts import (
            AuthorInterpretationCandidate,
            ExtractedClaimCandidate,
        )

        locator = SourceLocator(
            article=document.article,
            source_kind=SourceKind.ABSTRACT,
            source_text="TERT expression increased",
        )
        return LiteratureExtractionResult(
            claims=[
                ExtractedClaimCandidate(
                    subject="TERT",
                    predicate="increased",
                    object="after culture",
                    extraction_method=ExtractionMethod.LLM_STRUCTURED,
                    source_locator=locator,
                )
            ],
            author_interpretations=[
                AuthorInterpretationCandidate(
                    statement="TERT expression increased",
                    extraction_method=ExtractionMethod.LLM_STRUCTURED,
                    source_locator=locator,
                )
            ],
        )


async def test_global_cap_spans_all_three_buckets(jats_xml) -> None:
    # Target CDK4 -> 2 deterministic measurements; the extractor adds 1 claim and 1
    # author interpretation. With a global cap of 3, the total across ALL THREE buckets
    # is 3 (measurements, then a claim), and the interpretation is dropped by the cap.
    async def bundle_at(cap):
        return await _bundle(
            _FakeProvider(jats_xml),
            _ThreeBucketExtractor(),
            target_measurements=["CDK4"],
            max_total_candidates=cap,
        )

    capped = await bundle_at(3)
    total = len(capped.measurements) + len(capped.claims) + len(capped.author_interpretations)
    assert total == 3
    assert capped.author_interpretations == []  # the global cap reached the third bucket
    assert any("max_total_candidates" in w for w in capped.warnings)

    # With enough room, all three buckets are populated (proving the cap, not the data,
    # was the limiter above).
    full = await bundle_at(10)
    assert full.measurements and full.claims and full.author_interpretations

    # Deterministic across runs.
    again = await bundle_at(3)
    assert [m.candidate_id for m in capped.measurements] == [
        m.candidate_id for m in again.measurements
    ]

    # Cap never flips a candidate's verification state.
    assert capped.verification_decisions == [] and capped.canonical_runs == []


async def test_global_cap_sums_across_candidate_buckets(jats_xml) -> None:
    # Target CDK4 -> 2 deterministic measurements; the extractor adds 2 claims. With a
    # global cap of 3, the total across buckets is 3 (measurements first, then a claim).
    bundle = await _bundle(
        _FakeProvider(jats_xml),
        _ClaimExtractor(),
        target_measurements=["CDK4"],
        max_total_candidates=3,
    )
    total = len(bundle.measurements) + len(bundle.claims) + len(bundle.author_interpretations)
    assert total == 3
    assert bundle.measurements and bundle.claims  # the cap spanned both buckets
    assert any("max_total_candidates" in w for w in bundle.warnings)


async def test_cap_order_is_deterministic_across_runs() -> None:
    records = [
        _record(ArticleIdentifier(doi="10.1/a"), full=True),
        _record(ArticleIdentifier(doi="10.1/b"), full=True),
    ]
    kw = dict(max_candidates=10, max_total_candidates=8, over_inputs=_big_inputs)
    first = await _bundle(_FakeProvider(_BIG_TABLE, records=list(records)), **kw)
    second = await _bundle(_FakeProvider(_BIG_TABLE, records=list(records)), **kw)
    assert [m.candidate_id for m in first.measurements] == [
        m.candidate_id for m in second.measurements
    ]


async def test_one_documents_llm_failure_does_not_block_another(jats_xml) -> None:
    records = [
        _record(ArticleIdentifier(doi="10.1/a"), abstract="TERT a", full=False),
        _record(ArticleIdentifier(doi="10.1/b"), abstract="TERT b", full=False),
    ]
    bundle = await _bundle(_FakeProvider(jats_xml, records=records), _ExplodingExtractor())
    # Both documents were still processed despite the extractor failing on each.
    assert len(bundle.documents) == 2
    assert sum("structured extractor failed" in w for w in bundle.warnings) == 2


# --- invariants ---------------------------------------------------------------


async def test_knowledge_store_is_untouched(jats_xml) -> None:
    store = InMemoryKnowledgeStore()
    agent = LiteratureDiscoveryAgent(
        AgentContext(
            services={"literature_provider": _FakeProvider(jats_xml), "knowledge_store": store}
        )
    )
    await agent.run(_inputs())
    assert store.all_entities() == []
    assert store.all_interactions() == []
