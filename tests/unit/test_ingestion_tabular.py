"""Declared tabular ingestion, QC and normalization (PR13b).

The frozen rules this PR was approved under, each with the tests that hold it:

1. spec-driven, never inferred — an unmapped column is reported, a required one missing
   fails the run;
2. three layers — a candidate carries no verdict, a QC decision is the sole authority;
3. QC is acquisition quality, never biology;
4. one numeric grammar, shared with the literature pipeline;
5. no unit conversion this layer was not told about;
6. the column's declared value type is authoritative;
7. deterministic and idempotent;
8. writes nothing.
"""

from __future__ import annotations

import pytest

from virtualcell.core.experiment import (
    SCHEMA_VERSION,
    MeasurementQuality,
    MeasurementValueType,
    content_checksum,
)
from virtualcell.ingestion import (
    ColumnRole,
    ColumnSpec,
    DatasetSpec,
    IngestionStatus,
    QCRule,
    SourceFormat,
    ingest_table,
    read_delimited,
)
from virtualcell.ingestion.contracts import (
    SPEC_VERSION,
    RowRejectionReason,
    SpecVersionError,
    TimeAxisKind,
    encode_group,
)
from virtualcell.ingestion.readers import ReaderError

CSV = """cell_line,passage,PDL,DT_min,operator,notes
IMR 90,25,22.0,2520,alice,ok
IMR 90,30,25.5,4800,bob,
IMR 90,35,NA,6000,bob,
"""


def _spec(**over) -> DatasetSpec:
    fields = {
        "spec_version": SPEC_VERSION,
        "dataset_id": "fibroblast_passages",
        "columns": [
            ColumnSpec(header="cell_line", role=ColumnRole.IDENTIFIER),
            ColumnSpec(header="passage", role=ColumnRole.TIME_AXIS, time_axis=TimeAxisKind.PASSAGE),
            ColumnSpec(
                header="PDL",
                role=ColumnRole.MEASUREMENT,
                name="cumulative_PDL",
                value_type=MeasurementValueType.NUMERIC,
                unit="population_doubling",
            ),
            ColumnSpec(
                header="DT_min",
                role=ColumnRole.MEASUREMENT,
                name="DT_hours",
                value_type=MeasurementValueType.NUMERIC,
                unit="hour",
                source_unit="minute",
                unit_factor=1 / 60,
            ),
            ColumnSpec(header="operator", role=ColumnRole.IGNORED, required=False),
        ],
        "conditions": {"medium": "DMEM"},
    }
    fields.update(over)
    return DatasetSpec(**fields)


def _table(text: str = CSV):
    return read_delimited(text, source_name="passages.csv", source_format=SourceFormat.CSV)


def _ingest(text: str = CSV, spec: DatasetSpec | None = None):
    return ingest_table(_table(text), spec or _spec())


# --- 1. declared, never inferred ---------------------------------------------


def test_an_unmapped_column_is_reported_and_not_ingested() -> None:
    """A column nobody declared is a question for a human, not a guess for the parser."""
    result = _ingest()
    assert result.unmapped_columns == ["notes"]
    names = {m.name for run in result.runs for o in run.observations for m in o.measurements}
    assert "notes" not in names


def test_an_ignored_column_is_declared_and_silent() -> None:
    """Declaring a column ignored is a decision; leaving it unmapped is an oversight."""
    assert "operator" not in _ingest().unmapped_columns


def test_a_missing_required_column_fails_the_run() -> None:
    result = _ingest("cell_line,passage,PDL\nIMR 90,25,22.0\n")
    assert result.status is IngestionStatus.SPEC_MISMATCH
    assert result.missing_columns == ["DT_min"]
    assert result.runs == []


def test_an_optional_column_may_be_absent() -> None:
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,22.0,2520\n")
    assert result.status is IngestionStatus.SUCCESS


def test_a_spec_must_declare_a_measurement_and_one_time_axis() -> None:
    with pytest.raises(ValueError, match="at least one measurement"):
        DatasetSpec(
            spec_version=SPEC_VERSION,
            dataset_id="d",
            columns=[ColumnSpec(header="a", role=ColumnRole.IDENTIFIER)],
        )
    with pytest.raises(ValueError, match="one time axis"):
        _spec(
            columns=[
                *_spec().columns,
                ColumnSpec(header="day", role=ColumnRole.TIME_AXIS, time_axis=TimeAxisKind.PASSAGE),
            ]
        )


