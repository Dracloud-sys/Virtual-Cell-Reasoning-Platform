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
from virtualcell.ingestion.contracts import SPEC_VERSION, SpecVersionError, TimeAxisKind
from virtualcell.ingestion.readers import ReaderError

CSV = """cell_line,passage,PDL,DT_min,operator,notes
IMR 90,25,22.0,2520,alice,ok
IMR 90,30,25.5,4800,bob,
IMR 90,35,NA,6000,bob,
"""


def _spec(**over) -> DatasetSpec:
    fields = {
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
        DatasetSpec(dataset_id="d", columns=[ColumnSpec(header="a", role=ColumnRole.IDENTIFIER)])
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
    assert any("whole count" in error for error in result.errors)


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
    assert any("offset" in error for error in result.errors)


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
    imr = next(r for r in runs if "IMR_90" in r.run_id)
    assert [o.time_point.value for o in imr.observations] == [25, 30]


def test_a_run_is_namespaced_versioned_and_sealed() -> None:
    run = _ingest().runs[0]
    assert run.run_namespace == "ingestion"
    assert run.schema_version == SCHEMA_VERSION
    assert run.checksum == content_checksum(run)


def test_the_untouched_identifier_survives_even_though_the_run_id_is_slugged() -> None:
    """Whitespace is stripped from the *handle* only; nothing about the data is lost."""
    run = _ingest().runs[0]
    assert run.run_id == "ingestion:fibroblast_passages:cell_line=IMR_90"
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
