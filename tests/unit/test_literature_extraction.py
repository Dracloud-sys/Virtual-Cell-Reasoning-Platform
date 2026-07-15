"""Tests for source-grounded extraction and the acceptance boundary (PR8c-2/3)."""

from __future__ import annotations

import pytest

from virtualcell.literature.contracts import (
    ExtractedClaimCandidate,
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
    StatisticKind,
    StructuredLiteratureExtractor,
    accept_candidates,
    classify_statistic,
    extract_deterministic,
    parse_value_text,
)


@pytest.fixture
def doc(jats_xml, article_identifier):
    return parse_jats(jats_xml, article=article_identifier, provider="europe_pmc")


def _table_doc(article, table_html: str):
    xml = (
        f'<article><back><table-wrap id="T1"><table>{table_html}</table>'
        "</table-wrap></back></article>"
    )
    return parse_jats(xml, article=article)


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
        ("1,234", None, None, None, None, "unparsed"),  # ambiguous separator
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


def test_qualitative_text_stays_unparsed_and_never_gains_a_number() -> None:
    # Policy: qualitative cell text is preserved as an UNPARSED measurement candidate.
    # It never gains a number and never becomes an ESTABLISHED claim.
    for text in ("increased", "NS"):
        parsed = parse_value_text(text)
        assert parsed.parsed_value is None
        assert parsed.parse_status is ParseStatus.UNPARSED


def test_ambiguous_thousands_separator_is_not_guessed() -> None:
    parsed = parse_value_text("1,234")
    assert parsed.parsed_value is None  # 1.234 or 1234? refuse to guess
    assert parsed.raw_value == "1,234"


def test_comparator_is_not_stored_as_a_point_estimate() -> None:
    parsed = parse_value_text("<0.05")
    assert parsed.comparator == "<" and parsed.parsed_value == 0.05  # bound, not a value


# --- statistical column classification ---------------------------------------


@pytest.mark.parametrize(
    "label,kind",
    [
        ("P value", StatisticKind.P_VALUE),
        ("p-value", StatisticKind.P_VALUE),
        ("p", StatisticKind.P_VALUE),
        ("adjusted p-value", StatisticKind.ADJUSTED_P_VALUE),
        ("p.adj", StatisticKind.ADJUSTED_P_VALUE),
        ("q-value", StatisticKind.Q_VALUE_FDR),
        ("FDR", StatisticKind.Q_VALUE_FDR),
        ("95% CI", StatisticKind.CONFIDENCE_INTERVAL),
        ("n", StatisticKind.SAMPLE_SIZE),
        ("SD", StatisticKind.DISPERSION),
        ("SEM", StatisticKind.DISPERSION),
        ("TERT", None),
        ("P35", None),  # a passage label, not a p-value
        ("Control", None),
    ],
)
def test_classify_statistic(label, kind) -> None:
    assert classify_statistic(label) is kind


def test_statistical_column_is_not_extracted_as_a_measurement(article_identifier) -> None:
    doc = _table_doc(
        article_identifier,
        "<thead><tr><th>Marker</th><th>Control</th><th>P value</th></tr></thead>"
        "<tbody><tr><td>TERT</td><td>2.4</td><td>0.03</td></tr></tbody>",
    )
    result = extract_deterministic(doc, ExtractionTask(target_measurements=["TERT"]))
    assert [(m.sample_group, m.parsed_value) for m in result.measurements] == [("Control", 2.4)]
    assert any("p_value" in w for w in result.warnings)


@pytest.mark.parametrize("column", ["adjusted p-value", "q-value", "FDR", "n", "95% CI"])
def test_other_statistic_columns_are_excluded(article_identifier, column) -> None:
    doc = _table_doc(
        article_identifier,
        f"<thead><tr><th>Marker</th><th>Control</th><th>{column}</th></tr></thead>"
        "<tbody><tr><td>TERT</td><td>2.4</td><td>0.01</td></tr></tbody>",
    )
    result = extract_deterministic(doc, ExtractionTask(target_measurements=["TERT"]))
    assert [m.sample_group for m in result.measurements] == ["Control"]