def test_a_measurement_column_must_declare_its_value_type() -> None:
    """Inferring the type per cell is exactly the silent reinterpretation PR12 removed."""
    with pytest.raises(ValueError, match="must declare a value_type"):
        ColumnSpec(header="PDL", role=ColumnRole.MEASUREMENT)


def test_a_spec_declares_its_own_version_and_refuses_a_foreign_major() -> None:
    assert _spec().spec_version == SPEC_VERSION
    with pytest.raises(ValueError, match="incompatible dataset spec"):
        _spec(spec_version="2.0")
    assert issubclass(SpecVersionError, ValueError)


# --- 2. three layers: candidate proposes, decision judges ---------------------


def test_a_parsed_candidate_carries_no_quality_verdict() -> None:
    from virtualcell.ingestion.parse import parse_row
    from virtualcell.ingestion.readers import cells_of

    cells, _ = parse_row(cells_of(_table(), 0), _spec())
    assert cells
    assert not any(hasattr(cell, "quality") for cell in cells)


def test_every_measurement_carries_the_rule_that_decided_it() -> None:
    """A decision can be re-derived rather than trusted."""
    result = _ingest()
    rules = {
        m.provenance.metadata["qc_rule"]
        for run in result.runs
        for o in run.observations
        for m in o.measurements
    }
    assert rules == {QCRule.ACCEPTED.value, QCRule.MISSING_TOKEN.value}


# --- 3. QC is acquisition quality, never biology -----------------------------


def test_the_qc_vocabulary_is_exactly_the_canonical_quality_enum() -> None:
    """A QC layer that can say 'senescent' has stopped being reusable and become a hidden
    domain model. The vocabulary is the schema's, and nothing is added to it."""
    from virtualcell.ingestion.contracts import QCDecision

    assert QCDecision.model_fields["quality"].annotation is MeasurementQuality


@pytest.mark.parametrize(
    ("cell", "rule", "quality"),
    [
        ("NA", QCRule.MISSING_TOKEN, MeasurementQuality.MISSING),
        ("increased", QCRule.UNPARSEABLE, MeasurementQuality.SUSPECT),
        ('"1,234"', QCRule.UNPARSEABLE, MeasurementQuality.SUSPECT),  # quoted: one CSV field
    ],
)
def test_unusable_cells_get_an_acquisition_verdict(cell: str, rule, quality) -> None:
    result = _ingest(f"cell_line,passage,PDL,DT_min\nIMR 90,25,{cell},2520\n")
    decision = next(d for d in result.qc.decisions if d.column == "cumulative_PDL")
    assert (decision.rule, decision.quality) == (rule, quality)


def test_detection_limits_are_acquisition_statements() -> None:
    spec = _spec(
        columns=[
            *(c for c in _spec().columns if c.header != "PDL"),
            ColumnSpec(
                header="PDL",
                role=ColumnRole.MEASUREMENT,
                name="cumulative_PDL",
                value_type=MeasurementValueType.NUMERIC,
                detection_limit_low=1.0,
                detection_limit_high=100.0,
            ),
        ]
    )
    low = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,0.2,2520\n", spec)
    high = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,500,2520\n", spec)
    assert low.qc.for_rule(QCRule.BELOW_DETECTION)[0].quality is MeasurementQuality.BELOW_DETECTION
    assert high.qc.for_rule(QCRule.ABOVE_DETECTION)[0].quality is MeasurementQuality.ABOVE_DETECTION


def test_an_implausible_value_is_flagged_but_keeps_its_value() -> None:
    """A human reviewing the flag needs to see what was actually recorded."""
    spec = _spec(
        columns=[
            *(c for c in _spec().columns if c.header != "PDL"),
            ColumnSpec(
                header="PDL",
                role=ColumnRole.MEASUREMENT,
                name="cumulative_PDL",
                value_type=MeasurementValueType.NUMERIC,
                plausible_max=200.0,
            ),
        ]
    )
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,9999,2520\n", spec)
    measurement = result.runs[0].observations[0].measurements[0]
    assert measurement.quality is MeasurementQuality.SUSPECT
    assert measurement.value == 9999.0
    assert any(f.startswith("out_of_range") for f in measurement.quality_flags)


