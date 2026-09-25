"""B1: what reading quantitative observations against the plan must answer, before the code.

The observations are the platform's own `ExperimentRun`s. A change is classified only by a
rule someone declared; without one, nothing is classified. Comparability is checked before any
value is read: unit, time point, conditions, quality, and the readout's declared assay.
Replicates are classified together only when every pairing agrees — no mean, no test statistic.
The earlier plan is never modified; the comparison is a separate revision.
"""

from __future__ import annotations

from datetime import UTC, datetime

from virtualcell.core.experiment import (
    AcquisitionMode,
    ElapsedTimePoint,
    ExperimentRun,
    Measurement,
    MeasurementQuality,
    Observation,
    OriginKind,
    Provenance,
)
from virtualcell.research.contracts import (
    DecisionRule,
    HostDecision,
    Hypothesis,
    HypothesisSupport,
    ObservationMapping,
    Prediction,
    ProposedExperiment,
    ReadoutSpec,
    ResearchProvenance,
    ResearchReport,
)
from virtualcell.research.observe import compare_observations

RULE = DecisionRule(
    comparison="ratio",
    increase_at_or_above=1.25,
    decrease_at_or_below=0.8,
    no_change_between=[0.9, 1.1],
    declared_by="researcher",
    basis="synthetic development rule",
)


def _report() -> ResearchReport:
    return ResearchReport(
        question="q",
        restated_question="rq",
        provenance=ResearchProvenance(
            backend="host_llm", prompt_version="t", model_calls=0, evidence_offered=0
        ),
        hypotheses=[
            Hypothesis(id=h, statement=h, support=HypothesisSupport.UNVERIFIED_CANDIDATE)
            for h in ("A", "B")
        ],
        experiments=[
            ProposedExperiment(
                id="E",
                design="d",
                controls=["vehicle"],
                measurements=["signal", "detected"],
                readouts=[
                    ReadoutSpec(
                        name="signal", assay="fluorescence", unit="RFU", reference="vehicle"
                    ),
                    ReadoutSpec(name="detected", assay="fluorescence", unit="RFU"),
                ],
                predictions=[
                    Prediction(
                        hypothesis_id="A",
                        readout="signal",
                        expected="decrease",
                        versus="vehicle",
                        mechanism_link_ids=[],
                        assumptions=["assay reads the product linearly"],
                    ),
                    Prediction(
                        hypothesis_id="B", readout="signal", expected="no_change", versus="vehicle"
                    ),
                    Prediction(hypothesis_id="A", readout="detected", expected="absent"),
                    Prediction(hypothesis_id="B", readout="detected", expected="present"),
                ],
            )
        ],
    )


def _m(value, *, name="signal", unit="RFU", quality=MeasurementQuality.VALID, flags=()):
    return Measurement(
        name=name, value=value, unit=unit, quality=quality, quality_flags=list(flags)
    )


def _run(
    obs: list[tuple[str, list[Measurement]]], *, method="fluorescence", day=1.0
) -> ExperimentRun:
    return ExperimentRun(
        schema_version="1.0",
        run_id="dev:synthetic-1",
        provenance=Provenance(
            origin_kind=OriginKind.EXPERIMENT,
            acquisition_mode=AcquisitionMode.MANUAL,
            method=method,
            recorded_at=datetime(2026, 9, 25, tzinfo=UTC),
        ),
        observations=[
            Observation(
                time_point=ElapsedTimePoint(value=day, unit="day"),
                measurements=measurements,
                conditions={"arm": arm},
            )
            for arm, measurements in obs
        ],
    )


def _mapping(**kw) -> ObservationMapping:
    base = {
        "experiment_id": "E",
        "readout": "signal",
        "measurement_name": "signal",
        "unit": "RFU",
        "time_point": {"kind": "elapsed_time", "value": 1.0, "unit": "day"},
        "treatment": {"arm": "compound"},
        "reference": {"arm": "vehicle"},
        "rule": RULE,
    }
    base.update(kw)
    return ObservationMapping(**base)


def _only(result):
    (row,) = result.comparisons
    return row


def _outcomes(row) -> dict[str, str]:
    return {o.hypothesis_id: o.outcome for o in row.by_hypothesis}


def test_a_declared_rule_classifies_a_change_and_each_hypothesis_is_read_against_it() -> None:
    run = _run([("compound", [_m(50.0), _m(55.0)]), ("vehicle", [_m(100.0), _m(98.0)])])

    row = _only(compare_observations(_report(), [], [run], [_mapping()]))

    assert row.status == "compared"
    assert row.observed == "decrease"
    assert _outcomes(row) == {"A": "consistent", "B": "inconsistent"}


def test_no_declared_rule_means_no_classification() -> None:
    run = _run([("compound", [_m(50.0)]), ("vehicle", [_m(100.0)])])

    row = _only(compare_observations(_report(), [], [run], [_mapping(rule=None)]))

    assert row.status == "insufficient"
    assert "no_decision_rule" in row.reasons
    assert row.observed is None


def test_replicates_that_disagree_are_not_averaged_into_a_verdict() -> None:
    run = _run([("compound", [_m(50.0), _m(104.0)]), ("vehicle", [_m(100.0)])])

    row = _only(compare_observations(_report(), [], [run], [_mapping()]))

    assert row.status == "insufficient"
    assert "replicates_disagree" in row.reasons


