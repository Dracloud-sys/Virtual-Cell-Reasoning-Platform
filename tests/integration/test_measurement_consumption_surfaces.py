"""Measurement consumption, as both domains declare it and as every surface reports it.

The finding this closes (PR16, finding 3): a caller could submit a measurement and receive a
response identical to not having submitted it. A typo and a deliberate reading were
indistinguishable from the outside.

Two things are checked here that the unit tests cannot. First, that each domain's *policy*
is right — and the two policies genuinely differ, which is the evidence that this is a
platform contract with domain content rather than one vertical's feature wearing a generic
name. Second, that the same answer arrives through the service, the API and the CLI, since a
transparency feature visible on only one surface is not transparency.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from virtualcell.api.main import app
from virtualcell.cli import main as cli_main
from virtualcell.core.consumption import ConsumptionStatus
from virtualcell.core.experiment import (
    Measurement,
    MeasurementQuality,
    Observation,
    PassageTimePoint,
)
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.platform.bootstrap import default_registry, seed_registered_domains
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.service import ReasoningService

IMMORTALIZATION = {
    "domain": "immortalization",
    "task": "assess_state",
    "experiment": {
        "species": "bovine",
        "PDL_trend": "increasing",
        "DT_trend": "stable",
        "gammaH2AX": "low",
        "SA_b_gal": "unknown",
        "p16": "low",
        "p21": "low",
        "genomic_stability": "abnormal",
        "adipogenic_retention": "lost",
        "gamaH2AX": "high",
    },
}
ADIPOGENESIS = {
    "domain": "adipogenesis",
    "task": "assess_state",
    "experiment": {
        "PPARG": "high",
        "CEBPA": "high",
        "FABP4": "absent",
        "ADIPOQ": "unknown",
        "lipid_accumulation": "high",
        "lipid_efficiency": "high",
        "morphology": "high",
        "viability": "high",
        "induction_day": 10,
        "OilRedO": "strong",
    },
}


def _service(payload: dict) -> ReasoningResponse:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    service = ReasoningService(store, default_registry())
    return asyncio.run(service.query(ReasoningQuery.model_validate(payload)))


def _states(payload: dict) -> dict[str, str]:
    return {
        entry.submitted_as: entry.status.value
        for entry in _service(payload).measurement_consumption.entries
    }


# --- the state that used to be invisible --------------------------------------


@pytest.mark.parametrize(
    ("payload", "typo"), [(IMMORTALIZATION, "gamaH2AX"), (ADIPOGENESIS, "OilRedO")]
)
def test_an_unrecognised_measurement_no_longer_disappears(payload: dict, typo: str) -> None:
    """Both spellings are plausible and neither is an axis. Before this, submitting either
    produced a response identical to submitting nothing, so a typo was silent."""
    report = _service(payload).measurement_consumption
    assert typo in report.unsupported
    entry = next(e for e in report.entries if e.submitted_as == typo)
    assert entry.canonical_name is None  # it resolved to nothing, and says so
    assert entry.reason  # and says why
    assert entry.affected_status is False


def test_a_near_miss_is_reported_under_the_callers_own_spelling() -> None:
    """`gamaH2AX` next to a consumed `gammaH2AX` is the whole point: the ledger echoes what
    was sent, so the one-letter difference is visible side by side."""
    states = _states(IMMORTALIZATION)
    assert states["gammaH2AX"] == "used_for_status"
    assert states["gamaH2AX"] == "unsupported"


# --- immortalization policy ---------------------------------------------------


def test_immortalization_separates_status_axes_from_safety_axes() -> None:
    """The PR16 separation, now visible to a caller. Genomic stability and retention raise
    flags, add evidence and change the plan — and never the verdict."""
    states = _states(IMMORTALIZATION)
    assert states["p16"] == states["PDL_trend"] == "used_for_status"
    assert states["genomic_stability"] == states["adipogenic_retention"] == "used_for_guidance"

    report = _service(IMMORTALIZATION).measurement_consumption
    guidance = report.by_status(ConsumptionStatus.USED_FOR_GUIDANCE)
    assert all(not e.affected_status for e in guidance)
    assert any("flag:" in purpose for e in guidance for purpose in e.used_for)


def test_an_axis_submitted_as_unknown_is_not_reported_as_consumed() -> None:
    """`SA_b_gal: unknown` is a submitted key with no reading. Calling that 'used' would
    make the verdict look better supported than it is."""
    assert _states(IMMORTALIZATION)["SA_b_gal"] == "not_applicable"


def test_context_fields_are_reported_as_unread_rather_than_implied_to_matter() -> None:
    """A caller who believes `species` steers the reasoning is wrong, and nothing told them
    until now. It is preserved and unread, and the ledger says exactly that."""
    entry = next(
        e
        for e in _service(IMMORTALIZATION).measurement_consumption.entries
        if e.submitted_as == "species"
    )
    assert entry.status is ConsumptionStatus.NOT_APPLICABLE
    assert "no rule in this domain reads it" in (entry.reason or "")


def test_a_task_that_reads_no_measurement_says_so_for_every_one_of_them() -> None:
    """`handle_hypothesis` answers from a fixed, citation-bound policy: no submitted value
    can move it. That is defensible and was completely undiscoverable."""
    states = _states(
        {
            "domain": "immortalization",
            "task": "handle_hypothesis",
            "experiment": {"TERT": "activated", "PGC1A": "activated", "p16": "low"},
        }
    )
    assert set(states.values()) == {"not_applicable", "unsupported"}
    assert states["p16"] == "not_applicable"  # a real axis, simply not read by this task


def test_the_mechanism_task_reads_the_construct_and_nothing_else() -> None:
    states = _states(
        {
            "domain": "immortalization",
            "task": "explain_mechanism",
            "experiment": {"construct": "TERT_plus_CDK4", "p16": "high"},
        }
    )
    assert states["construct"] == "used_for_guidance"  # no status on a mechanism question
    assert states["p16"] == "not_applicable"


# --- adipogenesis policy, which lands differently -----------------------------


def test_adipogenesis_counts_inhibition_and_viability_as_status_axes() -> None:
    """The contrast with immortalization, and the reason this declaration belongs in the
    pack: there, every flag-raising axis is guidance. Here, an active inhibitor reaches
    `differentiation_inhibited` and a failing culture withholds the negative call, so both
    genuinely gate the verdict."""
    states = _states(
        {**ADIPOGENESIS, "experiment": {**ADIPOGENESIS["experiment"], "WNT_signalling": "high"}}
    )
    assert states["WNT_signalling"] == "used_for_status"
    assert states["viability"] == "used_for_status"
    # Only these two refine a call they can never make.
    assert states["lipid_efficiency"] == states["morphology"] == "used_for_guidance"


def test_a_measured_negative_is_consumed_while_an_unmeasured_axis_is_not() -> None:
    """The distinction the adipogenesis vertical exists to protect, now legible from the
    outside: `absent` is a result, `unknown` is a gap."""
    states = _states(ADIPOGENESIS)
    assert states["FABP4"] == "used_for_status"  # measured, and negative
    assert states["ADIPOQ"] == "not_applicable"  # never looked at


def test_the_required_axes_that_drove_the_call_are_recoverable() -> None:
    inputs = _service(ADIPOGENESIS).measurement_consumption.status_inputs
    assert {"PPARG", "CEBPA", "FABP4", "lipid_accumulation"} <= set(inputs)
    assert "ADIPOQ" not in inputs  # unmeasured, so it supported nothing


# --- canonical QC exclusion ---------------------------------------------------


def _run_with(quality: MeasurementQuality):
    from virtualcell.agents.immortalization.adapters import passage_series_to_run, run_consumption
    from virtualcell.agents.immortalization.models import PassageObservation

    run = passage_series_to_run(
        [PassageObservation(passage=10, cumulative_PDL=22.0, DT_hours=40.0)], run_id="test:run-1"
    )
    flagged = run.observations[0].measurements[0]
    run.observations[0].measurements[0] = flagged.model_copy(update={"quality": quality})
    return run_consumption(run)


def test_a_reading_qc_distrusted_is_reported_rather_than_dropped() -> None:
    """The conversion has always skipped a non-`valid` reading, for a good reason: the
    trajectory engine has no notion of a quality flag. What it could not do was *say so*,
    so the value simply vanished."""
    report = _run_with(MeasurementQuality.SUSPECT)
    excluded = report.by_status(ConsumptionStatus.QUALITY_EXCLUDED)
    assert [e.canonical_name for e in excluded] == ["cumulative_PDL"]
    assert "suspect" in (excluded[0].reason or "")
    assert excluded[0].provenance == "test:run-1:observations[0]"


def test_quality_exclusion_is_not_confused_with_an_unmodelled_name() -> None:
    """Both make a value disappear and they mean opposite things: one is a data problem,
    the other a schema gap. Collapsing them would hide the first inside the second."""
    report = _run_with(MeasurementQuality.SUSPECT)
    assert report.unsupported == []  # nothing here is unrecognised

    obs = Observation(
        time_point=PassageTimePoint(kind="passage", value=3),
        measurements=[
            Measurement(name="mystery_readout", value=1.0, quality=MeasurementQuality.VALID)
        ],
    )
    from virtualcell.agents.immortalization.adapters import passage_series_to_run, run_consumption
    from virtualcell.agents.immortalization.models import PassageObservation

    run = passage_series_to_run([PassageObservation(passage=1)], run_id="test:run-2")
    run.observations.append(obs)
    unmodelled = run_consumption(run)
    assert unmodelled.unsupported == ["mystery_readout"]
    assert unmodelled.by_status(ConsumptionStatus.QUALITY_EXCLUDED) == []


def test_a_clean_reading_is_reported_as_reaching_the_trajectory() -> None:
    report = _run_with(MeasurementQuality.VALID)
    assert sorted(report.status_inputs) == ["DT_hours", "cumulative_PDL"]


# --- the same answer on every surface -----------------------------------------


@pytest.mark.parametrize("payload", [IMMORTALIZATION, ADIPOGENESIS])
def test_service_api_and_cli_report_identical_consumption(payload: dict, tmp_path, capsys) -> None:
    service = _service(payload).measurement_consumption.model_dump(mode="json")

    with TestClient(app) as client:
        api = client.post("/reasoning/query", json=payload)
    assert api.status_code == 200
    assert api.json()["measurement_consumption"] == service

    request_file = tmp_path / "query.json"
    request_file.write_text(json.dumps(payload), encoding="utf-8")
    assert cli_main(["query", "--input", str(request_file), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["measurement_consumption"] == service


def test_the_cli_text_view_names_the_unrecognised_measurement(tmp_path, capsys) -> None:
    """The summary a human actually reads. An unsupported name is printed first and
    unconditionally, because it is the line that usually means a mistake."""
    request_file = tmp_path / "query.json"
    request_file.write_text(json.dumps(IMMORTALIZATION), encoding="utf-8")
    assert cli_main(["query", "--input", str(request_file), "--format", "text"]) == 0
    out = capsys.readouterr().out

    assert "measurements:" in out
    assert "not recognised (ignored): gamaH2AX" in out
    assert "used for the status:" in out
    assert "used for guidance only: genomic_stability, adipogenic_retention" in out


# --- additive, not disruptive -------------------------------------------------


def test_the_domain_report_is_untouched_by_transparency() -> None:
    """Transparency is an envelope concern. The vertical's own `DecisionReport` — status,
    tiers, citations, confidences — is byte-identical with and without an unsupported key,
    which is precisely why this feature could not change a benchmark score."""
    with_typo = _service(IMMORTALIZATION)
    clean_payload = {
        **IMMORTALIZATION,
        "experiment": {k: v for k, v in IMMORTALIZATION["experiment"].items() if k != "gamaH2AX"},
    }
    without = _service(clean_payload)

    assert with_typo.domain_details["decision_report"] == without.domain_details["decision_report"]
    assert with_typo.measurement_consumption != without.measurement_consumption


def test_a_response_built_without_a_ledger_is_still_valid() -> None:
    """The field is defaulted, so a pack that has not declared a policy keeps working and
    reports nothing rather than something wrong."""
    response = _service(IMMORTALIZATION)
    rebuilt = ReasoningResponse.model_validate(
        {
            k: v
            for k, v in response.model_dump(mode="json").items()
            if k != "measurement_consumption"
        }
    )
    assert rebuilt.measurement_consumption.entries == []


def test_provenance_points_at_where_the_value_came_from() -> None:
    entries = _service(IMMORTALIZATION).measurement_consumption.entries
    assert {e.provenance for e in entries} == {"query.experiment"}


# --- the contract holds on real responses, not only on hand-built entries -----


@pytest.mark.parametrize("payload", [IMMORTALIZATION, ADIPOGENESIS])
def test_every_entry_a_pack_produces_satisfies_the_contract(payload: dict) -> None:
    """The model refuses a self-contradicting entry, so this cannot fail while the packs
    build entries through the ledger. It is here for the case that matters: a pack that
    later constructs one by hand, or grows a state it forgot to explain."""
    for entry in _service(payload).measurement_consumption.entries:
        recognised = entry.status is not ConsumptionStatus.UNSUPPORTED
        assert (entry.canonical_name is not None) is recognised
        if entry.status in (
            ConsumptionStatus.USED_FOR_STATUS,
            ConsumptionStatus.USED_FOR_GUIDANCE,
        ):
            assert entry.used_for and entry.reason is None
        else:
            assert entry.reason and not entry.used_for


def test_a_recognised_but_unused_axis_still_reports_its_canonical_name() -> None:
    """`unknown` on a real axis is not the same finding as a name nobody recognises, and the
    canonical name is what separates them at a glance."""
    entries = {e.submitted_as: e for e in _service(IMMORTALIZATION).measurement_consumption.entries}
    assert entries["SA_b_gal"].canonical_name == "SA_b_gal"  # known axis, no reading
    assert entries["gamaH2AX"].canonical_name is None  # not an axis at all


def test_the_canonical_path_always_names_where_an_exclusion_came_from() -> None:
    """Provenance is not forced by the model - a general producer may not have one - but on
    this path it is always available, so its absence would be a defect rather than a
    limitation."""
    report = _run_with(MeasurementQuality.SUSPECT)
    assert all(entry.provenance for entry in report.entries)