def test_an_unparseable_value_keeps_no_value_at_all() -> None:
    """There is nothing to keep, and inventing one is the failure this layer prevents."""
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,increased,2520\n")
    measurement = next(
        m for m in result.runs[0].observations[0].measurements if m.name == "cumulative_PDL"
    )
    assert measurement.value is None
    assert measurement.quality is MeasurementQuality.SUSPECT
    assert measurement.provenance.metadata["raw_text"] == "increased"


# --- 4. one numeric grammar --------------------------------------------------


def test_ingestion_uses_the_platform_value_grammar() -> None:
    """Not a second parser: the same module the literature pipeline reads cells with."""
    import virtualcell.ingestion.parse as ingestion_parse
    from virtualcell.core import values
    from virtualcell.literature import extraction

    assert ingestion_parse.parse_value_text is values.parse_value_text
    assert extraction.parse_value_text is values.parse_value_text


def test_a_bound_keeps_its_comparator_and_never_becomes_a_point_estimate() -> None:
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,<0.05,2520\n")
    measurement = result.runs[0].observations[0].measurements[0]
    assert measurement.value == 0.05
    assert "bound:<" in measurement.quality_flags


def test_an_uncertainty_is_kept_separately_from_the_value() -> None:
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,22.0 ± 0.3,2520\n")
    measurement = result.runs[0].observations[0].measurements[0]
    assert measurement.value == 22.0
    assert "uncertainty:0.3" in measurement.quality_flags


# --- 5. no undeclared unit conversion ----------------------------------------


def test_a_declared_conversion_is_applied_and_recorded() -> None:
    result = _ingest()
    measurement = next(
        m for m in result.runs[0].observations[0].measurements if m.name == "DT_hours"
    )
    assert measurement.value == 42.0  # 2520 minutes
    assert measurement.unit == "hour"
    metadata = measurement.provenance.metadata
    assert metadata["pre_normalization_value"] == 2520.0
    assert (metadata["normalization_from_unit"], metadata["normalization_factor"]) == (
        "minute",
        1 / 60,
    )
    assert [(s.from_unit, s.to_unit) for s in result.normalizations] == [("minute", "hour")]


def test_a_conversion_without_a_declared_factor_is_refused_at_spec_time() -> None:
    with pytest.raises(ValueError, match="never guesses a conversion"):
        ColumnSpec(
            header="DT_min",
            role=ColumnRole.MEASUREMENT,
            value_type=MeasurementValueType.NUMERIC,
            unit="hour",
            source_unit="minute",
        )


def test_a_cell_carrying_a_different_unit_is_refused_not_reinterpreted() -> None:
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,22.0,40 hours\n")
    decision = next(d for d in result.qc.decisions if d.column == "DT_hours")
    assert decision.rule is QCRule.UNIT_MISMATCH
    assert decision.quality is MeasurementQuality.SUSPECT


# --- 6. the declared type is authoritative -----------------------------------


def test_a_string_in_a_numeric_column_never_becomes_a_categorical_measurement() -> None:
    """The PR12 value type earning its keep: the column decides, not the cell."""
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,high,2520\n")
    measurement = next(
        m for m in result.runs[0].observations[0].measurements if m.name == "cumulative_PDL"
    )
    assert measurement.value_type is MeasurementValueType.NUMERIC
    assert measurement.value is None
    assert measurement.quality is MeasurementQuality.SUSPECT


def test_a_categorical_column_may_declare_its_allowed_values() -> None:
    spec = _spec(
        columns=[
            *_spec().columns,
            ColumnSpec(
                header="morphology",
                role=ColumnRole.MEASUREMENT,
                value_type=MeasurementValueType.CATEGORICAL,
                allowed_categories=["spindle", "flattened"],
            ),
        ]
    )
    text = "cell_line,passage,PDL,DT_min,morphology\nIMR 90,25,22.0,2520,cobblestone\n"
    result = _ingest(text, spec)
    decision = next(d for d in result.qc.decisions if d.column == "morphology")
    assert decision.rule is QCRule.UNEXPECTED_CATEGORY


