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


def _candidate(
    article,
    source_text: str,
    parsed_value: float | None = None,
    *,
    measurement_name: str = "TERT",
    sample_group: str | None = None,
    **loc_over,
):
    loc_kw = dict(
        article=article, source_kind=SourceKind.TABLE, table_id="T1", source_text=source_text
    )
    loc_kw.update(loc_over)
    return ExtractedMeasurementCandidate(
        measurement_name=measurement_name,
        sample_group=sample_group,
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
    # The locator cites the real "2.4" cell but the candidate claims 9.9 — a
    # conservative re-parse of the raw value disagrees.
    result = LiteratureExtractionResult(measurements=[_candidate(article_identifier, "2.4", 9.9)])
    accepted, rejected = accept_candidates(doc, result)
    assert accepted.measurements == []
    assert any("parsed_value disagrees" in r for r in rejected)


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


# --- task-aware acceptance (target boundary for every extractor) -------------


def test_deterministic_candidates_pass_the_task_gate(doc) -> None:
    result = extract_deterministic(doc, _task())
    accepted, rejected = accept_candidates(doc, result, _task())
    assert rejected == []
    assert len(accepted.measurements) == len(result.measurements)


def test_unrequested_measurement_name_is_rejected(doc, article_identifier) -> None:
    forged = _candidate(
        article_identifier,
        "2.4",
        2.4,
        measurement_name="NOT_REQUESTED",
        row_index=0,
        column_index=2,
        row_label="TERT",
        column_label="P35",
    )
    accepted, rejected = accept_candidates(
        doc,
        LiteratureExtractionResult(measurements=[forged]),
        ExtractionTask(target_measurements=["TERT"]),
    )
    assert accepted.measurements == []
    assert any("not a requested target" in r for r in rejected)


def test_measurement_name_not_matching_the_cited_cell_is_rejected(doc, article_identifier) -> None:
    # CDK4 is a requested target, but the cited cell is TERT/P35.
    forged = _candidate(
        article_identifier,
        "2.4",
        2.4,
        measurement_name="CDK4",
        row_index=0,
        column_index=2,
        row_label="TERT",
        column_label="P35",
    )
    accepted, rejected = accept_candidates(
        doc,
        LiteratureExtractionResult(measurements=[forged]),
        ExtractionTask(target_measurements=["TERT", "CDK4"]),
    )
    assert accepted.measurements == []
    assert any("does not match the cited cell" in r for r in rejected)


def test_fabricated_sample_group_is_rejected(doc, article_identifier) -> None:
    forged = _candidate(
        article_identifier,
        "2.4",
        2.4,
        sample_group="fabricated",
        row_index=0,
        column_index=2,
        row_label="TERT",
        column_label="P35",
    )
    accepted, rejected = accept_candidates(
        doc, LiteratureExtractionResult(measurements=[forged]), _task()
    )
    assert accepted.measurements == []
    assert any("sample_group does not match" in r for r in rejected)


def test_row_oriented_target_is_accepted(doc, article_identifier) -> None:
    good = _candidate(
        article_identifier,
        "2.4",
        2.4,
        sample_group="P35",
        row_index=0,
        column_index=2,
        row_label="TERT",
        column_label="P35",
    )
    accepted, rejected = accept_candidates(
        doc,
        LiteratureExtractionResult(measurements=[good]),
        ExtractionTask(target_measurements=["TERT"]),
    )
    assert len(accepted.measurements) == 1 and rejected == []


def test_column_oriented_target_is_accepted(article_identifier) -> None:
    # Table with markers as COLUMNS and groups as rows.
    doc = _table_doc(
        article_identifier,
        "<thead><tr><th>Group</th><th>TERT</th></tr></thead>"
        "<tbody><tr><td>P35</td><td>2.4</td></tr></tbody>",
    )
    good = ExtractedMeasurementCandidate(
        measurement_name="TERT",
        sample_group="P35",
        raw_value="2.4",
        parsed_value=2.4,
        parse_status=ParseStatus.PARSED,
        extraction_method=ExtractionMethod.LLM_STRUCTURED,
        source_locator=SourceLocator(
            article=article_identifier,
            source_kind=SourceKind.TABLE,
            table_id="T1",
            row_index=0,
            column_index=1,
            row_label="P35",
            column_label="TERT",
            source_text="2.4",
        ),
    )
    accepted, rejected = accept_candidates(
        doc,
        LiteratureExtractionResult(measurements=[good]),
        ExtractionTask(target_measurements=["TERT"]),
    )
    assert len(accepted.measurements) == 1 and rejected == []


def test_explicit_statistic_target_passes_the_task_gate(article_identifier) -> None:
    doc = _table_doc(
        article_identifier,
        "<thead><tr><th>Marker</th><th>P value</th></tr></thead>"
        "<tbody><tr><td>TERT</td><td>0.03</td></tr></tbody>",
    )
    result = extract_deterministic(doc, ExtractionTask(target_measurements=["P value"]))
    accepted, rejected = accept_candidates(
        doc, result, ExtractionTask(target_measurements=["P value"])
    )
    assert len(accepted.measurements) == 1 and rejected == []
    assert accepted.measurements[0].statistic == "p_value"


# --- value integrity (parse contract enforced on every extractor) ------------


def _valued(article, *, source_text, table_html=None, **fields):
    """Build a measurement candidate citing a single-cell table, with value fields
    controllable so an LLM's bypass attempts can be exercised."""
    from xml.sax.saxutils import escape

    html = table_html or (
        "<thead><tr><th>Marker</th><th>P35</th></tr></thead>"
        f"<tbody><tr><td>TERT</td><td>{escape(source_text)}</td></tr></tbody>"
    )
    doc = _table_doc(article, html)
    kw = dict(
        measurement_name="TERT",
        raw_value=source_text,
        parse_status=ParseStatus.PARSED,
        extraction_method=ExtractionMethod.LLM_STRUCTURED,
        source_locator=SourceLocator(
            article=article,
            source_kind=SourceKind.TABLE,
            table_id="T1",
            row_index=0,
            column_index=1,
            row_label="TERT",
            column_label="P35",
            source_text=source_text,
        ),
    )
    kw.update(fields)
    return doc, ExtractedMeasurementCandidate(**kw)


def _rejected(doc, candidate) -> list[str]:
    accepted, rejected = accept_candidates(
        doc, LiteratureExtractionResult(measurements=[candidate]), _task()
    )
    assert accepted.measurements == []
    return rejected


def test_fabricated_raw_value_is_rejected(article_identifier) -> None:
    doc, candidate = _valued(
        article_identifier, source_text="2.4", raw_value="fabricated", parsed_value=2.4
    )
    assert any(
        "raw_value does not equal the cited cell text" in r for r in _rejected(doc, candidate)
    )


def test_ambiguous_comma_submitted_as_a_number_is_rejected(article_identifier) -> None:
    # "1,234" must stay UNPARSED for every extractor; claiming 1.0 is rejected.
    doc, candidate = _valued(article_identifier, source_text="1,234", parsed_value=1.0)
    assert any("re-parse" in r for r in _rejected(doc, candidate))


def test_uncertainty_submitted_as_the_primary_value_is_rejected(article_identifier) -> None:
    doc, candidate = _valued(article_identifier, source_text="2.4 ± 0.3", parsed_value=0.3)
    assert any("parsed_value disagrees" in r for r in _rejected(doc, candidate))


def test_tampered_comparator_is_rejected(article_identifier) -> None:
    doc, candidate = _valued(
        article_identifier, source_text="<0.05", parsed_value=0.05, comparator=None
    )
    assert any("comparator disagrees" in r for r in _rejected(doc, candidate))


def test_tampered_unit_is_rejected(article_identifier) -> None:
    doc, candidate = _valued(article_identifier, source_text="42 h", parsed_value=42.0, unit="day")
    assert any("unit disagrees" in r for r in _rejected(doc, candidate))


def test_parse_status_value_contradiction_is_rejected(article_identifier) -> None:
    # parse_status=UNPARSED but a value is present -> re-parse of "increased" disagrees.
    doc, candidate = _valued(
        article_identifier,
        source_text="increased",
        parsed_value=2.4,
        parse_status=ParseStatus.UNPARSED,
    )
    assert _rejected(doc, candidate)


def test_valid_deterministic_and_llm_values_pass(article_identifier) -> None:
    for source, _value in (("2.4", 2.4), ("2.4-fold", 2.4), ("<0.05", 0.05)):
        doc, _ = _valued(article_identifier, source_text=source)
        parsed = parse_value_text(source)
        good = ExtractedMeasurementCandidate(
            measurement_name="TERT",
            raw_value=source,
            parsed_value=parsed.parsed_value,
            comparator=parsed.comparator,
            uncertainty=parsed.uncertainty,
            unit=parsed.unit,
            parse_status=parsed.parse_status,
            extraction_method=ExtractionMethod.LLM_STRUCTURED,
            source_locator=SourceLocator(
                article=article_identifier,
                source_kind=SourceKind.TABLE,
                table_id="T1",
                row_index=0,
                column_index=1,
                row_label="TERT",
                column_label="P35",
                source_text=source,
            ),
        )
        accepted, rejected = accept_candidates(
            doc, LiteratureExtractionResult(measurements=[good]), _task()
        )
        assert len(accepted.measurements) == 1 and rejected == [], (source, rejected)


# --- ambiguous measurement axis ----------------------------------------------


def test_both_axes_matching_is_rejected_in_acceptance(article_identifier) -> None:
    doc = _table_doc(
        article_identifier,
        "<thead><tr><th>Marker</th><th>TERT expression</th></tr></thead>"
        "<tbody><tr><td>TERT</td><td>2.4</td></tr></tbody>",
    )
    candidate = ExtractedMeasurementCandidate(
        measurement_name="TERT",
        raw_value="2.4",
        parsed_value=2.4,
        parse_status=ParseStatus.PARSED,
        extraction_method=ExtractionMethod.LLM_STRUCTURED,
        source_locator=SourceLocator(
            article=article_identifier,
            source_kind=SourceKind.TABLE,
            table_id="T1",
            row_index=0,
            column_index=1,
            row_label="TERT",
            column_label="TERT expression",
            source_text="2.4",
        ),
    )
    accepted, rejected = accept_candidates(
        doc,
        LiteratureExtractionResult(measurements=[candidate]),
        ExtractionTask(target_measurements=["TERT"]),
    )
    assert accepted.measurements == []
    assert any("ambiguous" in r for r in rejected)


def test_both_axes_matching_is_skipped_by_deterministic_extractor(article_identifier) -> None:
    doc = _table_doc(
        article_identifier,
        "<thead><tr><th>Marker</th><th>TERT expression</th></tr></thead>"
        "<tbody><tr><td>TERT</td><td>2.4</td></tr></tbody>",
    )
    result = extract_deterministic(doc, ExtractionTask(target_measurements=["TERT"]))
    assert result.measurements == []
    assert any("both axes" in w for w in result.warnings)


# --- prose value-span boundary + target binding ------------------------------


def _prose_doc(article, abstract: str):
    from xml.sax.saxutils import escape

    return parse_jats(
        f"<article><front><article-meta><abstract><p>{escape(abstract)}</p>"
        "</abstract></article-meta></front></article>",
        article=article,
    )


def _prose_measurement(article, source_text: str, raw_value: str, *, name="TERT"):
    parsed = parse_value_text(raw_value)  # fields must agree with a conservative parse
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


def _prose_accepts(doc, candidate, targets=("TERT",)) -> bool:
    accepted, _ = accept_candidates(
        doc,
        LiteratureExtractionResult(measurements=[candidate]),
        ExtractionTask(target_measurements=list(targets)),
    )
    return bool(accepted.measurements)


def test_prose_partial_number_2_4_inside_12_4_is_rejected(article_identifier) -> None:
    text = "TERT expression was 12.4-fold higher."
    doc = _prose_doc(article_identifier, text)
    assert not _prose_accepts(doc, _prose_measurement(article_identifier, text, "2.4"))


def test_prose_partial_number_0_3_inside_10_3_is_rejected(article_identifier) -> None:
    text = "TERT was 10.3 units."
    doc = _prose_doc(article_identifier, text)
    assert not _prose_accepts(doc, _prose_measurement(article_identifier, text, "0.3"))


def test_prose_valid_fold_span_is_accepted(article_identifier) -> None:
    text = "TERT increased 2.4-fold after culture."
    doc = _prose_doc(article_identifier, text)
    assert _prose_accepts(doc, _prose_measurement(article_identifier, text, "2.4-fold"))


def test_prose_valid_comparator_span_is_accepted(article_identifier) -> None:
    text = "TERT was < 2.4 in controls."
    doc = _prose_doc(article_identifier, text)
    assert _prose_accepts(doc, _prose_measurement(article_identifier, text, "< 2.4"))


def test_prose_valid_uncertainty_span_is_accepted(article_identifier) -> None:
    text = "TERT reached 2.4 ± 0.3 at passage 35."
    doc = _prose_doc(article_identifier, text)
    assert _prose_accepts(doc, _prose_measurement(article_identifier, text, "2.4 ± 0.3"))


def test_prose_independent_span_accepted_despite_a_substring_occurrence(article_identifier) -> None:
    # "2.4" appears both inside "12.4" AND as an independent value — one valid span
    # is enough.
    text = "Baseline 12.4, then TERT reached 2.4 units."
    doc = _prose_doc(article_identifier, text)
    assert _prose_accepts(doc, _prose_measurement(article_identifier, text, "2.4"))


def test_prose_target_not_in_source_is_rejected(article_identifier) -> None:
    # measurement_name is a requested target, but the cited sentence is about CDK4.
    text = "CDK4 expression increased 2.4-fold after passage."
    doc = _prose_doc(article_identifier, text)
    assert not _prose_accepts(doc, _prose_measurement(article_identifier, text, "2.4-fold"))


def test_prose_target_in_source_is_accepted(article_identifier) -> None:
    text = "TERT expression increased 2.4-fold after passage."
    doc = _prose_doc(article_identifier, text)
    assert _prose_accepts(doc, _prose_measurement(article_identifier, text, "2.4-fold"))


def test_prose_target_case_insensitive_match(article_identifier) -> None:
    text = "tert increased 2.4-fold."
    doc = _prose_doc(article_identifier, text)
    assert _prose_accepts(doc, _prose_measurement(article_identifier, text, "2.4-fold"))


def test_prose_target_across_punctuation_matches(article_identifier) -> None:
    text = "TERT-mediated growth reached 2.4-fold."
    doc = _prose_doc(article_identifier, text)
    assert _prose_accepts(doc, _prose_measurement(article_identifier, text, "2.4-fold"))


def test_prose_partial_word_target_is_rejected(article_identifier) -> None:
    # "TERT" only appears inside a larger token; whole-word matching rejects it.
    text = "XTERTY expression reached 2.4-fold."
    doc = _prose_doc(article_identifier, text)
    assert not _prose_accepts(doc, _prose_measurement(article_identifier, text, "2.4-fold"))


def test_prose_multiple_targets_in_span_is_ambiguous_and_rejected(article_identifier) -> None:
    text = "TERT rose 2.4-fold while CDK4 fell."
    doc = _prose_doc(article_identifier, text)
    assert not _prose_accepts(
        doc, _prose_measurement(article_identifier, text, "2.4-fold"), targets=("TERT", "CDK4")
    )


def test_prose_candidate_stays_unverified() -> None:
    assert "verification_status" not in ExtractedMeasurementCandidate.model_fields


# --- complete numeric-token boundary -----------------------------------------


@pytest.mark.parametrize(
    ("source", "raw"),
    [
        ("TERT was 1e-4 M", "4"),  # exponent digit
        ("TERT was 1e-4 M", "-4"),  # signed exponent
        ("TERT was 1e-4 M", "e-4"),  # exponent fragment
        ("TERT was 2.4e10 copies", "10"),  # exponent digits
        ("TERT was 2.4e10 copies", "e10"),  # e + exponent
        ("TERT was 2.4e10 copies", "2.4"),  # mantissa of a sci-notation number
        ("TERT was 12.4-fold", ".4"),  # trailing decimal fragment
        ("TERT was 12.4-fold", "12."),  # leading decimal fragment
        ("TERT was 12.4-fold", "2.4"),  # digit-embedded substring
        ("TERT was 2.40 units", "2.4"),  # truncation of a longer number
        ("TERT n=1234 cells", "24"),  # interior digits
        ("TERT n=1,234 cells", "234"),  # thousands-grouped fragment
        ("TERT was -1.2e-4 M", "-1.2"),  # signed mantissa fragment of sci notation
    ],
)
def test_prose_numeric_token_fragment_is_rejected(article_identifier, source, raw) -> None:
    """A candidate value that covers only part of a complete source number is refused,
    even though ``parse_value_text`` alone would find a number inside it."""
    doc = _prose_doc(article_identifier, source)
    assert not _prose_accepts(doc, _prose_measurement(article_identifier, source, raw))


@pytest.mark.parametrize(
    ("source", "raw"),
    [
        ("TERT was 2.4-fold higher", "2.4-fold"),
        ("TERT was < 2.4-fold", "< 2.4"),
        ("TERT reached 2.4 ± 0.3-fold", "2.4 ± 0.3"),
        ("TERT was -1.2e-4 M", "-1.2e-4"),  # the complete signed sci-notation value
        ("TERT n=1,234 cells", "1,234"),  # the whole thousands-grouped token
        ("Baseline 12.4, then TERT reached 2.4 units.", "2.4"),  # one clean occurrence
    ],
)
def test_prose_complete_value_span_is_accepted(article_identifier, source, raw) -> None:
    doc = _prose_doc(article_identifier, source)
    assert _prose_accepts(doc, _prose_measurement(article_identifier, source, raw))


# --- Unicode-preserving target tokenization ----------------------------------


def test_prose_greek_target_not_in_ascii_only_source_is_rejected(article_identifier) -> None:
    # γH2AX (a phospho-form) must not bind to a sentence that only mentions plain H2AX.
    text = "H2AX reached 2.4-fold."
    doc = _prose_doc(article_identifier, text)
    cand = _prose_measurement(article_identifier, text, "2.4-fold", name="γH2AX")
    assert not _prose_accepts(doc, cand, targets=("γH2AX",))


def test_prose_greek_target_in_matching_source_is_accepted(article_identifier) -> None:
    text = "γH2AX reached 2.4-fold."
    doc = _prose_doc(article_identifier, text)
    cand = _prose_measurement(article_identifier, text, "2.4-fold", name="γH2AX")
    assert _prose_accepts(doc, cand, targets=("γH2AX",))


def test_prose_beta_actin_not_in_actin_only_source_is_rejected(article_identifier) -> None:
    text = "actin reached 2.4-fold."
    doc = _prose_doc(article_identifier, text)
    cand = _prose_measurement(article_identifier, text, "2.4-fold", name="β-actin")
    assert not _prose_accepts(doc, cand, targets=("β-actin",))


def test_prose_beta_actin_in_matching_source_is_accepted(article_identifier) -> None:
    text = "β-actin reached 2.4-fold."
    doc = _prose_doc(article_identifier, text)
    cand = _prose_measurement(article_identifier, text, "2.4-fold", name="β-actin")
    assert _prose_accepts(doc, cand, targets=("β-actin",))


def test_prose_ascii_name_cannot_stand_in_for_greek_target(article_identifier) -> None:
    # measurement_name H2AX must not satisfy a requested γH2AX target even though an
    # ASCII-stripping normalization would equate them.
    text = "H2AX reached 2.4-fold."
    doc = _prose_doc(article_identifier, text)
    cand = _prose_measurement(article_identifier, text, "2.4-fold", name="H2AX")
    assert not _prose_accepts(doc, cand, targets=("γH2AX",))


def test_prose_greek_case_folding_matches(article_identifier) -> None:
    # Uppercase Greek Γ casefolds to γ; the same target is still recognized.
    text = "ΓH2AX reached 2.4-fold."
    doc = _prose_doc(article_identifier, text)
    cand = _prose_measurement(article_identifier, text, "2.4-fold", name="γH2AX")
    assert _prose_accepts(doc, cand, targets=("γH2AX",))


def test_prose_unicode_multi_target_span_is_ambiguous(article_identifier) -> None:
    # Two distinct requested targets (one Greek-marked) co-occur -> ambiguous binding.
    text = "γH2AX rose 2.4-fold while H2AX fell."
    doc = _prose_doc(article_identifier, text)
    cand = _prose_measurement(article_identifier, text, "2.4-fold", name="γH2AX")
    assert not _prose_accepts(doc, cand, targets=("γH2AX", "H2AX"))


def test_prose_tert_tert2_distinction_preserved(article_identifier) -> None:
    text = "TERT2 rose 2.4-fold."
    doc = _prose_doc(article_identifier, text)
    assert _prose_accepts(
        doc,
        _prose_measurement(article_identifier, text, "2.4-fold", name="TERT2"),
        targets=("TERT2",),
    )
    assert not _prose_accepts(
        doc,
        _prose_measurement(article_identifier, text, "2.4-fold", name="TERT"),
        targets=("TERT",),
    )


def test_prose_unicode_accepted_candidate_stays_unverified(article_identifier) -> None:
    text = "γH2AX reached 2.4-fold."
    doc = _prose_doc(article_identifier, text)
    cand = _prose_measurement(article_identifier, text, "2.4-fold", name="γH2AX")
    accepted, _ = accept_candidates(
        doc,
        LiteratureExtractionResult(measurements=[cand]),
        ExtractionTask(target_measurements=["γH2AX"]),
    )
    assert len(accepted.measurements) == 1
    assert "verification_status" not in type(accepted.measurements[0]).model_fields


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