def test_a_value_between_declared_bands_is_indeterminate() -> None:
    run = _run([("compound", [_m(85.0)]), ("vehicle", [_m(100.0)])])

    row = _only(compare_observations(_report(), [], [run], [_mapping()]))

    assert row.observed == "indeterminate"
    assert set(_outcomes(row).values()) == {"undecided"}


def test_a_unit_other_than_the_rules_is_not_comparable() -> None:
    run = _run([("compound", [_m(50.0, unit="AU")]), ("vehicle", [_m(100.0, unit="AU")])])

    row = _only(compare_observations(_report(), [], [run], [_mapping()]))

    assert row.status == "not_comparable"
    assert "unit_mismatch" in row.reasons


def test_a_missing_reference_arm_is_not_comparable() -> None:
    run = _run([("compound", [_m(50.0)])])

    row = _only(compare_observations(_report(), [], [run], [_mapping()]))

    assert row.status == "not_comparable"
    assert "no_reference_observations" in row.reasons


def test_a_different_assay_than_the_readout_declares_is_not_comparable() -> None:
    run = _run([("compound", [_m(50.0)]), ("vehicle", [_m(100.0)])], method="absorbance")

    row = _only(compare_observations(_report(), [], [run], [_mapping()]))

    assert "assay_mismatch" in row.reasons


def test_suspect_and_bounded_readings_are_left_out_and_counted() -> None:
    run = _run(
        [
            (
                "compound",
                [
                    _m(50.0),
                    _m(10.0, quality=MeasurementQuality.SUSPECT),
                    _m(5.0, flags=["bound:<"]),
                ],
            ),
            ("vehicle", [_m(100.0)]),
        ]
    )

    row = _only(compare_observations(_report(), [], [run], [_mapping()]))

    assert row.status == "compared"
    assert row.left_out == {"suspect": 1, "bounded": 1}


def test_below_detection_reads_absent_and_a_zero_does_not() -> None:
    below = _run(
        [("compound", [_m(None, name="detected", quality=MeasurementQuality.BELOW_DETECTION)])]
    )
    zero = _run([("compound", [_m(0.0, name="detected")])])
    mapping = _mapping(readout="detected", measurement_name="detected", reference=None, rule=None)

    below_row = _only(compare_observations(_report(), [], [below], [mapping]))
    zero_row = _only(compare_observations(_report(), [], [zero], [mapping]))

    assert below_row.observed == "absent"
    assert _outcomes(below_row) == {"A": "consistent", "B": "inconsistent"}
    assert zero_row.status == "insufficient"
    assert "zero_is_not_below_detection" in zero_row.reasons


def test_one_consistent_result_confirms_nothing_and_the_plan_is_untouched() -> None:
    report = _report()
    before = report.model_dump_json()
    run = _run([("compound", [_m(50.0)]), ("vehicle", [_m(100.0)])])

    result = compare_observations(report, [], [run], [_mapping()])

    assert report.model_dump_json() == before
    assert result.prior_plan_sha256 and result.revision_id
    assert result.prior_plan_unchanged is True
    dumped = result.model_dump_json()
    assert "confirmed" not in dumped and "proven" not in dumped
    (row,) = [h for h in result.hypotheses if h.hypothesis_id == "A"]
    assert row.consistent == ["E:signal"]


def test_an_inconsistent_prediction_names_the_dependencies_to_re_examine() -> None:
    run = _run([("compound", [_m(50.0)]), ("vehicle", [_m(100.0)])])

    result = compare_observations(_report(), [], [run], [_mapping()])

    (row,) = [r for r in result.re_examine if r.hypothesis_id == "B"]
    assert row.experiment_id == "E" and row.readout == "signal"


def test_host_decisions_are_kept_as_the_hosts_and_checked_for_targets() -> None:
    run = _run([("compound", [_m(50.0)]), ("vehicle", [_m(100.0)])])
    decisions = [
        HostDecision(target_id="A", decision="hold", reason="one readout"),
        HostDecision(target_id="Z", decision="keep", reason="typo"),
    ]

    result = compare_observations(_report(), [], [run], [_mapping()], decisions=decisions)

    assert [d.target_id for d in result.host_decisions] == ["A", "Z"]
    assert result.decisions_by == "host"
    assert any(f.code == "unknown_decision_target" for f in result.findings)


def test_a_mapping_to_a_readout_nobody_predicted_is_a_finding() -> None:
    run = _run([("compound", [_m(50.0)]), ("vehicle", [_m(100.0)])])

    result = compare_observations(_report(), [], [run], [_mapping(readout="ghost")])

    assert any(f.code == "unknown_readout" for f in result.findings)


def test_only_runs_that_carry_the_readout_are_checked_against_its_assay() -> None:
    signal = _run([("compound", [_m(50.0)]), ("vehicle", [_m(100.0)])])
    other = _run([("compound", [_m(3.0, name="other")])], method="absorbance")
    other = other.model_copy(update={"run_id": "dev:synthetic-2"})

    row = _only(compare_observations(_report(), [], [signal, other], [_mapping()]))

    assert row.status == "compared"
    assert "assay_mismatch" not in row.reasons