def test_a_boolean_column_uses_a_fixed_declared_vocabulary() -> None:
    spec = _spec(
        columns=[
            *_spec().columns,
            ColumnSpec(
                header="contaminated",
                role=ColumnRole.MEASUREMENT,
                value_type=MeasurementValueType.BOOLEAN,
            ),
        ]
    )
    text = "cell_line,passage,PDL,DT_min,contaminated\nIMR 90,25,22.0,2520,no\n"
    measurement = next(
        m
        for m in _ingest(text, spec).runs[0].observations[0].measurements
        if m.name == "contaminated"
    )
    assert measurement.value is False

    maybe = "cell_line,passage,PDL,DT_min,contaminated\nIMR 90,25,22.0,2520,maybe\n"
    decision = next(d for d in _ingest(maybe, spec).qc.decisions if d.column == "contaminated")
    assert decision.rule is QCRule.UNPARSEABLE


def test_a_condition_without_a_declared_type_stays_a_label() -> None:
    """Reading "5" as the number five would be inference, which is what is excluded."""
    spec = _spec(
        columns=[*_spec().columns, ColumnSpec(header="oxygen_pct", role=ColumnRole.CONDITION)]
    )
    text = "cell_line,passage,PDL,DT_min,oxygen_pct\nIMR 90,25,22.0,2520,5\n"
    assert _ingest(text, spec).runs[0].observations[0].conditions == {"oxygen_pct": "5"}


# --- time axis ---------------------------------------------------------------


def test_a_fractional_passage_is_refused_not_truncated() -> None:
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25.5,22.0,2520\n")
    assert result.runs == []
    assert result.status is IngestionStatus.NO_VALID_ROWS
    assert [r.reason for r in result.rejected_rows] == [RowRejectionReason.UNUSABLE_TIME_POINT]
    assert "whole count" in result.rejected_rows[0].detail


def test_a_naive_timestamp_is_refused() -> None:
    spec = _spec(
        columns=[
            *(c for c in _spec().columns if c.header != "passage"),
            ColumnSpec(
                header="passage", role=ColumnRole.TIME_AXIS, time_axis=TimeAxisKind.TIMESTAMP
            ),
        ]
    )
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,2026-01-01T00:00:00,22.0,2520\n", spec)
    assert "offset" in result.rejected_rows[0].detail


def test_an_elapsed_time_axis_requires_a_unit() -> None:
    with pytest.raises(ValueError, match="must declare time_unit"):
        ColumnSpec(header="t", role=ColumnRole.TIME_AXIS, time_axis=TimeAxisKind.ELAPSED_TIME)


# --- runs, identity and 7. determinism ---------------------------------------


def test_rows_group_into_runs_by_identifier_and_keep_their_order() -> None:
    text = (
        "cell_line,passage,PDL,DT_min\nIMR 90,25,22.0,2520\nBJ,25,20.0,2400\nIMR 90,30,25.5,4800\n"
    )
    runs = _ingest(text).runs
    assert len(runs) == 2
    imr = next(r for r in runs if "IMR%2090" in r.run_id)
    assert [o.time_point.value for o in imr.observations] == [25, 30]


def test_a_run_is_namespaced_versioned_and_sealed() -> None:
    run = _ingest().runs[0]
    assert run.run_namespace == "ingestion"
    assert run.schema_version == SCHEMA_VERSION
    assert run.checksum == content_checksum(run)


def test_the_untouched_identifier_survives_even_though_the_run_id_is_slugged() -> None:
    """Whitespace is stripped from the *handle* only; nothing about the data is lost."""
    run = _ingest().runs[0]
    assert run.run_id == "ingestion:fibroblast_passages:cell_line=IMR%2090"
    assert run.conditions["cell_line"] == "IMR 90"
    assert run.conditions["medium"] == "DMEM"  # spec-level condition carried through


def test_importing_the_same_file_twice_is_identical() -> None:
    first, second = _ingest(), _ingest()
    assert [content_checksum(r) for r in first.runs] == [content_checksum(r) for r in second.runs]
    assert first.qc.counts == second.qc.counts


