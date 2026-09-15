"""A canonical run must reach reasoning through the query boundary, not a manual call.

PR13b proved the chain up to the agent:

    raw CSV -> QC -> canonical run -> run_to_passage_series -> the agent, called by hand

The last arrow was the problem. Every other surface reaches reasoning through
`ReasoningService.query`, and canonical runs reached it only if a human wrote the glue -
so the domain-neutral entry point, the consumption ledger, the missing-input round trip
and the MCP server all sat on one side of the chain and the ingestion layer on the other.

This is the acceptance criterion for closing it:

    raw CSV -> QC -> canonical run -> ReasoningService.query -> ReasoningResponse

and the specific thing it makes reachable: **`quality_excluded` is now a state a caller
can actually observe.** It has existed in the consumption vocabulary since PR17 and no
query could produce one, because QC verdicts live on canonical measurements and canonical
measurements could not be submitted.

The fixture is imported from the PR13b benchmark rather than copied. Two spellings of
"the same export" drift, and the claim here is precisely that this path and that one see
the same data.
"""

from __future__ import annotations

import asyncio

from tests.benchmarks.test_ingestion_product_path import (
    PASSAGE_CSV,
    SPEC,
)

from virtualcell.agents.immortalization.adapters import run_to_passage_series
from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
from virtualcell.agents.immortalization.models import (
    AssessmentIntent,
    ImmortalizationAssessmentInput,
)
from virtualcell.core.consumption import ConsumptionStatus
from virtualcell.core.experiment import ExperimentRun, MeasurementQuality
from virtualcell.ingestion import IngestionStatus, ingest_table, read_delimited
from virtualcell.ingestion.contracts import SourceFormat
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.platform.bootstrap import default_registry, seed_registered_domains
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.service import ReasoningService

DOMAIN = "immortalization"
TASK = "assess_state"


def _import(text: str = PASSAGE_CSV):
    table = read_delimited(text, source_name="imr90.csv", source_format=SourceFormat.CSV)
    return ingest_table(table, SPEC)


def _run(text: str = PASSAGE_CSV) -> ExperimentRun:
    result = _import(text)
    assert result.status is IngestionStatus.SUCCESS
    return result.runs[0]


def _ask(run: ExperimentRun, **extra) -> ReasoningResponse:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    service = ReasoningService(store, default_registry())
    query = ReasoningQuery(domain=DOMAIN, task=TASK, experiment_run=run, **extra)
    return asyncio.run(service.query(query))


# --- the criterion ------------------------------------------------------------


def test_a_raw_csv_reaches_a_reasoning_response_through_the_query_boundary() -> None:
    response = _ask(_run())

    assert response.domain == DOMAIN
    assert response.task == TASK
    assert response.summary
    assert response.decision_support.status == "senescence_or_stress_prone"
    assert response.recommended_next_experiments


def test_the_query_path_and_the_hand_written_one_reach_the_same_verdict() -> None:
    """The boundary must be a door, not a second implementation. If these ever disagree,
    the canonical intake has started making its own scientific decisions."""
    run = _run()

    by_hand = ImmortalizationAssessmentAgent(store=_seeded()).assess(
        ImmortalizationAssessmentInput(
            intent=AssessmentIntent.IMMORTALIZATION_ASSESSMENT,
            construct_type="unknown",
            observations=run_to_passage_series(run),
        )
    )
    through_query = _ask(run)

    assert through_query.decision_support.status == by_hand.candidate_status.value
    assert through_query.summary == by_hand.conclusion
    assert through_query.recommended_next_experiments == list(by_hand.next_experiment)
    assert [c.statement for c in through_query.supporting_evidence] == [
        c.statement for c in by_hand.supporting_evidence
    ]


def _seeded() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    return store


# --- what this unlocks: quality_excluded, reachable at last -------------------


