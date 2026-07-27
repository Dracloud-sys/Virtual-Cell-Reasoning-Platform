"""Tests for the deterministic literature verification gate (PR8d-1)."""

from __future__ import annotations

from datetime import UTC, datetime
from xml.sax.saxutils import escape

import pytest

from virtualcell.literature.contracts import (
    AuthorInterpretationCandidate,
    CandidateKind,
    ExtractedClaimCandidate,
    ExtractedMeasurementCandidate,
    ExtractionMethod,
    ParseStatus,
    SourceKind,
    SourceLocator,
    VerificationStatus,
)
from virtualcell.literature.documents import parse_jats
from virtualcell.literature.extraction import (
    ExtractionTask,
    LiteratureExtractionResult,
    extract_deterministic,
    parse_value_text,
)
from virtualcell.literature.verification import METHOD, VERIFIER, verify_candidates

_FIXED_CLOCK = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


@pytest.fixture
def document(jats_xml, article_identifier):
    return parse_jats(jats_xml, article=article_identifier, provider="europe_pmc")


def _verify_one(document, *, measurements=(), claims=(), interpretations=(), targets=("TERT",)):
    decisions = verify_candidates(
        document,
        LiteratureExtractionResult(
            measurements=list(measurements),
            claims=list(claims),
            author_interpretations=list(interpretations),
        ),
        ExtractionTask(target_measurements=list(targets)),
        verified_at=_FIXED_CLOCK,
    )
    assert len(decisions) == 1
    return decisions[0]


def _tert_p35(document, *, method=ExtractionMethod.LLM_STRUCTURED, **overrides):
    """A candidate for the exact TERT/P35 = 2.4 cell of the sample table."""
    fields = {
        "measurement_name": "TERT",
        "sample_group": "P35",
        "raw_value": "2.4",
        "parsed_value": 2.4,
        "parse_status": ParseStatus.PARSED,
        "extraction_method": method,
        "source_locator": SourceLocator(
            article=document.article,
            source_kind=SourceKind.TABLE,
            table_id="T1",
            row_index=0,
            column_index=2,
            row_label="TERT",
            column_label="P35",
            source_text="2.4",
        ),
    }
    fields.update(overrides)
    return ExtractedMeasurementCandidate(**fields)


def _prose_doc(article, abstract: str):
    return parse_jats(
        f"<article><front><article-meta><abstract><p>{escape(abstract)}</p>"
        "</abstract></article-meta></front></article>",
        article=article,
    )


def _prose_measurement(article, source_text: str, raw_value: str, *, name="TERT"):
    parsed = parse_value_text(raw_value)
    return ExtractedMeasurementCandidate(
        measurement_name=name,
        raw_value=raw_value,
        parsed_value=parsed.parsed_value,
        comparator=parsed.comparator,
        uncertainty=parsed.uncertainty,
        unit=parsed.unit,
        parse_status=parsed.parse_status,
        extraction_method=ExtractionMethod.LLM_STRUCTURED,
        source_locator=SourceLocator(
            article=article, source_kind=SourceKind.ABSTRACT, source_text=source_text
        ),
    )


# --- MACHINE_VERIFIED --------------------------------------------------------


def test_exact_table_measurement_is_machine_verified(document) -> None:
    result = extract_deterministic(document, ExtractionTask(target_measurements=["TERT"]))
    tert_p35 = next(m for m in result.measurements if m.sample_group == "P35")
    decision = _verify_one(document, measurements=[tert_p35])
    assert decision.status is VerificationStatus.MACHINE_VERIFIED
    assert decision.candidate_kind is CandidateKind.MEASUREMENT
    assert decision.verifier == VERIFIER and decision.method == METHOD


def test_deterministic_table_candidate_is_machine_verified(document) -> None:
    result = extract_deterministic(document, ExtractionTask(target_measurements=["TERT"]))
    for candidate in result.measurements:  # TERT/P3 = 1.0 and TERT/P35 = 2.4
        decision = _verify_one(document, measurements=[candidate])
        assert decision.status is VerificationStatus.MACHINE_VERIFIED