def test_identical_rows_collapse_to_one_run() -> None:
    """PR13a identity applied to a file that lists the same group twice."""
    spec = _spec(columns=[c for c in _spec().columns if c.role is not ColumnRole.IDENTIFIER])
    text = "passage,PDL,DT_min\n25,22.0,2520\n"
    result = ingest_table(
        read_delimited(text, source_name="a.csv", source_format=SourceFormat.CSV), spec
    )
    assert len(result.runs) == 1


# --- 8. writes nothing -------------------------------------------------------


def test_ingestion_returns_runs_and_writes_nothing() -> None:
    """Importing data and asserting it as evidence are different acts."""
    import ast
    import inspect

    from virtualcell.ingestion import canonical

    tree = ast.parse(inspect.getsource(canonical))
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(module.startswith("virtualcell.knowledge") for module in imported)
    assert "store" not in inspect.signature(ingest_table).parameters


# --- reader ------------------------------------------------------------------


def test_a_row_with_more_fields_than_headers_is_refused() -> None:
    with pytest.raises(ReaderError, match="refusing to guess"):
        read_delimited("a,b\n1,2,3\n", source_name="x.csv", source_format=SourceFormat.CSV)


def test_a_short_row_is_padded_and_a_blank_line_is_skipped() -> None:
    table = read_delimited("a,b\n1\n\n2,3\n", source_name="x.csv", source_format=SourceFormat.CSV)
    assert table.rows == [["1", ""], ["2", "3"]]


def test_tsv_is_read_with_the_same_pipeline() -> None:
    text = CSV.replace(",", "\t")
    table = read_delimited(text, source_name="p.tsv", source_format=SourceFormat.TSV)
    assert ingest_table(table, _spec(source_format=SourceFormat.TSV)).status is (
        IngestionStatus.SUCCESS
    )


def test_a_source_with_no_rows_is_a_typed_status_not_an_empty_success() -> None:
    result = _ingest("cell_line,passage,PDL,DT_min\n")
    assert result.status is IngestionStatus.NO_ROWS
    assert result.status.is_failure


def test_an_unreadable_file_is_a_typed_status_not_an_exception() -> None:
    from virtualcell.ingestion import ingest_file

    result = ingest_file("no/such/file.csv", _spec())
    assert result.status is IngestionStatus.UNREADABLE_SOURCE
    assert result.errors


# --- review round 2: bounds are never point estimates ------------------------


def test_a_bound_is_not_a_valid_scalar_reading() -> None:
    """A "<0.05" cell does not mean 0.05. The value is kept because the limit is real
    information, but the reading is not a point estimate."""
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,<0.05,2520\n")
    decision = next(d for d in result.qc.decisions if d.column == "cumulative_PDL")
    assert decision.rule is QCRule.BOUNDED
    assert decision.quality is MeasurementQuality.SUSPECT

    measurement = next(
        m for m in result.runs[0].observations[0].measurements if m.name == "cumulative_PDL"
    )
    assert measurement.value == 0.05  # the limit is not discarded...
    assert measurement.bound == "<"  # ...but it is unmistakably a limit


def test_the_schema_refuses_to_read_a_bound_as_a_number() -> None:
    """The structural guard: every consumer goes through ``numeric_value``, so a limit
    cannot be read as a value by code that only remembered to check quality."""
    from virtualcell.core.experiment import Measurement, MeasurementTypeError

    bounded = Measurement(name="p", value=0.05, quality_flags=["bound:<"])
    assert bounded.bound == "<"
    assert not bounded.is_point_estimate
    with pytest.raises(MeasurementTypeError, match="bounded"):
        bounded.numeric_value()


# --- review round 2: whole-cell numeric parsing ------------------------------


@pytest.mark.parametrize("text", ["abc24xyz", "24 (n=3)", "P24", "24 units", "24 or 25"])
def test_a_numeric_cell_that_merely_contains_a_number_is_refused(text: str) -> None:
    """Deciding *which part* of a cell was the datum is the reader interpreting, which is
    what a declared numeric column exists to make unnecessary."""
    result = _ingest(f'cell_line,passage,PDL,DT_min\nIMR 90,25,"{text}",2520\n')
    decision = next(d for d in result.qc.decisions if d.column == "cumulative_PDL")
    assert decision.rule is QCRule.UNPARSEABLE