def test_a_qc_flagged_reading_is_reported_as_quality_excluded_on_the_query_surface() -> None:
    """The state PR17 defined and no query could produce.

    An unreadable cell must not reach reasoning as a number - PR13b proved that. What it
    could not do is *tell the caller*, because the report it left behind lived on the
    canonical run and no caller could submit one. Now the report says so, under the name
    the measurement actually has, pointing at the observation it came from.
    """
    text = PASSAGE_CSV.replace("IMR 90,30,25.0,2400,bob", "IMR 90,30,NA,2400,bob")
    run = _run(text)

    # The run really does carry a flagged reading, so the assertion below is about the
    # boundary rather than about a fixture that happened to be clean.
    flagged = [
        m
        for observation in run.observations
        for m in observation.measurements
        if m.quality is not MeasurementQuality.VALID
    ]
    assert len(flagged) == 1

    response = _ask(run)
    excluded = response.measurement_consumption.by_status(ConsumptionStatus.QUALITY_EXCLUDED)

    assert [entry.submitted_as for entry in excluded] == ["cumulative_PDL"]
    entry = excluded[0]
    assert entry.reason and "missing" in entry.reason
    # Traceable to the passage it came from, not to the run as a whole.
    assert entry.provenance and "observations[2]" in entry.provenance


def test_a_clean_export_reports_every_reading_as_used() -> None:
    response = _ask(_run())
    used = response.measurement_consumption.by_status(ConsumptionStatus.USED_FOR_STATUS)

    names = {entry.submitted_as for entry in used}
    assert names == {"cumulative_PDL", "DT_hours"}
    assert not response.measurement_consumption.by_status(ConsumptionStatus.QUALITY_EXCLUDED)


def test_a_measurement_the_domain_cannot_map_is_unsupported_not_silently_dropped() -> None:
    """The two ways a reading disappears must stay apart. An unrecognised name is a
    modelling gap; a recognised name QC flagged is a value the engine wanted and could not
    trust. Collapsing them hides a data problem inside a schema problem."""
    run = _run()
    with_extra = run.model_copy(
        update={
            "checksum": None,
            "observations": [
                run.observations[0].model_copy(
                    update={
                        "measurements": [
                            *run.observations[0].measurements,
                            _measurement("mystery_readout", 1.0),
                        ]
                    }
                ),
                *run.observations[1:],
            ],
        }
    )

    response = _ask(with_extra)
    unsupported = response.measurement_consumption.by_status(ConsumptionStatus.UNSUPPORTED)

    assert [entry.submitted_as for entry in unsupported] == ["mystery_readout"]
    assert not response.measurement_consumption.by_status(ConsumptionStatus.QUALITY_EXCLUDED)


def _measurement(name: str, value: float):
    from virtualcell.core.experiment import Measurement, MeasurementValueType

    return Measurement(name=name, value=value, value_type=MeasurementValueType.NUMERIC)


# --- the run stays traceable through the answer -------------------------------


def test_the_response_records_which_run_answered_it() -> None:
    """A verdict derived from a canonical run has to say so. Otherwise the answer and the
    data that produced it can only be reconnected by whoever happened to run the query."""
    run = _run()
    provenance = _ask(run).provenance.experiment_run

    assert provenance is not None
    assert provenance.run_id == run.run_id
    assert provenance.schema_version == run.schema_version
    assert provenance.observations == len(run.observations)
    # The ingestion layer seals what it produces, and the answer repeats the claim rather
    # than making one: an unsealed run is reported as unsealed, never as verified.
    assert provenance.sealed is True


# --- the two entries compose ---------------------------------------------------


def test_the_gaps_a_run_leaves_can_be_closed_the_way_the_report_says() -> None:
    """The strongest statement of the design, and the reason a run and a dict may be sent
    together.

    A passage export carries the series and nothing else, so the senescence markers come
    back as missing inputs - under axis names, because that is what a caller sends. The
    stains were never in that file and never will be; they are a different assay. The
    caller supplies them beside the run, and the gap closes with nothing reported as
    unrecognised. A boundary that accepted only one of the two would have made this
    unreachable without re-exporting the CSV.
    """
    run = _run()
    first = _ask(run)
    assert [item.canonical_axis for item in first.missing_inputs] == [
        "gammaH2AX",
        "SA_b_gal",
        "p16",
        "p21",
    ]

    measured = {item.canonical_axis: "normal" for item in first.missing_inputs}
    second = _ask(run, experiment=measured)

    assert second.missing_inputs == []
    assert not second.measurement_consumption.unsupported
    # And the run's own readings are still accounted for, under their canonical names.
    used = {
        entry.submitted_as
        for entry in second.measurement_consumption.by_status(ConsumptionStatus.USED_FOR_STATUS)
    }
    assert {"cumulative_PDL", "DT_hours"} <= used
