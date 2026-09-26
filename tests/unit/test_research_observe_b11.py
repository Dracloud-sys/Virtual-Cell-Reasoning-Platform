"""B1.1: what reading observations must answer about references, pairing and assumptions.

Written before the change, from three defects reproduced through the product path:

* R1 — predictions "vs vehicle" were read against an untreated reference arm and compared;
  the mapping never said which plan reference its reference arm stood for;
* R2 — a donor-paired design was read as every treatment × reference combination, and the
  combinations were called replicates;
* R3 — the luciferase check (an experiment testing a measurement assumption, with no hypothesis
  prediction) could not be read, and ATP predictions resting on that assumption stayed
  "consistent" although the check failed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from virtualcell.core.experiment import (
    AcquisitionMode,
    ElapsedTimePoint,
    ExperimentRun,
    Measurement,
    Observation,
    OriginKind,
    Provenance,
)
from virtualcell.research.contracts import (
    AssumptionCheck,
    DecisionRule,
    Hypothesis,
    HypothesisSupport,
    ObservationMapping,
    ObservationPair,
    Prediction,
    ProposedExperiment,
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
LUC = "the compound does not affect luciferase"


def _report(**exp_kw) -> ResearchReport:
    predictions = exp_kw.pop(
        "predictions",
        [
            Prediction(hypothesis_id="A", readout="signal", expected="decrease", versus="vehicle"),
            Prediction(
                hypothesis_id="B",
                readout="signal",
                expected="no_change",
                versus="vehicle",
                assumptions=[LUC],
            ),
        ],
    )
    return ResearchReport(
        question="q",
        restated_question="rq",
        provenance=ResearchProvenance(
            backend="host_llm", prompt_version="t", model_calls=0, evidence_offered=0
        ),
        hypotheses=[
            Hypothesis(id=h, statement=h, support=HypothesisSupport.UNVERIFIED_CANDIDATE, **kw)
            for h, kw in (("A", {}), ("B", {}), ("C", {"mutually_exclusive_with": ["A"]}))
        ],
        experiments=[
            ProposedExperiment(
                id="E",
                design="d",
                controls=["vehicle"],
                measurements=["signal"],
                predictions=predictions,
                **exp_kw,
            ),
            ProposedExperiment(
                id="CHK",
                design="luciferase standard ± compound, no cells",
                measurements=["standard"],
                assumption_checks=[
                    AssumptionCheck(
                        assumption=LUC,
                        readout="standard",
                        expected_if_holds="no_change",
                        versus="standard alone",
                    )
                ],
            ),
        ],
    )


def _run(arms, *, name="signal", run_id="dev:b11-1") -> ExperimentRun:
    """arms: [(conditions, value, observation_id | None)]"""
    return ExperimentRun(
        schema_version="1.0",
        run_id=run_id,
        provenance=Provenance(
            origin_kind=OriginKind.EXPERIMENT,
            acquisition_mode=AcquisitionMode.MANUAL,
            recorded_at=datetime(2026, 9, 25, tzinfo=UTC),
        ),
        observations=[
            Observation(
                observation_id=oid,
                time_point=ElapsedTimePoint(value=1.0, unit="day"),
                measurements=[Measurement(name=name, value=value, unit="RFU")],
                conditions=conditions,
            )
            for conditions, value, oid in arms
        ],
    )


def _mapping(**kw) -> ObservationMapping:
    base = {
        "experiment_id": "E",
        "readout": "signal",
        "measurement_name": "signal",
        "unit": "RFU",
        "treatment": {"arm": "compound"},
        "reference": {"arm": "vehicle"},
        "versus": "vehicle",
        "rule": RULE,
    }
    base.update(kw)
    return ObservationMapping(**base)


def _simple(ref_arm="vehicle"):
    return _run([({"arm": "compound"}, 50.0, None), ({"arm": ref_arm}, 100.0, None)])


def _row(result, experiment_id="E"):
    return next(c for c in result.comparisons if c.experiment_id == experiment_id)


def _outcomes(row):
    return {o.hypothesis_id: o.outcome for o in row.by_hypothesis}


# --- 1. the reference the observation was read against ------------------------------------------


def test_a_different_reference_holds_the_comparison_even_in_the_same_direction() -> None:
    row = _row(
        compare_observations(
            _report(),
            [],
            [_simple("untreated")],
            [_mapping(reference={"arm": "untreated"}, versus="untreated")],
        )
    )

    assert row.observed == "decrease", "the value is still classified and kept"
    assert set(_outcomes(row).values()) == {"held_reference"}
    assert "vehicle" in row.by_hypothesis[0].note and "untreated" in row.by_hypothesis[0].note


def test_a_mapping_that_does_not_name_its_reference_confirms_nothing() -> None:
    row = _row(compare_observations(_report(), [], [_simple()], [_mapping(versus=None)]))

    assert set(_outcomes(row).values()) == {"held_reference"}


def test_the_named_reference_is_matched_as_written_not_by_synonym() -> None:
    row = _row(compare_observations(_report(), [], [_simple()], [_mapping(versus="DMSO vehicle")]))

    assert set(_outcomes(row).values()) == {"held_reference"}


def test_a_matching_reference_is_compared() -> None:
    row = _row(compare_observations(_report(), [], [_simple()], [_mapping()]))

    assert _outcomes(row) == {"A": "consistent", "B": "inconsistent"}


# --- 2. declared pairs, not every combination ----------------------------------------------------


def _donors():
    arms = []
    for donor, (c, v) in {"D1": (50.0, 100.0), "D2": (25.0, 50.0), "D3": (100.0, 200.0)}.items():
        arms.append(({"arm": "compound", "donor": donor}, c, f"{donor}-c"))
        arms.append(({"arm": "vehicle", "donor": donor}, v, f"{donor}-v"))
    return _run(arms)


def _pairs():
    return [
        ObservationPair(treatment_observation_id=f"{d}-c", reference_observation_id=f"{d}-v")
        for d in ("D1", "D2", "D3")
    ]


def test_declared_pairs_are_read_pair_by_pair() -> None:
    row = _row(compare_observations(_report(), [], [_donors()], [_mapping(pairs=_pairs())]))

    assert row.pairing == "declared_pairs"
    assert row.independent_pairs == 3
    assert [p.value for p in row.pairs] == [0.5, 0.5, 0.5]
    assert row.observed == "decrease"


def test_without_pairs_the_combinations_are_not_called_replicates() -> None:
    row = _row(compare_observations(_report(), [], [_donors()], [_mapping()]))

    assert row.pairing == "all_combinations"
    assert row.combinations == 9
    assert row.independent_pairs is None
    assert "combinations_disagree" in row.reasons
    assert "replicates_disagree" not in row.reasons


def test_a_pair_naming_an_observation_in_the_wrong_arm_is_not_comparable() -> None:
    bad = [ObservationPair(treatment_observation_id="D1-v", reference_observation_id="D1-c")]

    row = _row(compare_observations(_report(), [], [_donors()], [_mapping(pairs=bad)]))

    assert row.status == "not_comparable"
    assert "pair_arm_mismatch" in row.reasons


def test_observations_left_out_of_every_pair_are_counted_not_used() -> None:
    row = _row(compare_observations(_report(), [], [_donors()], [_mapping(pairs=_pairs()[:2])]))

    assert row.independent_pairs == 2
    assert row.unpaired_observations == 2


# --- 3 and 4. an assumption check, read without a hypothesis, and what depends on it -------------


def _check_run(value: float):
    return _run(
        [({"arm": "standard + compound"}, value, None), ({"arm": "standard alone"}, 100.0, None)],
        name="standard",
        run_id="dev:b11-chk",
    )


def _check_mapping():
    return _mapping(
        experiment_id="CHK",
        readout="standard",
        measurement_name="standard",
        treatment={"arm": "standard + compound"},
        reference={"arm": "standard alone"},
        versus="standard alone",
    )


def test_an_assumption_check_is_read_without_any_hypothesis() -> None:
    result = compare_observations(_report(), [], [_check_run(100.0)], [_check_mapping()])

    row = _row(result, "CHK")
    assert row.by_hypothesis == []
    (check,) = row.assumption_outcomes
    assert check.assumption == LUC and check.outcome == "holds"
    assert not any(f.code == "unknown_readout" for f in result.findings)


def test_a_failed_check_marks_dependent_interpretations_and_keeps_the_measurement() -> None:
    result = compare_observations(
        _report(), [], [_simple(), _check_run(60.0)], [_mapping(), _check_mapping()]
    )

    (review,) = result.assumption_reviews
    assert review.status == "does_not_hold"
    assert review.dependent_predictions == ["E:B:signal"]
    row = _row(result)
    assert row.observed == "decrease" and row.treatment_values == [50.0]
    b = next(o for o in row.by_hypothesis if o.hypothesis_id == "B")
    assert b.outcome == "inconsistent", "the raw comparison is preserved"
    assert b.assumptions_checked == {LUC: "does_not_hold"}
    assert b.interpretation == "re_examine"
    a = next(o for o in row.by_hypothesis if o.hypothesis_id == "A")
    assert a.interpretation is None, "A does not rest on the assumption; nothing propagates"
    assert any(
        r.hypothesis_id == "B"
        and r.because == ["inconsistent", "assumption_does_not_hold"]
        and r.shaken_assumptions == [LUC]
        for r in result.re_examine
    )


def test_an_assumption_named_nowhere_in_the_plan_is_a_finding() -> None:
    report = _report()
    report.experiments[1].assumption_checks[0] = AssumptionCheck(
        assumption="something nobody assumed", readout="standard", expected_if_holds="no_change"
    )

    result = compare_observations(report, [], [_check_run(100.0)], [_check_mapping()])

    assert any(f.code == "assumption_check_names_no_assumption" for f in result.findings)


# --- 5. each outcome carries its scope; "alone" is not a refutation of coexistence ---------------


def test_an_outcome_records_what_it_was_compared_against() -> None:
    row = _row(compare_observations(_report(), [], [_donors()], [_mapping(pairs=_pairs())]))

    scope = row.by_hypothesis[0].scope
    assert scope.experiment_id == "E" and scope.readout == "signal"
    assert scope.versus == "vehicle" and scope.reference_conditions == {"arm": "vehicle"}
    assert scope.pairing == "declared_pairs" and scope.values == 3
    assert scope.hypothesis_alone is True


def test_an_inconsistent_alone_names_who_was_consistent_and_may_coexist() -> None:
    report = _report(
        predictions=[
            Prediction(hypothesis_id="A", readout="signal", expected="decrease", versus="vehicle"),
            Prediction(hypothesis_id="B", readout="signal", expected="no_change", versus="vehicle"),
            Prediction(hypothesis_id="C", readout="signal", expected="no_change", versus="vehicle"),
        ]
    )

    row = _row(compare_observations(report, [], [_simple()], [_mapping()]))

    b = next(o for o in row.by_hypothesis if o.hypothesis_id == "B")
    c = next(o for o in row.by_hypothesis if o.hypothesis_id == "C")
    assert b.outcome == "inconsistent" and b.may_coexist_with == ["A"]
    assert c.may_coexist_with == [], "C is declared mutually exclusive with A"
