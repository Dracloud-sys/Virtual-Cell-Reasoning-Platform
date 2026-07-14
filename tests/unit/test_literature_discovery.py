"""Tests for deterministic discovery: query building, connector, dedup, relevance.

No network: the Europe PMC connector is driven by an injected fake transport.
"""

from __future__ import annotations

import json

import pytest

from virtualcell.literature.contracts import (
    ArticleIdentifier,
    ArticleRecord,
    LiteratureQuery,
)
from virtualcell.literature.discovery import (
    build_europe_pmc_query,
    deduplicate_articles,
    discover,
    score_relevance,
)
from virtualcell.literature.providers.base import HttpResponse, ProviderError
from virtualcell.literature.providers.europe_pmc import EuropePmcProvider


class _FakeTransport:
    """Returns queued responses (or raises a queued exception) per call, in order."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def get(self, url: str, *, headers=None, timeout: float = 10.0) -> HttpResponse:
        self.calls.append(url)
        item = self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


def _result(**over) -> dict:
    base = {
        "id": "PMC111",
        "source": "PMC",
        "pmid": "111",
        "pmcid": "PMC111",
        "doi": "10.1000/A",
        "title": "TERT and CDK4 in bovine preadipocyte senescence escape",
        "abstractText": (
            "Bovine preadipocyte cells expressing TERT escaped senescence after long culture."
        ),
        "authorString": "Kim J, Lee S.",
        "journalInfo": {"journal": {"title": "J Cell Sci"}},
        "pubYear": "2022",
        "pubTypeList": {"pubType": ["research-article"]},
        "publicationStatus": "ppublish",
        "isOpenAccess": "Y",
        "inPMC": "Y",
        "hasSuppl": "Y",
    }
    base.update(over)
    return base


def _page(results: list[dict], *, hit_count=3, next_cursor="C2") -> HttpResponse:
    body = {
        "hitCount": hit_count,
        "nextCursorMark": next_cursor,
        "resultList": {"result": results},
    }
    return HttpResponse(status_code=200, text=json.dumps(body))


_EMPTY_PAGE = _page([], next_cursor="C2")


def _query(**over) -> LiteratureQuery:
    kw = {
        "query_text": "spontaneous immortalization",
        "species": ["Bos taurus", "bovine"],
        "cell_types": ["preadipocyte"],
        "genes": ["TERT", "CDK4"],
        "max_results": 25,
    }
    kw.update(over)
    return LiteratureQuery(**kw)


# --- query builder -----------------------------------------------------------


def test_deterministic_provider_query_generation() -> None:
    built1 = build_europe_pmc_query(_query(open_access_only=True, year_from=2010, year_to=2020))
    built2 = build_europe_pmc_query(_query(open_access_only=True, year_from=2010, year_to=2020))
    assert built1.query_string == built2.query_string  # deterministic
    q = built1.query_string
    assert '("spontaneous immortalization")' in q
    assert '"Bos taurus" OR "bovine"' in q
    assert '"TERT" OR "CDK4"' in q
    assert "PUB_YEAR:[2010 TO 2020]" in q
    assert "OPEN_ACCESS:Y" in q
    # Only caller-provided synonyms are recorded; none are invented.
    assert built1.expansions["species"] == ["Bos taurus", "bovine"]


def test_query_builder_sanitizes_quotes() -> None:
    built = build_europe_pmc_query(LiteratureQuery(query_text='TERT "escape"'))
    assert '"' not in built.query_string.replace('("', "").replace('")', "")


# --- connector ---------------------------------------------------------------


def test_mocked_search_maps_fields() -> None:
    transport = _FakeTransport([_page([_result()]), _EMPTY_PAGE])
    provider = EuropePmcProvider(transport)
    result = provider.search(_query())
    assert result.provenance.provider == "europe_pmc"
    assert result.provenance.hit_count == 3
    art = result.articles[0]
    assert art.identifiers.pmcid == "PMC111"
    assert art.is_open_access is True
    assert art.has_full_text is True
    assert art.has_supplementary is True
    assert art.publication_year == 2022
    assert art.authors == ["Kim J", "Lee S"]


def test_bounded_max_results() -> None:
    many = [_result(id=str(i), pmid=str(i), pmcid=None, doi=f"10.1/{i}") for i in range(10)]
    transport = _FakeTransport([_page(many, hit_count=10, next_cursor="C2"), _EMPTY_PAGE])
    provider = EuropePmcProvider(transport)
    result = provider.search(_query(max_results=3))
    assert len(result.articles) == 3  # capped at max_results


def test_provider_http_failure_is_not_a_silent_empty_result() -> None:
    transport = _FakeTransport([HttpResponse(status_code=500, text="")])
    provider = EuropePmcProvider(transport, retries=0)
    with pytest.raises(ProviderError):
        provider.search(_query())


def test_zero_results_is_not_an_error() -> None:
    transport = _FakeTransport([_page([], hit_count=0, next_cursor="*")])
    provider = EuropePmcProvider(transport)
    result = provider.search(_query())
    assert result.articles == []
    assert result.provenance.hit_count == 0


def test_transport_error_retries_then_raises() -> None:
    transport = _FakeTransport(
        [ProviderError("boom"), ProviderError("boom"), ProviderError("boom")]
    )
    provider = EuropePmcProvider(transport, retries=2)
    with pytest.raises(ProviderError):
        provider.search(_query())
    assert len(transport.calls) == 3  # initial + 2 retries


def test_pagination_stops_and_records_pages() -> None:
    page1 = _page([_result(id=str(i), pmid=str(i), pmcid=None, doi=f"10.1/{i}") for i in range(2)])
    transport = _FakeTransport([page1, _EMPTY_PAGE])
    provider = EuropePmcProvider(transport)
    result = provider.search(_query(max_results=25))
    assert result.provenance.pages_fetched == 2  # fetched a second (empty) page, then stopped
    assert len(result.articles) == 2


# --- provider failure semantics & retry --------------------------------------


def test_malformed_json_is_a_provider_error() -> None:
    transport = _FakeTransport([HttpResponse(status_code=200, text="not json")])
    with pytest.raises(ProviderError, match="malformed JSON"):
        EuropePmcProvider(transport).search(_query())


def test_transient_status_is_retried_then_succeeds() -> None:
    transport = _FakeTransport(
        [HttpResponse(status_code=503, text=""), _page([_result()]), _EMPTY_PAGE]
    )
    provider = EuropePmcProvider(transport, retries=2, sleeper=lambda _: None)
    result = provider.search(_query())
    assert len(result.articles) == 1
    assert len(transport.calls) == 3  # 503 retried, then page, then empty page


def test_client_4xx_is_not_retried() -> None:
    transport = _FakeTransport([HttpResponse(status_code=400, text="")])
    provider = EuropePmcProvider(transport, retries=3, sleeper=lambda _: None)
    with pytest.raises(ProviderError):
        provider.search(_query())
    assert len(transport.calls) == 1  # 4xx: no retry


def test_negative_config_is_rejected() -> None:
    with pytest.raises(ValueError):
        EuropePmcProvider(retries=-1)


def test_provider_error_carries_query_context() -> None:
    transport = _FakeTransport([HttpResponse(status_code=500, text="")])
    provider = EuropePmcProvider(transport, retries=0)
    try:
        provider.search(_query())
    except ProviderError as exc:
        assert exc.provider == "europe_pmc"
        assert exc.query_sent and "spontaneous immortalization" in exc.query_sent
    else:  # pragma: no cover
        raise AssertionError("expected ProviderError")


def test_full_text_404_returns_none() -> None:
    transport = _FakeTransport([HttpResponse(status_code=404, text="")])
    provider = EuropePmcProvider(transport)
    assert provider.fetch_open_full_text(ArticleIdentifier(pmcid="PMC1")) is None


def test_malformed_row_is_skipped_with_warning() -> None:
    # A row with no identifiers cannot build an ArticleRecord; it is skipped, not fatal.
    good = _result()
    bad = _result(id=None, pmid=None, pmcid=None, doi=None)
    transport = _FakeTransport([_page([good, bad], hit_count=2), _EMPTY_PAGE])
    result = EuropePmcProvider(transport).search(_query())
    assert len(result.articles) == 1
    assert result.warnings and "skipped" in result.warnings[0]


# --- correction / retraction notices -----------------------------------------


def test_retraction_notice_sets_flag() -> None:
    raw = _result(
        commentCorrectionList={"commentCorrection": [{"type": "Retraction", "id": "999"}]}
    )
    transport = _FakeTransport([_page([raw]), _EMPTY_PAGE])
    art = EuropePmcProvider(transport).search(_query()).articles[0]
    assert art.is_retracted is True
    assert art.notices[0].kind.value == "retraction"
    assert art.notices[0].reference == "999"


def test_correction_is_preserved_but_not_a_retraction() -> None:
    raw = _result(commentCorrectionList={"commentCorrection": [{"type": "Correction", "id": "5"}]})
    transport = _FakeTransport([_page([raw]), _EMPTY_PAGE])
    art = EuropePmcProvider(transport).search(_query()).articles[0]
    assert art.is_retracted is False  # a correction is not a retraction
    assert art.notices[0].kind.value == "correction"


# --- deduplication -----------------------------------------------------------


def _rec(
    pmid=None, pmcid=None, doi=None, provider_id=None, title="A paper", **over
) -> ArticleRecord:
    if not any([pmid, pmcid, doi, provider_id]):
        provider_id = "auto"  # satisfy the >=1-id rule; provider_id is not a strong key
    return ArticleRecord(
        identifiers=ArticleIdentifier(pmid=pmid, pmcid=pmcid, doi=doi, provider_id=provider_id),
        title=title,
        **over,
    )


def test_dedup_by_strong_identifier() -> None:
    # Same paper indexed twice: once with PMCID+PMID, once with only PMID.
    result = deduplicate_articles(
        [_rec(pmid="111", pmcid="PMC111", doi="10.1/a"), _rec(pmid="111", abstract="filled in")]
    )
    assert len(result.articles) == 1
    assert result.articles[0].identifiers.pmcid == "PMC111"
    assert result.articles[0].abstract == "filled in"  # gap filled from the duplicate


def test_dedup_by_normalized_doi() -> None:
    result = deduplicate_articles(
        [_rec(doi="10.1000/ABC"), _rec(doi="https://doi.org/10.1000/abc")]
    )
    assert len(result.articles) == 1


def test_different_pmid_same_title_stays_separate() -> None:
    # The bug this fixes: distinct papers must NOT be merged on title alone.
    result = deduplicate_articles(
        [
            _rec(pmid="111", doi="10.1/a", title="Identical title"),
            _rec(pmid="222", doi="10.1/b", title="Identical title"),
        ]
    )
    assert len(result.articles) == 2


def test_different_doi_same_title_stays_separate() -> None:
    result = deduplicate_articles(
        [_rec(doi="10.1/a", title="Same title"), _rec(doi="10.1/b", title="Same title")]
    )
    assert len(result.articles) == 2


def test_same_pmid_different_metadata_merges() -> None:
    result = deduplicate_articles(
        [_rec(pmid="111", title="Title one"), _rec(pmid="111", abstract="extra")]
    )
    assert len(result.articles) == 1


def test_transitive_merge_via_shared_ids() -> None:
    # A (pmcid only) + B (pmcid + pmid) + C (pmid only) -> one record.
    result = deduplicate_articles(
        [_rec(pmcid="PMC1"), _rec(pmcid="PMC1", pmid="111"), _rec(pmid="111")]
    )
    assert len(result.articles) == 1


def test_title_fallback_only_without_strong_ids() -> None:
    result = deduplicate_articles(
        [_rec(provider_id="x", title="TERT Escape!"), _rec(provider_id="y", title="tert   escape")]
    )
    assert len(result.articles) == 1  # no strong ids -> title fallback merges


def test_conflicting_strong_ids_merge_but_report_conflict() -> None:
    # Same DOI, different PMID: they share a strong id so they merge, but the PMID
    # conflict is surfaced rather than silently overwritten.
    result = deduplicate_articles([_rec(doi="10.1/a", pmid="111"), _rec(doi="10.1/a", pmid="222")])
    assert len(result.articles) == 1
    assert result.articles[0].identifiers.pmid == "111"  # first wins, not overwritten
    assert any("pmid" in c for c in result.conflicts)


def test_distinct_papers_are_not_merged() -> None:
    result = deduplicate_articles(
        [_rec(pmid="1", title="Paper A"), _rec(pmid="2", title="Paper B")]
    )
    assert len(result.articles) == 2


def test_retracted_metadata_is_preserved() -> None:
    transport = _FakeTransport(
        [_page([_result(pubTypeList={"pubType": ["Retracted Publication"]})]), _EMPTY_PAGE]
    )
    provider = EuropePmcProvider(transport)
    assert provider.search(_query()).articles[0].is_retracted is True


# --- relevance ---------------------------------------------------------------


def test_relevance_breakdown_is_transparent() -> None:
    art = _rec(
        pmid="1",
        title="TERT in bovine preadipocyte senescence",
        abstract="bovine preadipocyte TERT CDK4 escape",
        has_full_text=True,
    )
    rel = score_relevance(art, _query())
    names = {c.name for c in rel.breakdown}
    assert {"query_terms", "title_match", "species", "genes", "availability"} <= names
    assert rel.total_score > 0
    assert "tert" in [m.lower() for m in rel.matched_terms] or "bovine" in rel.matched_terms
    assert rel.missing_critical_filters == []  # species/cell_types/genes all matched


def test_missing_critical_filter_is_flagged() -> None:
    art = _rec(pmid="1", title="An unrelated study", abstract="nothing relevant here")
    rel = score_relevance(art, _query())
    assert set(rel.missing_critical_filters) == {"species", "cell_types", "genes"}


def test_relevance_is_not_an_evidence_tier() -> None:
    # RelevanceResult exposes only search-relevance fields — no confidence/tier that
    # could be mistaken for scientific strength.
    art = _rec(pmid="1", title="TERT bovine", abstract="bovine TERT")
    rel = score_relevance(art, _query())
    fields = set(type(rel).model_fields)
    assert "confidence" not in fields and "tier" not in fields and "evidence" not in fields


def test_discover_returns_relevance_ranked_bundle() -> None:
    high = _result(pmid="1", pmcid=None, doi="10.1/1")
    low = _result(
        pmid="2",
        pmcid=None,
        doi="10.1/2",
        title="Unrelated topic",
        abstractText="no relevant terms",
        isOpenAccess="N",
        inPMC="N",
        hasSuppl="N",
    )
    transport = _FakeTransport([_page([low, high], hit_count=2), _EMPTY_PAGE])
    bundle = discover(_query(), EuropePmcProvider(transport))
    assert [r.article.pmid for r in bundle.relevance] == ["1", "2"]  # ranked high-first
    assert bundle.claims == [] and bundle.measurements == []  # discovery only
