"""Tests for source-grounded extraction and the acceptance boundary (PR8c-2/3)."""

from __future__ import annotations

import pytest
from tests.unit.test_literature_documents import _ARTICLE, JATS

from virtualcell.literature.contracts import (
    ExtractedMeasurementCandidate,
    ExtractionMethod,
    ParseStatus,
    SourceKind,
    SourceLocator,
)
from virtualcell.literature.documents import parse_jats
from virtualcell.literature.extraction import (
    ExtractionTask,
    LiteratureExtractionResult,
    StructuredLiteratureExtractor,
    accept_candidates,
    extract_deterministic,
    parse_value_text,
)


def _doc():
    return parse_jats(JATS, article=_ARTICLE, provider="europe_pmc")


def _task(**over) -> ExtractionTask:
    kw = {"target_measurements": ["TERT", "CDK4", "SA_b_gal"]}
    kw.update(over)
    return ExtractionTask(**kw)


# --- value parsing -----------------------------------------------------------


@pytest.mark.parametrize(
    "text,value,comparator,uncertainty,unit,status",
    [
        ("2.4", 2.4, None, None, None, "parsed"),
        ("2.4-fold", 2.4, None, None, "fold", "parsed"),
        ("2.4 ± 0.3", 2.4, None, 0.3, None, "parsed"),
        ("<0.05", 0.05, "<", None, None, "parsed"),
        ("≥10", 10.0, ">=", None, None, "parsed"),
        ("42 h", 42.0, None, None, "h", "parsed"),
        ("increased", None, None, None, None, "unparsed"),
        ("NS", None, None, None, None, "unparsed"),
    ],
)
def test_parse_value_text(text, value, comparator, uncertainty, unit, status) -> None:
    parsed = parse_value_text(text)
    assert parsed.raw_value == text  # verbatim source always kept
    assert parsed.parsed_value == value
    assert parsed.comparator == comparator
    assert parsed.uncertainty == uncertainty
    assert parsed.unit == unit
    assert parsed.parse_status.value == status


def test_qualitative_text_never_gains_a_number() -> None:
    assert parse_value_text("increased").parsed_value is None
    assert parse_value_text("NS").parsed_value is None


def test_comparator_is_not_stored_as_a_point_estimate() -> None:
    parsed = parse_value_text("<0.05")
    assert parsed.comparator == "<" and parsed.parsed_value == 0.05  # bound, not a value


# --- deterministic extraction ------------------------------------------------


def test_extraction_is_targeted_not_every_number() -> None:
    result = extract_deterministic(_doc(), ExtractionTask(target_measurements=["TERT"]))
    assert {m.measurement_name for m in result.measurements} == {"TERT"}
    # CDK4 / SA_b_gal rows exist in the table but were not requested.
    assert all(m.measurement_name == "TERT" for m in result.measurements)


def test_no_targets_extracts_nothing() -> None:
    result = extract_deterministic(_doc(), ExtractionTask())
    assert result.measurements == []
    assert any("no target_measurements" in w for w in result.warnings)


def test_deterministic_candidates_carry_exact_locators() -> None:
    result = extract_deterministic(_doc(), _task())
    tert = next(
        m for m in result.measurements if m.measurement_name == "TERT" and m.sample_group == "P35"
    )
    assert tert.parsed_value == 2.4
    assert tert.parse_status is ParseStatus.PARSED
    loc = tert.source_locator
    assert loc.source_kind is SourceKind.TABLE
    assert loc.table_id == "T1" and loc.row_label == "TERT" and loc.column_label == "P35"
    assert loc.source_text == "2.4"
    assert loc.source_text_hash  # auto-hashed


def test_uncertainty_and_qualitative_cells_are_preserved() -> None:
    result = extract_deterministic(_doc(), _task())
    cdk4 = next(
        m for m in result.measurements if m.measurement_name == "CDK4" and m.sample_group == "P35"
    )
    assert cdk4.parsed_value == 1.1 and cdk4.uncertainty == 0.2
    sa = next(
        m
        for m in result.measurements
        if m.measurement_name == "SA_b_gal" and m.sample_group == "P35"
    )
    assert sa.raw_value == "increased" and sa.parsed_value is None
    assert sa.parse_status is ParseStatus.UNPARSED