@pytest.mark.parametrize("text", ["24", "24.5", "-3", "1e5", "<0.05", "2.4 ± 0.3", "2.4-fold"])
def test_a_cell_that_is_a_value_in_full_still_parses(text: str) -> None:
    from virtualcell.core.values import is_whole_value

    assert is_whole_value(text)


def test_the_strict_boundary_is_built_from_the_shared_grammar() -> None:
    """Not a second parser: strict mode is the same grammar with a whole-cell anchor, so
    the two can never drift into disagreeing about what a number is."""
    from virtualcell.core.values import ParseStatus, parse_value_text

    lenient = parse_value_text("abc24xyz")
    strict = parse_value_text("abc24xyz", strict=True)
    assert lenient.parsed_value == 24.0  # the literature prose path is unchanged
    assert strict.parse_status is ParseStatus.UNPARSED
    assert parse_value_text("24", strict=True).parsed_value == 24.0


# --- review round 2: authoritative status when rows are rejected -------------


def test_rejecting_every_row_is_not_a_success() -> None:
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,P?,22.0,2520\nIMR 90,x,25.5,4800\n")
    assert result.status is IngestionStatus.NO_VALID_ROWS
    assert result.status.is_failure
    assert result.runs == []
    assert len(result.rejected_rows) == 2


def test_rejecting_some_rows_is_partial_not_success() -> None:
    """Neither answer is right on its own: real runs were produced *and* a human needs to
    look at what was dropped."""
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,22.0,2520\nIMR 90,x,25.5,4800\n")
    assert result.status is IngestionStatus.PARTIAL
    assert not result.status.is_failure  # runs were produced
    assert len(result.runs) == 1
    assert result.rejected_rows[0].row_index == 1


def test_a_rejected_row_contributes_no_qc_decisions() -> None:
    """Its cells never became measurements, so counting them would inflate the numbers a
    human reads to judge the import."""
    good = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,22.0,2520\n")
    mixed = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,22.0,2520\nIMR 90,x,25.5,4800\n")
    assert len(mixed.qc.decisions) == len(good.qc.decisions)


def test_the_status_exit_codes_are_three_distinct_answers() -> None:
    assert IngestionStatus.SUCCESS.exit_code == 0
    assert IngestionStatus.PARTIAL.exit_code == 2
    assert IngestionStatus.NO_VALID_ROWS.exit_code == 1
    assert IngestionStatus.NO_ROWS.exit_code == 1


# --- review round 2: hardened run grouping -----------------------------------


def test_a_row_with_a_blank_required_identifier_is_rejected() -> None:
    """Defaulting it to empty would group every such row together, silently merging
    unrelated cultures into one run."""
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,22.0,2520\n,30,25.5,4800\n")
    assert [r.reason for r in result.rejected_rows] == [RowRejectionReason.UNUSABLE_IDENTIFIER]
    assert len(result.runs) == 1
    assert result.status is IngestionStatus.PARTIAL


def test_unrelated_rows_with_blank_identifiers_never_merge() -> None:
    result = _ingest("cell_line,passage,PDL,DT_min\n,25,22.0,2520\n,30,99.0,4800\n")
    assert result.runs == []
    assert len(result.rejected_rows) == 2


def test_the_group_encoding_cannot_collide() -> None:
    """Concatenating raw values with delimiters is not injective: without encoding, one
    identifier holding a delimiter produces the key two identifiers would, and two
    unrelated cultures silently become one run."""
    assert encode_group({"a": "x|b=y"}) != encode_group({"a": "x", "b": "y"})
    assert encode_group({"a": "x=y"}) != encode_group({"a": "x", "y": ""})
    # ...and it stays whitespace-free, which a canonical run id requires.
    assert " " not in encode_group({"cell_line": "IMR 90"})


def test_identifier_values_containing_delimiters_survive_verbatim() -> None:
    text = 'cell_line,passage,PDL,DT_min\n"a|b=c",25,22.0,2520\n'
    run = _ingest(text).runs[0]
    assert run.conditions["cell_line"] == "a|b=c"
    assert run.run_id == "ingestion:fibroblast_passages:cell_line=a%7Cb%3Dc"