def test_sd_and_sem_are_not_standalone_measurements(article_identifier) -> None:
    doc = _table_doc(
        article_identifier,
        "<thead><tr><th>Marker</th><th>Mean</th><th>SD</th><th>SEM</th></tr></thead>"
        "<tbody><tr><td>TERT</td><td>2.4</td><td>0.3</td><td>0.1</td></tr></tbody>",
    )
    result = extract_deterministic(doc, ExtractionTask(target_measurements=["TERT"]))
    assert [m.sample_group for m in result.measurements] == ["Mean"]


def test_explicitly_targeting_a_statistic_records_it_as_a_statistic(article_identifier) -> None:
    # If the caller really does target a p-value axis it is extracted, but labelled a
    # statistic — never passed off as a biological measurement.
    doc = _table_doc(
        article_identifier,
        "<thead><tr><th>Marker</th><th>P value</th></tr></thead>"
        "<tbody><tr><td>TERT</td><td>0.03</td></tr></tbody>",
    )
    result = extract_deterministic(doc, ExtractionTask(target_measurements=["P value"]))
    assert len(result.measurements) == 1
    assert result.measurements[0].statistic == "p_value"
    assert result.measurements[0].sample_group == "TERT"


# --- deterministic extraction ------------------------------------------------


def test_extraction_is_targeted_not_every_number(doc) -> None:
    result = extract_deterministic(doc, ExtractionTask(target_measurements=["TERT"]))
    assert {m.measurement_name for m in result.measurements} == {"TERT"}


def test_no_targets_extracts_nothing(doc) -> None:
    result = extract_deterministic(doc, ExtractionTask())
    assert result.measurements == []
    assert any("no target_measurements" in w for w in result.warnings)


def test_target_contexts_are_reserved_and_reported_not_silently_ignored(doc) -> None:
    result = extract_deterministic(doc, _task(target_contexts=["bovine preadipocyte"]))
    assert any("target_contexts is reserved" in w for w in result.warnings)


def test_deterministic_candidates_carry_exact_coordinates(doc) -> None:
    result = extract_deterministic(doc, _task())
    tert = next(
        m for m in result.measurements if m.measurement_name == "TERT" and m.sample_group == "P35"
    )
    assert tert.parsed_value == 2.4
    loc = tert.source_locator
    assert loc.table_id == "T1" and loc.row_index == 0 and loc.column_index == 2
    assert loc.row_label == "TERT" and loc.column_label == "P35"
    assert loc.source_text == "2.4" and loc.source_text_hash


def test_uncertainty_and_qualitative_cells_are_preserved(doc) -> None:
    result = extract_deterministic(doc, _task())
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


def test_candidates_have_no_verification_status() -> None:
    assert "verification_status" not in ExtractedMeasurementCandidate.model_fields


def test_max_candidates_is_bounded(doc) -> None:
    result = extract_deterministic(doc, _task(max_candidates=1))
    assert len(result.measurements) == 1
    assert any("max_candidates" in w for w in result.warnings)


@pytest.mark.parametrize("bad", [0, -1, 10_000])
def test_max_candidates_bounds_are_validated(bad) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractionTask(target_measurements=["TERT"], max_candidates=bad)


# --- acceptance boundary (extraction integrity) ------------------------------


