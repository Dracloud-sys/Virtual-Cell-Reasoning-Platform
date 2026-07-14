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
    VerificationStatus,
    hash_source_text,
    normalize_doi,
    normalize_title,
)


def test_query_text_must_not_be_blank() -> None:
    with pytest.raises(ValidationError):
        LiteratureQuery(query_text="   ")


def test_max_results_is_bounded() -> None:
    assert LiteratureQuery(query_text="x", max_results=25).max_results == 25
    with pytest.raises(ValidationError):
        LiteratureQuery(query_text="x", max_results=0)
    with pytest.raises(ValidationError):
        LiteratureQuery(query_text="x", max_results=10_000)  # above the cap


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
    ident = ArticleIdentifier(doi=raw)
    assert ident.doi == raw  # original preserved verbatim
    assert ident.normalized_doi == expected


def test_title_normalization() -> None:
    assert normalize_title("TERT & CDK4: Senescence!") == "tert cdk4 senescence"
    assert normalize_title(None) is None


def test_source_locator_hash_and_blank_rejection() -> None:
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
    ).with_hash()
    assert loc.source_text_hash == hash_source_text("TERT 2.4 fold")
    # Hash is deterministic and content-sensitive.
    assert hash_source_text("a") != hash_source_text("b")


def test_candidates_default_to_pending_review() -> None:
    cand = ExtractedMeasurementCandidate(
        measurement_name="TERT",
        value=2.4,
        unit="fold_change",
        source_locator=SourceLocator(
            article=ArticleIdentifier(pmid="1"),
            source_kind=SourceKind.TABLE,
            source_text="TERT 2.4",
        ),
        extraction_method=ExtractionMethod.DETERMINISTIC_TABLE,
    )
    assert cand.verification_status is VerificationStatus.PENDING_REVIEW


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