def test_all_candidates_are_unverified_by_construction() -> None:
    result = extract_deterministic(_doc(), _task())
    assert result.measurements
    # Candidates have no status field at all; verification is PR8d's job.
    assert "verification_status" not in ExtractedMeasurementCandidate.model_fields


def test_max_candidates_is_bounded() -> None:
    result = extract_deterministic(_doc(), _task(max_candidates=1))
    assert len(result.measurements) == 1
    assert any("max_candidates" in w for w in result.warnings)


# --- acceptance boundary (extraction integrity) ------------------------------


def _fabricated(source_text: str, parsed_value: float | None = None, **loc_over):
    loc_kw = dict(
        article=_ARTICLE, source_kind=SourceKind.TABLE, table_id="T1", source_text=source_text
    )
    loc_kw.update(loc_over)
    return ExtractedMeasurementCandidate(
        measurement_name="TERT",
        raw_value=source_text,
        parsed_value=parsed_value,
        parse_status=ParseStatus.PARSED if parsed_value is not None else ParseStatus.UNPARSED,
        extraction_method=ExtractionMethod.LLM_STRUCTURED,
        source_locator=SourceLocator(**loc_kw),
    )


def test_deterministic_candidates_all_pass_acceptance() -> None:
    doc = _doc()
    accepted, rejected = accept_candidates(doc, extract_deterministic(doc, _task()))
    assert rejected == []
    assert len(accepted.measurements) == len(extract_deterministic(doc, _task()).measurements)


def test_fabricated_source_text_is_rejected() -> None:
    doc = _doc()
    result = LiteratureExtractionResult(measurements=[_fabricated("9.9", 9.9)])
    accepted, rejected = accept_candidates(doc, result)
    assert accepted.measurements == []
    assert any("source_text not found" in r for r in rejected)


def test_unknown_table_id_is_rejected() -> None:
    doc = _doc()
    result = LiteratureExtractionResult(measurements=[_fabricated("2.4", 2.4, table_id="T99")])
    accepted, rejected = accept_candidates(doc, result)
    assert accepted.measurements == []
    assert any("unknown table_id" in r for r in rejected)


def test_hallucinated_number_not_in_the_cited_span_is_rejected() -> None:
    # The locator cites a real cell ("2.4") but the candidate claims 9.9.
    doc = _doc()
    result = LiteratureExtractionResult(measurements=[_fabricated("2.4", 9.9)])
    accepted, rejected = accept_candidates(doc, result)
    assert accepted.measurements == []
    assert any("does not appear in the cited source text" in r for r in rejected)


def test_wrong_row_label_is_rejected() -> None:
    doc = _doc()
    result = LiteratureExtractionResult(measurements=[_fabricated("2.4", 2.4, row_label="CDK4")])
    accepted, rejected = accept_candidates(doc, result)
    assert accepted.measurements == []
    assert any("row_label" in r for r in rejected)


# --- structured LLM boundary --------------------------------------------------


class _FakeExtractor:
    """A fake structured extractor — no LLM, no network."""

    name = "fake_structured"

    def __init__(self, result: LiteratureExtractionResult) -> None:
        self._result = result

    def extract(self, document, task) -> LiteratureExtractionResult:
        return self._result


def test_fake_extractor_satisfies_the_protocol() -> None:
    extractor = _FakeExtractor(LiteratureExtractionResult())
    assert isinstance(extractor, StructuredLiteratureExtractor)


def test_llm_candidates_must_pass_the_same_acceptance_boundary() -> None:
    doc = _doc()
    good = _fabricated("2.4", 2.4, row_label="TERT", column_label="P35")
    bad = _fabricated("9.9", 9.9)  # hallucinated span
    extractor = _FakeExtractor(LiteratureExtractionResult(measurements=[good, bad]))
    accepted, rejected = accept_candidates(doc, extractor.extract(doc, _task()))
    assert [m.parsed_value for m in accepted.measurements] == [2.4]
    assert len(rejected) == 1
