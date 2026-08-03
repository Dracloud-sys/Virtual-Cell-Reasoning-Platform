"""PR13b acceptance: raw CSV drives the shipped reasoning path end to end.

This is the criterion the whole ingestion layer exists to satisfy. Every other test in
PR13b checks one rule in isolation; this one checks the claim:

    raw CSV -> QC -> canonical run -> run_to_passage_series -> ImmortalizationAssessmentAgent

If that chain works, an experimentalist's export can reach a grounded decision report
without anyone hand-transcribing it into the platform's own shapes — which is the point of
having a canonical schema at all.

Following PR10b, this runs the **product path**: the shipped agent, not a re-implementation
of its rules.
"""

from __future__ import annotations

from virtualcell.agents.immortalization.adapters import run_to_passage_series
from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
from virtualcell.agents.immortalization.models import (
    AssessmentIntent,
    ImmortalizationAssessmentInput,
)
from virtualcell.core.experiment import MeasurementQuality, MeasurementValueType
from virtualcell.ingestion import (
    ColumnRole,
    ColumnSpec,
    DatasetSpec,
    IngestionStatus,
    ingest_table,
    read_delimited,
)
from virtualcell.ingestion.contracts import SPEC_VERSION, SourceFormat, TimeAxisKind
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource

# A plausible bench export: doubling time recorded in minutes, one blank reading, and a
# column nobody declared. None of that is unusual, and none of it may silently change the
# science.
PASSAGE_CSV = """cell_line,passage,PDL,DT_min,operator
IMR 90,10,12.0,1440,alice
IMR 90,20,20.0,1800,alice
IMR 90,30,25.0,2400,bob
IMR 90,40,27.0,3600,bob
IMR 90,50,27.5,6000,bob
"""

SPEC = DatasetSpec(
    spec_version=SPEC_VERSION,
    dataset_id="imr90_passage_series",
    source_format=SourceFormat.CSV,
    columns=[
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
    conditions={"medium": "DMEM", "serum_pct": 10},
    method="manual_passage_log",
)


def _import(text: str = PASSAGE_CSV):
    table = read_delimited(text, source_name="imr90.csv", source_format=SourceFormat.CSV)
    return ingest_table(table, SPEC)


def _store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(ImmortalizationSeedSource(), store)
    return store


def test_a_raw_csv_reaches_a_grounded_decision_report() -> None:
    result = _import()
    assert result.status is IngestionStatus.SUCCESS

    run = result.runs[0]
    series = run_to_passage_series(run)  # validates the schema version before reading
    report = ImmortalizationAssessmentAgent(store=_store()).assess(
        ImmortalizationAssessmentInput(
            intent=AssessmentIntent.IMMORTALIZATION_ASSESSMENT,
            construct_type="unknown",
            observations=series,
        )
    )

    # The chain produced a real, grounded report — not an empty shell. The status is the
    # one the trajectory actually supports, and the agent asks for the assays that would
    # settle it, so the imported data reached the reasoning and not just the type checks.
    assert report.conclusion
    assert report.candidate_status is not None
    assert report.candidate_status.value == "senescence_or_stress_prone"
    assert report.next_experiment


def test_the_trajectory_the_agent_sees_is_the_one_in_the_file() -> None:
    """Normalization must not move the science: the passages, PDLs and converted doubling
    times reaching the engine are exactly what the export recorded."""
    series = run_to_passage_series(_import().runs[0])

    assert [o.passage for o in series] == [10, 20, 30, 40, 50]
    assert [o.cumulative_PDL for o in series] == [12.0, 20.0, 25.0, 27.0, 27.5]
    # 1440 min -> 24 h, 6000 min -> 100 h, by the factor the spec declared.
    assert [o.DT_hours for o in series] == [24.0, 30.0, 40.0, 60.0, 100.0]


def test_the_engine_reads_the_slowdown_the_export_shows() -> None:
    """The imported series carries a real biological signal through to the engine, rather
    than merely surviving the type checks."""
    from virtualcell.agents.immortalization.trajectory import extract_trajectory

    analysis = extract_trajectory(run_to_passage_series(_import().runs[0]))
    assert analysis.derived_DT_trend.value == "worsening"


def test_a_qc_failure_travels_to_the_report_instead_of_becoming_a_number() -> None:
    """The failure mode worth guarding: an unreadable cell must not reach reasoning as a
    value. It arrives as a missing measurement, and the agent sees less data, not wrong
    data."""
    text = PASSAGE_CSV.replace("IMR 90,30,25.0,2400,bob", "IMR 90,30,NA,2400,bob")
    result = _import(text)

    missing = [
        m
        for run in result.runs
        for observation in run.observations
        for m in observation.measurements
        if m.quality is MeasurementQuality.MISSING
    ]
    assert len(missing) == 1
    assert missing[0].value is None

    series = run_to_passage_series(result.runs[0])
    assert [o.cumulative_PDL for o in series] == [12.0, 20.0, None, 27.0, 27.5]
    assert [o.DT_hours for o in series] == [24.0, 30.0, 40.0, 60.0, 100.0]


def test_the_imported_run_is_sealed_and_traceable_to_its_source_cells() -> None:
    """A number in a decision report can be walked back to a row and column in a file."""
    run = _import().runs[0]
    assert run.checksum is not None

    measurement = run.observations[0].measurements[0]
    metadata = measurement.provenance.metadata
    assert metadata["source_name"] == "imr90.csv"
    assert metadata["row_index"] == 0
    assert metadata["column_header"] == "PDL"
    assert metadata["raw_text"] == "12.0"


def test_a_bound_never_reaches_the_trajectory_as_a_point_estimate() -> None:
    """The end-to-end guard for the defect that matters most here.

    A cell reading "<15.0" says the true PDL is *below* 15, not that it is 15. If that
    number entered the series it would be indistinguishable from a measured 15.0, and the
    trend, the slowdown detection and the resulting candidate status would all be computed
    from a limit — wrong in a way nothing downstream could detect. It must arrive absent.
    """
    text = PASSAGE_CSV.replace("IMR 90,20,20.0,1800,alice", "IMR 90,20,<15.0,1800,alice")
    result = _import(text)

    bounded = next(
        m
        for run in result.runs
        for observation in run.observations
        for m in observation.measurements
        if m.bound is not None
    )
    assert bounded.value == 15.0  # the limit itself is preserved on the run...
    assert bounded.quality is not MeasurementQuality.VALID

    series = run_to_passage_series(result.runs[0])
    assert [o.cumulative_PDL for o in series] == [12.0, None, 25.0, 27.0, 27.5]