def _candidate(article, source_text: str, parsed_value: float | None = None, **loc_over):
    loc_kw = dict(
        article=article, source_kind=SourceKind.TABLE, table_id="T1", source_text=source_text
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


@pytest.fixture
def ambiguous_doc(article_identifier):
    """Two cells share the value 2.4 — only exact coordinates tell them apart."""
    return _table_doc(
        article_identifier,
        "<thead><tr><th>Marker</th><th>A</th><th>B</th></tr></thead>"
        "<tbody><tr><td>TERT</td><td>2.4</td><td>9</td></tr>"
        "<tr><td>CDK4</td><td>8</td><td>2.4</td></tr></tbody>",
    )


def test_deterministic_candidates_all_pass_acceptance(doc) -> None:
    result = extract_deterministic(doc, _task())
    accepted, rejected = accept_candidates(doc, result)
    assert rejected == []
    assert len(accepted.measurements) == len(result.measurements)


def test_exact_same_cell_locator_is_accepted(doc, article_identifier) -> None:
    good = _candidate(
        article_identifier,
        "2.4",
        2.4,
        row_index=0,
        column_index=2,
        row_label="TERT",
        column_label="P35",
    )
    accepted, rejected = accept_candidates(doc, LiteratureExtractionResult(measurements=[good]))
    assert len(accepted.measurements) == 1 and rejected == []


def test_locator_combining_different_cells_is_rejected(ambiguous_doc, article_identifier) -> None:
    # "2.4" is real and column "B" is real, but TERT/B is 9 — the constraints hold on
    # *different* cells, so the locator must be rejected.
    forged = _candidate(article_identifier, "2.4", 2.4, row_label="TERT", column_label="B")
    accepted, rejected = accept_candidates(
        ambiguous_doc, LiteratureExtractionResult(measurements=[forged])
    )
    assert accepted.measurements == []
    assert any("no single cell" in r for r in rejected)


def test_duplicate_values_are_distinguished_by_coordinates(
    ambiguous_doc, article_identifier
) -> None:
    tert_a = _candidate(
        article_identifier,
        "2.4",
        2.4,
        row_index=0,
        column_index=1,
        row_label="TERT",
        column_label="A",
    )
    cdk4_b = _candidate(
        article_identifier,
        "2.4",
        2.4,
        row_index=1,
        column_index=2,
        row_label="CDK4",
        column_label="B",
    )
    accepted, rejected = accept_candidates(
        ambiguous_doc, LiteratureExtractionResult(measurements=[tert_a, cdk4_b])
    )
    assert len(accepted.measurements) == 2 and rejected == []


def test_tampered_coordinates_are_rejected(ambiguous_doc, article_identifier) -> None:
    # Right text/labels for TERT/A, but pointing at CDK4/B's coordinates.
    forged = _candidate(
        article_identifier,
        "2.4",
        2.4,
        row_index=1,
        column_index=2,
        row_label="TERT",
        column_label="A",
    )
    accepted, _ = accept_candidates(
        ambiguous_doc, LiteratureExtractionResult(measurements=[forged])
    )
    assert accepted.measurements == []


def test_partial_coordinates_are_rejected(doc, article_identifier) -> None:
    forged = _candidate(article_identifier, "2.4", 2.4, row_index=0)  # no column_index
    accepted, rejected = accept_candidates(doc, LiteratureExtractionResult(measurements=[forged]))
    assert accepted.measurements == []
    assert any("both row_index and column_index" in r for r in rejected)


def test_wrong_row_label_is_rejected(doc, article_identifier) -> None:
    forged = _candidate(article_identifier, "2.4", 2.4, row_label="CDK4")
    accepted, _ = accept_candidates(doc, LiteratureExtractionResult(measurements=[forged]))
    assert accepted.measurements == []


def test_wrong_column_label_is_rejected(doc, article_identifier) -> None:
    forged = _candidate(article_identifier, "2.4", 2.4, row_label="TERT", column_label="P3")
    accepted, _ = accept_candidates(doc, LiteratureExtractionResult(measurements=[forged]))
    assert accepted.measurements == []


def test_fabricated_source_text_is_rejected(doc, article_identifier) -> None:
    result = LiteratureExtractionResult(measurements=[_candidate(article_identifier, "9.9", 9.9)])
    accepted, _ = accept_candidates(doc, result)
    assert accepted.measurements == []


def test_unknown_table_id_is_rejected(doc, article_identifier) -> None:
    result = LiteratureExtractionResult(
        measurements=[_candidate(article_identifier, "2.4", 2.4, table_id="T99")]
    )
    _, rejected = accept_candidates(doc, result)
    assert any("unknown table_id" in r for r in rejected)


def test_hallucinated_number_not_in_the_cited_span_is_rejected(doc, article_identifier) -> None:
    result = LiteratureExtractionResult(measurements=[_candidate(article_identifier, "2.4", 9.9)])
    accepted, rejected = accept_candidates(doc, result)
    assert accepted.measurements == []
    assert any("does not appear in the cited source text" in r for r in rejected)


# --- source-kind anchoring ----------------------------------------------------


def _claim(article, text: str, kind: SourceKind, **loc_over):
    loc_kw = dict(article=article, source_kind=kind, source_text=text)
    loc_kw.update(loc_over)
    return ExtractedClaimCandidate(
        subject="TERT",
        predicate="increased",
        object="after long-term culture",
        extraction_method=ExtractionMethod.LLM_STRUCTURED,
        source_locator=SourceLocator(**loc_kw),
    )


def test_abstract_locator_is_checked_against_the_abstract_only(doc, article_identifier) -> None:
    ok = _claim(article_identifier, "TERT expression increased", SourceKind.ABSTRACT)
    accepted, _ = accept_candidates(doc, LiteratureExtractionResult(claims=[ok]))
    assert len(accepted.claims) == 1
    # Text that lives in a section, not the abstract, must not pass as an abstract span.
    bad = _claim(article_identifier, "Cells escaped senescence", SourceKind.ABSTRACT)
    accepted, rejected = accept_candidates(doc, LiteratureExtractionResult(claims=[bad]))
    assert accepted.claims == [] and any("abstract" in r for r in rejected)


def test_section_locator_must_name_the_right_section(doc, article_identifier) -> None:
    ok = _claim(
        article_identifier,
        "Cells escaped senescence",
        SourceKind.SECTION,
        section_title="Discussion",
    )
    accepted, _ = accept_candidates(doc, LiteratureExtractionResult(claims=[ok]))
    assert len(accepted.claims) == 1
    # Real text, but attributed to the wrong section.
    wrong = _claim(
        article_identifier, "Cells escaped senescence", SourceKind.SECTION, section_title="Results"
    )
    accepted, rejected = accept_candidates(doc, LiteratureExtractionResult(claims=[wrong]))
    assert accepted.claims == [] and any("not found in section" in r for r in rejected)


def test_section_locator_without_a_section_title_is_rejected(doc, article_identifier) -> None:
    bad = _claim(article_identifier, "Cells escaped senescence", SourceKind.SECTION)
    accepted, rejected = accept_candidates(doc, LiteratureExtractionResult(claims=[bad]))
    assert accepted.claims == [] and any("section_title" in r for r in rejected)


@pytest.mark.parametrize("kind", [SourceKind.FIGURE, SourceKind.SUPPLEMENTARY])
def test_unsupported_source_kinds_are_rejected(doc, article_identifier, kind) -> None:
    bad = _claim(article_identifier, "TERT expression increased", kind)
    accepted, rejected = accept_candidates(doc, LiteratureExtractionResult(claims=[bad]))
    assert accepted.claims == []
    assert any("not supported by the current parser" in r for r in rejected)


# --- structured LLM boundary --------------------------------------------------


class _FakeExtractor:
    """A fake structured extractor — no LLM, no network."""

    name = "fake_structured"

    def __init__(self, result: LiteratureExtractionResult) -> None:
        self._result = result

    def extract(self, document, task) -> LiteratureExtractionResult:
        return self._result


def test_fake_extractor_satisfies_the_protocol() -> None:
    assert isinstance(_FakeExtractor(LiteratureExtractionResult()), StructuredLiteratureExtractor)


def test_llm_candidates_must_pass_the_same_acceptance_boundary(doc, article_identifier) -> None:
    good = _candidate(
        article_identifier,
        "2.4",
        2.4,
        row_index=0,
        column_index=2,
        row_label="TERT",
        column_label="P35",
    )
    bad = _candidate(article_identifier, "9.9", 9.9)  # hallucinated span
    extractor = _FakeExtractor(LiteratureExtractionResult(measurements=[good, bad]))
    accepted, rejected = accept_candidates(doc, extractor.extract(doc, _task()))
    assert [m.parsed_value for m in accepted.measurements] == [2.4]
    assert len(rejected) == 1
