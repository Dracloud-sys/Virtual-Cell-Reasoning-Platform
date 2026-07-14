"""Tests for the literature pipeline contracts (PR8b)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from virtualcell.core.experiment import (
    AcquisitionMode,
    ExperimentRun,
    OriginKind,
    Provenance,
)
from virtualcell.literature.contracts import (
    ArticleIdentifier,
    ArticleRecord,
    ExtractedMeasurementCandidate,
    ExtractionMethod,
    LiteratureEvidenceBundle,
    LiteratureQuery,
    ProviderProvenance,
    SourceKind,
    SourceLocator,
    VerificationDecision,
    VerificationStatus,
    hash_source_text,
    normalize_doi,
    normalize_title,
)


def _measurement(value=2.4, **over) -> ExtractedMeasurementCandidate:
    kw = dict(
        measurement_name="TERT",
        value=value,
        unit="fold_change",
        source_locator=SourceLocator(
            article=ArticleIdentifier(pmid="1"),
            source_kind=SourceKind.TABLE,
            source_text=f"TERT {value}",
        ),
        extraction_method=ExtractionMethod.DETERMINISTIC_TABLE,
    )
    kw.update(over)
    return ExtractedMeasurementCandidate(**kw)


def test_query_text_must_not_be_blank() -> None:
    with pytest.raises(ValidationError):
        LiteratureQuery(query_text="   ")


def test_query_text_without_searchable_chars_rejected() -> None:
    with pytest.raises(ValidationError):
        LiteratureQuery(query_text='""')  # sanitizes to nothing


def test_blank_filter_terms_are_dropped() -> None:
    q = LiteratureQuery(query_text="x", genes=["TERT", "", "  "])
    assert q.genes == ["TERT"]


def test_year_bounds_and_order_validated() -> None:
    LiteratureQuery(query_text="x", year_from=2010, year_to=2020)  # ok
    with pytest.raises(ValidationError):
        LiteratureQuery(query_text="x", year_from=2025, year_to=2020)  # from > to
    with pytest.raises(ValidationError):
        LiteratureQuery(query_text="x", year_from=-5)  # out of range


def test_max_results_is_bounded() -> None:
    assert LiteratureQuery(query_text="x", max_results=25).max_results == 25
    with pytest.raises(ValidationError):
        LiteratureQuery(query_text="x", max_results=0)
    with pytest.raises(ValidationError):
        LiteratureQuery(query_text="x", max_results=10_000)  # above the cap


def test_article_identifier_requires_at_least_one_id() -> None:
    ArticleIdentifier(provider_id="p")  # ok
    with pytest.raises(ValidationError):
        ArticleIdentifier()  # all None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("10.1234/ABC", "10.1234/abc"),
        ("https://doi.org/10.1234/abc", "10.1234/abc"),
        ("https://dx.doi.org/10.1234/ABC", "10.1234/abc"),
        ("doi:10.1234/abc", "10.1234/abc"),
        ("  10.1234/abc  ", "10.1234/abc"),
        (None, None),
    ],
)
def test_doi_normalization_preserves_original(raw, expected) -> None:
    assert normalize_doi(raw) == expected
    # A DOI-bearing identifier preserves the original string and normalizes for
    # comparison; the all-None case is covered by the identifier-required test.
    ident = ArticleIdentifier(doi=raw, provider_id="p")
    assert ident.doi == raw  # original preserved verbatim
    assert ident.normalized_doi == expected


def test_title_normalization() -> None:
    assert normalize_title("TERT & CDK4: Senescence!") == "tert cdk4 senescence"
    assert normalize_title(None) is None


def test_source_locator_hash_is_auto_and_verified() -> None:
    with pytest.raises(ValidationError):
        SourceLocator(
            article=ArticleIdentifier(pmid="1"),
            source_kind=SourceKind.ABSTRACT,
            source_text="   ",
        )
    loc = SourceLocator(
        article=ArticleIdentifier(pmid="1"),
        source_kind=SourceKind.TABLE,
        source_text="TERT 2.4 fold",
    )
    assert loc.source_text_hash == hash_source_text("TERT 2.4 fold")  # auto-populated
    # A supplied hash that disagrees with the text is rejected (no stale hash).
    with pytest.raises(ValidationError):
        SourceLocator(
            article=ArticleIdentifier(pmid="1"),
            source_kind=SourceKind.TABLE,
            source_text="TERT 2.4 fold",
            source_text_hash="deadbeef",
        )


def test_candidate_id_is_deterministic_and_content_derived() -> None:
    a = _measurement(value=2.4)
    b = _measurement(value=2.4)
    c = _measurement(value=9.9)
    assert a.candidate_id and a.candidate_id == b.candidate_id  # same content -> same id
    assert a.candidate_id != c.candidate_id  # different content -> different id
    assert a.verification_status is VerificationStatus.PENDING_REVIEW


def test_two_candidates_from_one_source_have_distinct_ids() -> None:
    loc = SourceLocator(
        article=ArticleIdentifier(pmid="1"),
        source_kind=SourceKind.TABLE,
        source_text="TERT 2.4; CDK4 1.1",
    )
    m1 = ExtractedMeasurementCandidate(
        measurement_name="TERT",
        value=2.4,
        source_locator=loc,
        extraction_method=ExtractionMethod.DETERMINISTIC_TABLE,
    )
    m2 = ExtractedMeasurementCandidate(
        measurement_name="CDK4",
        value=1.1,
        source_locator=loc,
        extraction_method=ExtractionMethod.DETERMINISTIC_TABLE,
    )
    assert m1.candidate_id != m2.candidate_id


def _bundle(**over) -> LiteratureEvidenceBundle:
    kw = dict(
        query=LiteratureQuery(query_text="x"),
        provider_provenance=ProviderProvenance(
            provider="p", query_sent="x", retrieved_at=datetime(2024, 1, 1, tzinfo=UTC)
        ),
    )
    kw.update(over)
    return LiteratureEvidenceBundle(**kw)


def test_bundle_rejects_duplicate_candidate_ids() -> None:
    m = _measurement()
    with pytest.raises(ValidationError, match="duplicate candidate_id"):
        _bundle(measurements=[m, m.model_copy()])


def test_bundle_rejects_decision_for_unknown_candidate() -> None:
    with pytest.raises(ValidationError, match="unknown candidate_id"):
        _bundle(
            verification_decisions=[
                VerificationDecision(
                    candidate_id="missing",
                    candidate_kind="measurement",
                    status=VerificationStatus.MACHINE_VERIFIED,
                )
            ]
        )


def test_bundle_rejects_status_disagreement() -> None:
    m = _measurement()  # pending_review
    with pytest.raises(ValidationError, match="disagrees"):
        _bundle(
            measurements=[m],
            verification_decisions=[
                VerificationDecision(
                    candidate_id=m.candidate_id,
                    candidate_kind="measurement",
                    status=VerificationStatus.MACHINE_VERIFIED,  # candidate is still pending
                )
            ],
        )


def test_bundle_accepts_consistent_decision() -> None:
    m = _measurement(verification_status=VerificationStatus.MACHINE_VERIFIED)
    bundle = _bundle(
        measurements=[m],
        verification_decisions=[
            VerificationDecision(
                candidate_id=m.candidate_id,
                candidate_kind="measurement",
                status=VerificationStatus.MACHINE_VERIFIED,
            )
        ],
    )
    assert LiteratureEvidenceBundle.model_validate(bundle.model_dump(mode="json")) == bundle


def test_provider_provenance_requires_timezone() -> None:
    ProviderProvenance(provider="p", query_sent="q", retrieved_at=datetime(2024, 1, 1, tzinfo=UTC))
    with pytest.raises(ValidationError):
        ProviderProvenance(provider="p", query_sent="q", retrieved_at=datetime(2024, 1, 1))


def test_article_record_allows_missing_abstract_and_authors() -> None:
    rec = ArticleRecord(identifiers=ArticleIdentifier(pmid="9"))
    assert rec.abstract is None
    assert rec.authors == []


def test_bundle_json_round_trips_with_a_canonical_run() -> None:
    bundle = LiteratureEvidenceBundle(
        query=LiteratureQuery(query_text="TERT senescence"),
        provider_provenance=ProviderProvenance(
            provider="europe_pmc", query_sent="TERT", retrieved_at=datetime(2024, 1, 1, tzinfo=UTC)
        ),
        articles=[ArticleRecord(identifiers=ArticleIdentifier(pmid="9"), title="A paper")],
        canonical_runs=[
            ExperimentRun(
                run_id="lit:10.1/x:groupA",
                provenance=Provenance(
                    origin_kind=OriginKind.EXPERIMENT, acquisition_mode=AcquisitionMode.IMPORTED
                ),
            )
        ],
        warnings=["example"],
    )
    restored = LiteratureEvidenceBundle.model_validate(bundle.model_dump(mode="json"))
    assert restored == bundle
    assert restored.canonical_runs[0].provenance.acquisition_mode is AcquisitionMode.IMPORTED