# --- review round 2: spec versioning and numeric coherence -------------------


def test_an_unversioned_spec_is_refused_not_assumed_to_be_current() -> None:
    """A spec is executed; guessing which instructions it meant is how a file gets read
    under rules its author never wrote."""
    with pytest.raises(ValueError, match="spec_version"):
        DatasetSpec.model_validate(
            {"dataset_id": "d", "columns": [c.model_dump() for c in _spec().columns]}
        )


def test_a_newer_spec_minor_is_refused_unlike_a_newer_run_minor() -> None:
    """The asymmetry is deliberate: a run is data a reader can carry through untouched, a
    spec is an instruction a reader would silently fail to follow."""
    with pytest.raises(ValueError, match="newer than this reader"):
        _spec(spec_version="1.99")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_spec_numbers_must_be_finite(bad: float) -> None:
    for field in ("detection_limit_low", "plausible_max"):
        with pytest.raises(ValueError, match="finite"):
            ColumnSpec(
                header="PDL",
                role=ColumnRole.MEASUREMENT,
                value_type=MeasurementValueType.NUMERIC,
                **{field: bad},
            )
    with pytest.raises(ValueError, match="finite|positive"):
        ColumnSpec(
            header="DT",
            role=ColumnRole.MEASUREMENT,
            value_type=MeasurementValueType.NUMERIC,
            unit="hour",
            source_unit="minute",
            unit_factor=bad,
        )


@pytest.mark.parametrize("factor", [0.0, -1.0])
def test_a_conversion_factor_must_be_positive(factor: float) -> None:
    """A zero or negative factor is not a unit conversion, it is a different measurement."""
    with pytest.raises(ValueError, match="positive"):
        ColumnSpec(
            header="DT",
            role=ColumnRole.MEASUREMENT,
            value_type=MeasurementValueType.NUMERIC,
            unit="hour",
            source_unit="minute",
            unit_factor=factor,
        )


def test_an_inverted_range_is_refused() -> None:
    with pytest.raises(ValueError, match="no reading could ever satisfy both"):
        ColumnSpec(
            header="PDL",
            role=ColumnRole.MEASUREMENT,
            value_type=MeasurementValueType.NUMERIC,
            detection_limit_low=10.0,
            detection_limit_high=1.0,
        )
    with pytest.raises(ValueError, match="range is empty"):
        ColumnSpec(
            header="PDL",
            role=ColumnRole.MEASUREMENT,
            value_type=MeasurementValueType.NUMERIC,
            plausible_min=10.0,
            plausible_max=1.0,
        )


# --- review round 3: canonical-name collisions cannot merge runs -------------


def _two_identifier_spec(**over) -> DatasetSpec:
    fields = {
        "spec_version": SPEC_VERSION,
        "dataset_id": "d",
        "columns": [
            ColumnSpec(header="id1", role=ColumnRole.IDENTIFIER),
            ColumnSpec(header="id2", role=ColumnRole.IDENTIFIER),
            ColumnSpec(header="p", role=ColumnRole.TIME_AXIS, time_axis=TimeAxisKind.PASSAGE),
            ColumnSpec(
                header="v", role=ColumnRole.MEASUREMENT, value_type=MeasurementValueType.NUMERIC
            ),
        ],
    }
    fields.update(over)
    return DatasetSpec(**fields)


def test_two_identifier_columns_may_not_declare_the_same_name() -> None:
    """The defect: both columns collapse into one dict entry keyed by name, so rows
    differing only in the shadowed column group into a single run — unrelated cultures
    silently merged, and the import reports success."""
    columns = _two_identifier_spec().columns
    with pytest.raises(ValueError, match="duplicate canonical column name"):
        _two_identifier_spec(
            columns=[
                ColumnSpec(header="id1", role=ColumnRole.IDENTIFIER, name="sample"),
                ColumnSpec(header="id2", role=ColumnRole.IDENTIFIER, name="sample"),
                *columns[2:],
            ]
        )