def test_structured_llm_measurement_passing_exact_cell_is_machine_verified(document) -> None:
    llm = _tert_p35(document, method=ExtractionMethod.LLM_STRUCTURED)
    decision = _verify_one(document, measurements=[llm])
    assert decision.status is VerificationStatus.MACHINE_VERIFIED


# --- PENDING_REVIEW ----------------------------------------------------------


def test_prose_measurement_is_pending_review(article_identifier) -> None:
    doc = _prose_doc(article_identifier, "TERT reached 2.4-fold after culture.")
    cand = _prose_measurement(
        article_identifier, "TERT reached 2.4-fold after culture.", "2.4-fold"
    )
    decision = _verify_one(doc, measurements=[cand])
    assert decision.status is VerificationStatus.PENDING_REVIEW
    assert any("prose" in r for r in decision.reasons)


def test_unparsed_qualitative_measurement_is_pending_review(document) -> None:
    result = extract_deterministic(document, ExtractionTask(target_measurements=["SA_b_gal"]))
    qualitative = next(m for m in result.measurements if m.parse_status is ParseStatus.UNPARSED)
    decision = _verify_one(document, measurements=[qualitative], targets=("SA_b_gal",))
    assert decision.status is VerificationStatus.PENDING_REVIEW
    assert any("qualitative" in r for r in decision.reasons)


def test_statistic_tagged_measurement_is_pending_review(article_identifier) -> None:
    doc = parse_jats(
        '<article><back><table-wrap id="T1"><table>'
        "<thead><tr><th>Marker</th><th>P value</th></tr></thead>"
        "<tbody><tr><td>TERT</td><td>0.03</td></tr></tbody>"
        "</table></table-wrap></back></article>",
        article=article_identifier,
    )
    result = extract_deterministic(doc, ExtractionTask(target_measurements=["P value"]))
    statistic = result.measurements[0]
    assert statistic.statistic == "p_value"
    decision = _verify_one(doc, measurements=[statistic], targets=("P value",))
    assert decision.status is VerificationStatus.PENDING_REVIEW
    assert any("statistic" in r for r in decision.reasons)


def test_claim_is_pending_review(document) -> None:
    claim = ExtractedClaimCandidate(
        subject="TERT",
        predicate="increased",
        object="after culture",
        extraction_method=ExtractionMethod.LLM_STRUCTURED,
        source_locator=SourceLocator(
            article=document.article,
            source_kind=SourceKind.ABSTRACT,
            source_text="TERT expression",
        ),
    )
    decision = _verify_one(document, claims=[claim])
    assert decision.status is VerificationStatus.PENDING_REVIEW
    assert decision.candidate_kind is CandidateKind.CLAIM
    assert any("claim" in r for r in decision.reasons)


def test_author_interpretation_is_pending_review(document) -> None:
    interp = AuthorInterpretationCandidate(
        statement="Cells escaped senescence.",
        extraction_method=ExtractionMethod.LLM_STRUCTURED,
        source_locator=SourceLocator(
            article=document.article,
            source_kind=SourceKind.SECTION,
            section_title="Discussion",
            source_text="Cells escaped senescence.",
        ),
    )
    decision = _verify_one(document, interpretations=[interp])
    assert decision.status is VerificationStatus.PENDING_REVIEW
    assert decision.candidate_kind is CandidateKind.AUTHOR_INTERPRETATION
    assert any("interpretation" in r for r in decision.reasons)


# --- REJECTED (source-integrity failures, never softened to pending) ---------


def test_stale_missing_source_text_is_rejected(article_identifier) -> None:
    doc = _prose_doc(article_identifier, "TERT reached 2.4-fold after culture.")
    cand = _prose_measurement(article_identifier, "a sentence absent from the abstract 2.4", "2.4")
    decision = _verify_one(doc, measurements=[cand])
    assert decision.status is VerificationStatus.REJECTED


def test_wrong_table_coordinates_is_rejected(document) -> None:
    wrong = _tert_p35(
        document,
        source_locator=SourceLocator(
            article=document.article,
            source_kind=SourceKind.TABLE,
            table_id="T1",
            row_index=1,  # CDK4 row, not TERT
            column_index=2,
            row_label="TERT",
            column_label="P35",
            source_text="2.4",
        ),
    )
    decision = _verify_one(document, measurements=[wrong])
    assert decision.status is VerificationStatus.REJECTED