def test_the_collision_policy_covers_every_ingested_column_not_just_measurements() -> None:
    """A name shared by any two ingested columns collapses wherever the pipeline keys by
    name, so the rule is stated once for all of them rather than per role."""
    columns = _two_identifier_spec().columns
    for clashing in (
        ColumnSpec(header="c1", role=ColumnRole.CONDITION, name="v"),
        ColumnSpec(header="t1", role=ColumnRole.IDENTIFIER, name="v"),
    ):
        with pytest.raises(ValueError, match="duplicate canonical column name"):
            _two_identifier_spec(columns=[*columns, clashing])

    # ...but an ignored column contributes nothing, so its name cannot collide.
    _two_identifier_spec(
        columns=[*columns, ColumnSpec(header="x", role=ColumnRole.IGNORED, name="v")]
    )


def test_rows_differing_in_any_identifier_stay_separate_runs() -> None:
    """The end state the collision rule protects: two cultures, two runs."""
    table = read_delimited(
        "id1,id2,p,v\na,b,1,10\nx,b,2,20\n", source_name="s.csv", source_format=SourceFormat.CSV
    )
    result = ingest_table(table, _two_identifier_spec())
    assert len(result.runs) == 2
    assert {run.run_id for run in result.runs} == {
        "ingestion:d:id1=a|id2=b",
        "ingestion:d:id1=x|id2=b",
    }
    assert all(len(run.observations) == 1 for run in result.runs)


def test_a_column_is_resolved_by_its_source_header() -> None:
    """The header is what the spec guarantees unique at the file level; looking a column
    up by a name two columns could share is how one shadows the other."""
    import inspect

    from virtualcell.ingestion import canonical

    source = inspect.getsource(canonical.ingest_table)
    assert "by_header[cell.locator.column_header]" in source


# --- review round 3: non-finite values and grammar drift ---------------------


@pytest.mark.parametrize("text", ["1e999", "-1e999", "1e999 fold"])
def test_a_value_that_overflows_to_infinity_is_unreadable(text: str) -> None:
    """It is syntactically a number and semantically nothing the schema can hold. Parsing
    it would hand a constructor a value guaranteed to raise, turning one raw cell into a
    traceback instead of a QC verdict."""
    from virtualcell.core.values import ParseStatus, parse_value_text

    assert parse_value_text(text, strict=True).parse_status is ParseStatus.UNPARSED
    assert parse_value_text(text).parse_status is ParseStatus.UNPARSED


def test_an_overflowing_cell_becomes_a_qc_verdict_not_a_crash() -> None:
    result = _ingest("cell_line,passage,PDL,DT_min\nIMR 90,25,1e999,2520\n")
    decision = next(d for d in result.qc.decisions if d.column == "cumulative_PDL")
    assert decision.rule is QCRule.UNPARSEABLE
    assert decision.quality is MeasurementQuality.SUSPECT

    measurement = next(
        m for m in result.runs[0].observations[0].measurements if m.name == "cumulative_PDL"
    )
    assert measurement.value is None


def test_an_overflowing_uncertainty_is_refused_too() -> None:
    from virtualcell.core.values import ParseStatus, parse_value_text

    assert parse_value_text("2 ± 1e999", strict=True).parse_status is ParseStatus.UNPARSED


def test_the_uncertainty_pattern_reuses_the_shared_number_token() -> None:
    """The drift this catches: the uncertainty regex had its own abbreviated number, so
    "2 ± 1e5" passed the whole-cell check built from the full token and then recorded an
    uncertainty of 1 instead of 100000."""
    from virtualcell.core.values import parse_value_text

    parsed = parse_value_text("2 ± 1e5", strict=True)
    assert (parsed.parsed_value, parsed.uncertainty) == (2.0, 100000.0)


def test_a_unit_ending_in_a_non_word_character_is_accepted() -> None:
    """``%`` is a declared unit, but a trailing ``\\b`` cannot match after it at end of
    text, so "24%" was refused while "24 fold" was accepted."""
    from virtualcell.core.values import is_whole_value, parse_value_text

    assert is_whole_value("24%")
    parsed = parse_value_text("24%", strict=True)
    assert (parsed.parsed_value, parsed.unit) == (24.0, "%")
    # The longest matching unit still wins over its own prefix.
    assert parse_value_text("48 hours", strict=True).unit == "hours"