def test_wrong_row_column_label_is_rejected(document) -> None:
    wrong = _tert_p35(
        document,
        source_locator=SourceLocator(
            article=document.article,
            source_kind=SourceKind.TABLE,
            table_id="T1",
            row_index=0,
            column_index=2,
            row_label="CDK4",  # real label is TERT
            column_label="P35",
            source_text="2.4",
        ),
    )
    decision = _verify_one(document, measurements=[wrong])
    assert decision.status is VerificationStatus.REJECTED


def test_raw_parsed_mismatch_is_rejected(document) -> None:
    wrong = _tert_p35(document, parsed_value=9.9)  # cell says 2.4
    decision = _verify_one(document, measurements=[wrong])
    assert decision.status is VerificationStatus.REJECTED


def test_target_binding_mismatch_is_rejected(document) -> None:
    tert = _tert_p35(document)
    decision = _verify_one(document, measurements=[tert], targets=("CDK4",))  # TERT not requested
    assert decision.status is VerificationStatus.REJECTED


def test_unsupported_numeric_notation_is_rejected(article_identifier) -> None:
    doc = _prose_doc(article_identifier, "TERT was −1.2e−4 M in the assay.")
    cand = _prose_measurement(article_identifier, "TERT was −1.2e−4 M in the assay.", "1.2")
    decision = _verify_one(doc, measurements=[cand])
    assert decision.status is VerificationStatus.REJECTED


# --- decision provenance, determinism, purity --------------------------------


def test_source_text_hash_is_recorded(document) -> None:
    tert = _tert_p35(document)
    decision = _verify_one(document, measurements=[tert])
    assert decision.source_text_hash == tert.source_locator.source_text_hash
    assert decision.source_text_hash is not None


def test_verified_at_is_timezone_aware(document) -> None:
    decision = verify_candidates(
        document,
        LiteratureExtractionResult(measurements=[_tert_p35(document)]),
        ExtractionTask(target_measurements=["TERT"]),
    )[0]
    assert decision.verified_at.tzinfo is not None
    assert decision.verified_at.tzinfo.utcoffset(decision.verified_at) is not None


def test_injected_clock_is_reproducible(document) -> None:
    tert = _tert_p35(document)
    first = _verify_one(document, measurements=[tert])
    second = _verify_one(document, measurements=[tert])
    assert first.verified_at == second.verified_at == _FIXED_CLOCK


def test_exactly_one_decision_per_candidate(document) -> None:
    tert = _tert_p35(document)
    decisions = verify_candidates(
        document,
        LiteratureExtractionResult(measurements=[tert, tert]),  # same id twice
        ExtractionTask(target_measurements=["TERT"]),
        verified_at=_FIXED_CLOCK,
    )
    assert len(decisions) == 1


def test_input_candidate_is_not_mutated(document) -> None:
    tert = _tert_p35(document)
    before = tert.model_dump()
    verify_candidates(
        document,
        LiteratureExtractionResult(measurements=[tert]),
        ExtractionTask(target_measurements=["TERT"]),
        verified_at=_FIXED_CLOCK,
    )
    assert tert.model_dump() == before


def test_decisions_are_ordered_and_reference_real_ids(document) -> None:
    tert = _tert_p35(document)
    claim = ExtractedClaimCandidate(
        subject="TERT",
        predicate="increased",
        object="after culture",
        extraction_method=ExtractionMethod.LLM_STRUCTURED,
        source_locator=SourceLocator(
            article=document.article,
            source_kind=SourceKind.ABSTRACT,
            source_text="TERT expression",
        ),
    )
    decisions = verify_candidates(
        document,
        LiteratureExtractionResult(measurements=[tert], claims=[claim]),
        ExtractionTask(target_measurements=["TERT"]),
        verified_at=_FIXED_CLOCK,
    )
    assert [d.candidate_id for d in decisions] == [tert.candidate_id, claim.candidate_id]
    assert [d.candidate_kind for d in decisions] == [
        CandidateKind.MEASUREMENT,
        CandidateKind.CLAIM,
    ]
