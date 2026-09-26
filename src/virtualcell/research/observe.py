"""B1: reading quantitative observations against a plan's predictions.

The observations are the platform's own :class:`~virtualcell.core.experiment.ExperimentRun`
records; their quality vocabulary, bound flags, units, time points, effective conditions and
observation ids are reused as they are, and nothing about a measurement is restated here. What
this module adds is the comparison, in a fixed order:

1. **comparability first** — the readout exists in the plan; the run's method is the assay the
   readout declares; the unit is the unit the rule assumes; the time point and condition arms
   are found; declared pairs name observations in the right arms; readings that are bounded,
   suspect, excluded, missing or above detection are left out and counted, never used;
2. **classification only by a declared rule** — a change is read as increase, decrease or
   no_change only through a :class:`~virtualcell.research.contracts.DecisionRule` someone
   declared. With no rule, nothing is classified. No threshold, mean or test statistic is
   invented. With declared pairs each pair is classified on its own and the result stands only
   when every pair agrees; without them every treatment reading is set against every reference
   reading, and those **combinations are not independent replicates** and are never counted as
   such;
3. **each prediction read against the result, on the same reference** — a change prediction is
   compared only when the mapping names the plan reference its reference arm stands for and it
   is the prediction's own `versus`, as written. Otherwise the comparison is held. Every outcome
   carries its scope: what was compared, against what, with how many values, for this
   hypothesis alone;
4. **assumption checks** — a readout that tests a measurement assumption (not a hypothesis) is
   read against that assumption. If the check does not hold, every prediction that names the
   assumption is marked for re-examination; its raw comparison is kept, and nothing is carried
   to predictions that do not name it.

The plan is never modified. The result is a separate revision naming the plan it read by hash,
and keep / revise / hold decisions are recorded as the host's, never computed.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from itertools import product
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from virtualcell.core.experiment import (
    ExperimentRun,
    MeasurementQuality,
    TimePoint,
    deduplicate_runs,
)
from virtualcell.research.contracts import (
    GROUNDED_KINDS,
    AssumptionCheck,
    DecisionRule,
    EvidenceItem,
    HostDecision,
    ObservationMapping,
    Prediction,
    ProposedExperiment,
    ResearchReport,
    expectation_kind,
)
from virtualcell.research.plan import PlanFinding, assumption_check_findings

Status = Literal["compared", "insufficient", "not_comparable"]
Outcome = Literal["consistent", "inconsistent", "undecided", "not_read", "held_reference"]
CheckOutcome = Literal["holds", "does_not_hold", "undecided", "not_read", "held_reference"]
Pairing = Literal["declared_pairs", "all_combinations"]

_TIME_POINT = TypeAdapter(TimePoint)

#: Qualities that make a reading unusable as a value. Below detection is handled separately:
#: for a state it is the reading "absent"; for a change it is not a number.
_LEFT_OUT_QUALITIES = {
    MeasurementQuality.MISSING: "missing",
    MeasurementQuality.SUSPECT: "suspect",
    MeasurementQuality.EXCLUDED: "excluded",
    MeasurementQuality.ABOVE_DETECTION: "above_detection",
}

#: An assumption whose check came back in one of these puts its dependants up for re-examination.
_SHAKEN = {"does_not_hold", "conflicting"}


class ComparisonScope(BaseModel):
    """What one outcome was read on: the limits of what it can be used for."""

    model_config = ConfigDict(frozen=True)

    experiment_id: str
    readout: str
    versus: str | None = Field(
        default=None, description="The plan reference the observation's reference arm stands for."
    )
    reference_conditions: dict[str, Any] | None = None
    time_point: dict[str, Any] | None = None
    pairing: Pairing | None = None
    values: int = Field(
        default=0,
        description=(
            "Values classified: declared pairs, or treatment × reference combinations. "
            "Combinations are not independent replicates."
        ),
    )
    hypothesis_alone: bool = Field(
        default=True,
        description="The prediction is for this hypothesis alone; no combination is modelled.",
    )


class PredictionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    hypothesis_id: str
    expected: str
    versus: str | None = None
    outcome: Outcome
    note: str | None = None
    scope: ComparisonScope | None = None
    may_coexist_with: list[str] = Field(
        default_factory=list,
        description=(
            "For an inconsistent outcome: hypotheses consistent on this same readout that are not "
            "declared mutually exclusive with this one. The inconsistency is for this hypothesis "
            "alone and does not rule out it acting together with them."
        ),
    )
    assumptions_checked: dict[str, str] = Field(
        default_factory=dict,
        description="This prediction's assumptions that a check in this revision read, and how.",
    )
    interpretation: Literal["re_examine"] | None = Field(
        default=None,
        description=(
            "re_examine: an assumption this prediction rests on did not hold on its check. The "
            "outcome above is the raw comparison, kept; its reading needs looking at again."
        ),
    )


class AssumptionOutcome(BaseModel):
    """A check read under its declared rule and tested condition; nothing more general."""

    model_config = ConfigDict(frozen=True)

    assumption: str
    expected_if_holds: str
    versus: str | None = None
    outcome: CheckOutcome
    note: str | None = None
    scope: ComparisonScope | None = None


class PairValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    treatment_observation_id: str
    reference_observation_id: str
    value: float | None = None
    classified: str | None = None
    note: str | None = None


class ReadoutComparison(BaseModel):
    """One mapping: which readings were used, what they show under the rule, and per hypothesis."""

    experiment_id: str
    readout: str
    measurement_name: str
    run_ids: list[str] = Field(default_factory=list)
    kind: Literal["state", "change"] | None = None
    versus: str | None = None
    reference_link: Literal["structural", "declared_only"] | None = Field(
        default=None,
        description=(
            "structural: a condition value of the reference arm is the named reference, as "
            "written. declared_only: the mapping names it but the arm's conditions do not carry "
            "it, so change predictions are held. No synonym is inferred."
        ),
    )
    status: Status
    reasons: list[str] = Field(default_factory=list)
    observed: str | None = Field(
        default=None,
        description=(
            "increase / decrease / no_change / indeterminate for a change; present / absent for "
            "a state. None when nothing was classified."
        ),
    )
    treatment_values: list[float] = Field(default_factory=list)
    reference_values: list[float] = Field(default_factory=list)
    pairing: Pairing | None = None
    pairs: list[PairValue] = Field(default_factory=list)
    declared_pairs: int | None = Field(
        default=None, description="Pairs the mapping declares. None when no pairs were declared."
    )
    used_pairs: int | None = Field(
        default=None,
        description=(
            "Declared pairs that gave one usable value each. A count of pairs used, not of "
            "independent biological replicates."
        ),
    )
    pair_independence: Literal["not_established"] | None = Field(
        default=None,
        description=(
            "Whether the pairs are independent donors or experiments. Nothing in the input states "
            "it, so it is never established here; it is the researcher's to say."
        ),
    )
    combinations: int | None = Field(
        default=None,
        description=(
            "Treatment × reference combinations read when no pairs were declared. Not a number "
            "of independent replicates."
        ),
    )
    unpaired_observations: int = Field(
        default=0, description="Observations in either arm that no declared pair names; not used."
    )
    pairwise: list[float] = Field(
        default_factory=list,
        description="Each value classified under the rule's comparison, in order. No mean.",
    )
    pairwise_classes: list[str] = Field(default_factory=list)
    below_detection: int = 0
    left_out: dict[str, int] = Field(
        default_factory=dict, description="Readings not used, counted by why."
    )
    rule: DecisionRule | None = None
    by_hypothesis: list[PredictionOutcome] = Field(default_factory=list)
    assumption_outcomes: list[AssumptionOutcome] = Field(default_factory=list)


class HypothesisReading(BaseModel):
    hypothesis_id: str
    consistent: list[str] = Field(default_factory=list)
    inconsistent: list[str] = Field(default_factory=list)
    undecided: list[str] = Field(default_factory=list)
    not_read: list[str] = Field(default_factory=list)
    held_reference: list[str] = Field(default_factory=list)
    to_re_examine: list[str] = Field(
        default_factory=list, description="Readouts whose reading rests on an assumption shaken."
    )


class AssumptionReview(BaseModel):
    """One measurement assumption, what its checks showed, and what rests on it."""

    assumption: str
    status: Literal["holds", "does_not_hold", "not_established", "conflicting"]
    checks: list[str] = Field(
        default_factory=list, description="experiment:readout=outcome, for each check read."
    )
    dependent_predictions: list[str] = Field(
        default_factory=list,
        description=(
            "Every prediction in the plan (experiment:hypothesis:readout) naming this assumption. "
            "Only these; nothing is inferred for predictions that do not name it."
        ),
    )
    meaning: str = Field(
        default=(
            "Read under the declared rule, on the tested readout, arms and time point only. Not a "
            "general statement that the assay is free of interference, and not a scientific "
            "validation. Predictions that do not name this assumption were not marked because no "
            "dependency is stated; that is not a finding that they are unaffected."
        )
    )


class ReExamine(BaseModel):
    """A prediction to look at again, why, and what it rested on."""

    hypothesis_id: str
    experiment_id: str
    readout: str
    expected: str
    observed: str
    because: list[Literal["inconsistent", "assumption_does_not_hold"]] = Field(default_factory=list)
    basis: str
    evidence_ids: list[str] = Field(default_factory=list)
    ungrounded_evidence_ids: list[str] = Field(default_factory=list)
    mechanism_link_ids: list[str] = Field(default_factory=list)
    mechanism_evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    shaken_assumptions: list[str] = Field(default_factory=list)
    shares_dependencies_with: list[str] = Field(
        default_factory=list,
        description=(
            "Other predictions (experiment:hypothesis:readout) resting on the same assumption, "
            "mechanism link or evidence. Named, not changed."
        ),
    )


class ObservationComparison(BaseModel):
    """A revision beside the plan: what the observations say about its predictions."""

    revision_id: str
    prior_plan_sha256: str
    observations_sha256: str
    prior_plan_unchanged: bool
    runs_used: list[str] = Field(default_factory=list)
    runs_collapsed_as_duplicates: list[str] = Field(default_factory=list)
    comparisons: list[ReadoutComparison] = Field(default_factory=list)
    hypotheses: list[HypothesisReading] = Field(default_factory=list)
    assumption_reviews: list[AssumptionReview] = Field(default_factory=list)
    re_examine: list[ReExamine] = Field(default_factory=list)
    host_decisions: list[HostDecision] = Field(default_factory=list)
    decisions_by: Literal["host"] = "host"
    findings: list[PlanFinding] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)


LIMITS: tuple[str, ...] = (
    "A change is classified only by the rule declared for it. The rule's bounds are whoever "
    "declared them; nothing here checks that they are biologically or statistically adequate.",
    "No mean, variance or test statistic is computed. Declared pairs are classified one by one "
    "and count only when every pair agrees. Without declared pairs every treatment reading is set "
    "against every reference reading; those combinations are not independent replicates.",
    "A change prediction is compared only against the reference it names, as written. A mapping "
    "that does not name its reference, or names another, holds the comparison.",
    "'Consistent' means the classified result equals the predicted value. It does not show the "
    "hypothesis holds: other hypotheses may predict the same value, and causes can act together.",
    "'Inconsistent' means this hypothesis alone does not predict what was seen. Where hypotheses "
    "may coexist, another may account for the result; it is not a refutation.",
    "'present' means the producer recorded a valid non-zero reading and did not mark it below "
    "detection; the detection limit is the producer's. A zero is not below detection.",
    "Units are compared as written; nothing is converted. The run's method is compared with the "
    "readout's declared assay as written.",
    "An assumption check holds or does not hold under its declared rule and tested condition "
    "only. It marks the predictions that name that assumption; the others are left unmarked "
    "because no dependency is stated, which does not mean they are unaffected. Interference seen "
    "on one assay is not carried to another.",
    "A named reference is compared only when the reference arm's own conditions carry that name. "
    "A name the conditions do not carry is a declaration, and the comparison is held.",
    "The plan is not modified. Keep, revise and hold are the host's proposals and the "
    "researcher's decision.",
)


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def _sha(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def compare_observations(
    report: ResearchReport,
    evidence: list[EvidenceItem],
    runs: list[ExperimentRun],
    mappings: list[ObservationMapping],
    decisions: list[HostDecision] | None = None,
) -> ObservationComparison:
    prior = _sha(report.model_dump(mode="json"))
    findings: list[PlanFinding] = list(assumption_check_findings(report))
    by_id = {item.id: item for item in evidence}

    dedup = deduplicate_runs(list(runs))
    for dropped in dedup.collapsed:
        findings.append(
            PlanFinding(
                code="duplicate_run",
                where=f"run:{dropped}",
                detail="reports the same observations as an earlier run; read once.",
            )
        )
    usable_runs = dedup.runs

    comparisons = [_compare(report, usable_runs, m, findings) for m in mappings]
    _mark_coexistence(report, comparisons)
    reviews = _assumption_reviews(report, comparisons, findings)
    comparisons = _apply_reviews(report, comparisons, reviews)
    decisions = list(decisions or [])
    _check_decisions(report, decisions, findings)

    observations = _sha(
        {
            "runs": [r.model_dump(mode="json") for r in usable_runs],
            "mappings": [m.model_dump(mode="json") for m in mappings],
        }
    )
    decisions_sha = _sha([d.model_dump(mode="json") for d in decisions])
    return ObservationComparison(
        revision_id="rev-" + _sha([prior, observations, decisions_sha])[:16],
        prior_plan_sha256=prior,
        observations_sha256=observations,
        prior_plan_unchanged=_sha(report.model_dump(mode="json")) == prior,
        runs_used=[r.run_id for r in usable_runs],
        runs_collapsed_as_duplicates=list(dedup.collapsed),
        comparisons=comparisons,
        hypotheses=_by_hypothesis(report, comparisons),
        assumption_reviews=reviews,
        re_examine=_re_examine(report, by_id, comparisons, reviews),
        host_decisions=decisions,
        findings=findings,
        limits=list(LIMITS),
    )


# --- one mapping ---------------------------------------------------------------------------- #


def _experiment(report: ResearchReport, experiment_id: str) -> ProposedExperiment | None:
    return next((e for e in report.experiments if e.id == experiment_id), None)


def _matches(conditions: dict[str, Any], wanted: dict[str, Any]) -> bool:
    return all(k in conditions and conditions[k] == v for k, v in wanted.items())


def _compare(
    report: ResearchReport,
    runs: list[ExperimentRun],
    m: ObservationMapping,
    findings: list[PlanFinding],
) -> ReadoutComparison:
    where = f"mapping:{m.experiment_id}:{m.readout}"
    row = ReadoutComparison(
        experiment_id=m.experiment_id,
        readout=m.readout,
        measurement_name=m.measurement_name,
        versus=m.versus,
        reference_link=_reference_link(m),
        rule=m.rule,
        status="not_comparable",
    )
    exp = _experiment(report, m.experiment_id)
    if exp is None:
        row.reasons.append("unknown_experiment")
        findings.append(
            PlanFinding(
                code="unknown_experiment",
                where=where,
                detail=f"{m.experiment_id!r} is not an experiment in the plan.",
            )
        )
        return row
    predictions = [p for p in exp.predictions if _norm(p.readout) == _norm(m.readout)]
    checks = [c for c in exp.assumption_checks if _norm(c.readout) == _norm(m.readout)]
    if not predictions and not checks:
        row.reasons.append("unknown_readout")
        findings.append(
            PlanFinding(
                code="unknown_readout",
                where=where,
                detail=(
                    f"no prediction or assumption check in {exp.id!r} names readout {m.readout!r}."
                ),
            )
        )
        return row

    kind: Literal["state", "change"] = "change" if m.reference is not None else "state"
    row.kind = kind
    spec = next((s for s in exp.readouts if _norm(s.name) == _norm(m.readout)), None)
    unit = m.unit if m.unit is not None else (spec.unit if spec else None)
    if spec and spec.unit and m.unit and spec.unit != m.unit:
        row.reasons.append("rule_unit_differs_from_readout_spec")
    expected_values = [p.expected.value for p in predictions]
    expected_values += [c.expected_if_holds.value for c in checks]
    if kind == "change" and not any(expectation_kind(v) == "change" for v in expected_values):
        row.reasons.append("reference_given_but_no_change_prediction")
    if kind == "state" and m.pairs:
        row.reasons.append("pairs_need_a_reference_arm")
    if spec and spec.reference and m.versus and _norm(spec.reference) != _norm(m.versus):
        findings.append(
            PlanFinding(
                code="mapping_reference_differs_from_readout_spec",
                where=where,
                detail=(
                    f"the readout spec's reference is {spec.reference!r}; the mapping says its "
                    f"reference arm stands for {m.versus!r}."
                ),
            )
        )

    time_point = None
    if m.time_point is not None:
        try:
            time_point = _TIME_POINT.validate_python(m.time_point)
        except ValidationError:
            row.reasons.append("time_point_not_readable")

    selected = [r for r in runs if not m.run_ids or r.run_id in m.run_ids]
    missing_runs = [rid for rid in m.run_ids if rid not in {r.run_id for r in runs}]
    if missing_runs:
        row.reasons.append("run_not_supplied")
    row.run_ids = [r.run_id for r in selected]

    treatment: list = []
    reference: list = []
    #: observation_id -> ("t" | "r", readings), for declared pairs. Ids are the runs' own.
    arms: dict[str, tuple[str, list]] = {}
    unidentified = 0
    other_time = 0
    for run in selected:
        for obs in run.observations:
            readings = [x for x in obs.measurements if x.name == m.measurement_name]
            if not readings:
                continue
            if time_point is not None and obs.time_point != time_point:
                other_time += len(readings)
                continue
            conditions = run.effective_conditions(obs)
            is_t = _matches(conditions, m.treatment)
            is_r = m.reference is not None and _matches(conditions, m.reference)
            if is_t and is_r:
                _add(row.reasons, "observation_matches_both_arms")
                continue
            if (is_t or is_r) and spec and spec.assay:
                # A measurement's own provenance wins over the run's, as it does everywhere a
                # run is read; only readings that would be used are checked.
                for reading in readings:
                    method = (
                        reading.provenance.method
                        if reading.provenance and reading.provenance.method
                        else run.provenance.method
                    )
                    if method is None:
                        _add(row.reasons, "run_method_unstated")
                    elif _norm(method) != _norm(spec.assay):
                        _add(row.reasons, "assay_mismatch")
            if is_t or is_r:
                if obs.observation_id is None:
                    unidentified += 1
                elif obs.observation_id in arms:
                    _add(row.reasons, "duplicate_observation_id")
                else:
                    arms[obs.observation_id] = ("t" if is_t else "r", readings)
            if is_t:
                treatment.extend(readings)
            elif is_r:
                reference.extend(readings)

    if not treatment:
        row.reasons.append(
            "no_observations_at_time_point" if other_time else "no_treatment_observations"
        )
    if kind == "change" and not reference:
        row.reasons.append(
            "no_observations_at_time_point" if other_time else "no_reference_observations"
        )
    for reading in [*treatment, *reference]:
        if unit is not None and reading.unit != unit:
            _add(row.reasons, "unit_mismatch")

    t_values, t_below, t_zero = _usable(treatment, row.left_out)
    r_values, r_below, _r_zero = _usable(reference, row.left_out)
    row.below_detection = t_below + r_below
    row.treatment_values = t_values
    row.reference_values = r_values
    # Readings that exist but that quality leaves out entirely make the arm unreadable: that
    # is a comparability failure, not a shortage of data.
    if treatment and not t_values and not (kind == "state" and t_below):
        _add(row.reasons, "all_treatment_readings_left_out")
    if kind == "change" and reference and not r_values:
        _add(row.reasons, "all_reference_readings_left_out")

    paired: _Paired = []
    if kind == "change" and m.pairs:
        _reject_reused_observations(m, row)
        paired = _declared_pairs(m, arms, row)
        named = {p.treatment_observation_id for p in m.pairs}
        named |= {p.reference_observation_id for p in m.pairs}
        row.unpaired_observations = unidentified + sum(1 for oid in arms if oid not in named)

    if row.reasons:
        row.status = "not_comparable"
        row.reasons = list(dict.fromkeys(row.reasons))
        _read_all(row, predictions, checks, kind, None, "not comparable", m)
        return row

    if kind == "state":
        _classify_state(row, t_values, t_below, t_zero)
    elif m.pairs:
        _classify_pairs(row, paired, m.rule, findings, where)
    else:
        _classify_combinations(row, t_values, r_values, m.rule, findings, where)
    _read_all(
        row, predictions, checks, kind, row.observed if row.status == "compared" else None, None, m
    )
    return row


def _add(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _usable(readings: list, left_out: dict[str, int]) -> tuple[list[float], int, int]:
    """Point estimates, the below-detection count, and the count of exact zeros."""
    values: list[float] = []
    below = 0
    zeros = 0
    counts: Counter[str] = Counter(left_out)
    for x in readings:
        if x.quality is MeasurementQuality.BELOW_DETECTION:
            below += 1
            continue
        if x.quality in _LEFT_OUT_QUALITIES:
            counts[_LEFT_OUT_QUALITIES[x.quality]] += 1
            continue
        if x.bound is not None:
            counts["bounded"] += 1
            continue
        if not x.is_numeric:
            counts["not_numeric"] += 1
            continue
        value = x.numeric_value()
        if value == 0:
            zeros += 1
        values.append(value)
    left_out.clear()
    left_out.update({k: v for k, v in counts.items() if v})
    return values, below, zeros


_Paired = list[tuple[PairValue, tuple[float, float] | None]]


def _reject_reused_observations(m: ObservationMapping, row: ReadoutComparison) -> None:
    """An observation may stand in one pair only; reuse would inflate the pair count."""
    named = [p.treatment_observation_id for p in m.pairs]
    named += [p.reference_observation_id for p in m.pairs]
    if len(named) != len(set(named)):
        _add(row.reasons, "observation_in_more_than_one_pair")


def _declared_pairs(
    m: ObservationMapping, arms: dict[str, tuple[str, list]], row: ReadoutComparison
) -> _Paired:
    """Each declared pair with its two point estimates, or with why it cannot give one value."""
    out: _Paired = []
    for pair in m.pairs:
        t_id, r_id = pair.treatment_observation_id, pair.reference_observation_id
        t, r = arms.get(t_id), arms.get(r_id)
        if t is None or r is None:
            _add(row.reasons, "pair_observation_not_found")
            out.append(
                (_pair(t_id, r_id, "an observation this pair names is in neither arm"), None)
            )
            continue
        if t[0] != "t" or r[0] != "r":
            _add(row.reasons, "pair_arm_mismatch")
            out.append((_pair(t_id, r_id, "the pair names observations from the wrong arms"), None))
            continue
        t_vals, _, _ = _usable(t[1], {})
        r_vals, _, _ = _usable(r[1], {})
        if len(t_vals) != 1 or len(r_vals) != 1:
            note = (
                f"needs one usable reading on each side; has {len(t_vals)} and {len(r_vals)}. "
                "Readings within one observation are not averaged."
            )
            out.append((_pair(t_id, r_id, note), None))
            continue
        out.append((_pair(t_id, r_id, None), (t_vals[0], r_vals[0])))
    return out


def _pair(t_id: str, r_id: str, note: str | None) -> PairValue:
    return PairValue(treatment_observation_id=t_id, reference_observation_id=r_id, note=note)


def _classify_state(row: ReadoutComparison, values: list[float], below: int, zeros: int) -> None:
    if zeros:
        row.status = "insufficient"
        row.reasons.append("zero_is_not_below_detection")
        return
    if any(v < 0 for v in values):
        row.status = "insufficient"
        row.reasons.append("negative_value_for_a_state")
        return
    states = ({"absent"} if below else set()) | ({"present"} if values else set())
    if not states:
        row.status = "insufficient"
        row.reasons.append("no_usable_readings")
        return
    if len(states) > 1:
        row.status = "insufficient"
        row.reasons.append("replicates_disagree")
        return
    row.status = "compared"
    (row.observed,) = states


def _rule_usable(row: ReadoutComparison, rule: DecisionRule | None) -> bool:
    if rule is None:
        row.status = "insufficient"
        row.reasons.append("no_decision_rule")
        return False
    if (
        rule.increase_at_or_above is None
        and rule.decrease_at_or_below is None
        and rule.no_change_between is None
    ):
        row.status = "insufficient"
        row.reasons.append("rule_declares_no_band")
        return False
    return True


def _classify_values(
    row: ReadoutComparison,
    values: list[float],
    rule: DecisionRule,
    findings: list[PlanFinding],
    where: str,
    disagree: str,
) -> list[str]:
    classes: list[str] = []
    overlap = False
    for value in values:
        row.pairwise.append(round(value, 6))
        bands = _bands(value, rule)
        overlap = overlap or len(bands) > 1
        classes.append(bands[0] if len(bands) == 1 else "indeterminate")
    row.pairwise_classes = classes
    if overlap:
        findings.append(
            PlanFinding(
                code="rule_bands_overlap",
                where=where,
                detail="a value fell in more than one declared band; read as indeterminate.",
            )
        )
    distinct = set(classes)
    if len(distinct) > 1:
        row.status = "insufficient"
        row.reasons.append(disagree)
    elif distinct:
        row.status = "compared"
        (row.observed,) = distinct
    else:
        row.status = "insufficient"
        row.reasons.append("no_usable_readings")
    return classes


def _compare_value(t: float, r: float, rule: DecisionRule) -> float:
    return t / r if rule.comparison == "ratio" else t - r


def _classify_combinations(
    row: ReadoutComparison,
    t_values: list[float],
    r_values: list[float],
    rule: DecisionRule | None,
    findings: list[PlanFinding],
    where: str,
) -> None:
    row.pairing = "all_combinations"
    if row.below_detection:
        row.left_out["below_detection"] = row.below_detection
    if not t_values or not r_values:
        row.status = "insufficient"
        row.reasons.append("no_usable_readings")
        return
    if not _rule_usable(row, rule):
        return
    if rule.comparison == "ratio" and any(r == 0 for r in r_values):
        row.status = "insufficient"
        row.reasons.append("reference_zero_for_ratio")
        return
    values = [_compare_value(t, r, rule) for t, r in product(t_values, r_values)]
    row.combinations = len(values)
    _classify_values(row, values, rule, findings, where, "combinations_disagree")


def _classify_pairs(
    row: ReadoutComparison,
    paired: _Paired,
    rule: DecisionRule | None,
    findings: list[PlanFinding],
    where: str,
) -> None:
    row.pairing = "declared_pairs"
    row.pair_independence = "not_established"
    if row.below_detection:
        row.left_out["below_detection"] = row.below_detection
    usable = [(p, raw) for p, raw in paired if raw is not None]
    unusable = [p for p, raw in paired if raw is None]
    row.declared_pairs = len(paired)
    row.used_pairs = len(usable)
    row.pairs = [p for p, _ in paired]
    if not usable:
        row.status = "insufficient"
        row.reasons.append("no_usable_pairs")
        return
    if not _rule_usable(row, rule):
        return
    if rule.comparison == "ratio" and any(r == 0 for _, (_, r) in usable):
        row.status = "insufficient"
        row.reasons.append("reference_zero_for_ratio")
        return
    values = [_compare_value(t, r, rule) for _, (t, r) in usable]
    classes = _classify_values(row, values, rule, findings, where, "pairs_disagree")
    row.pairs = [
        p.model_copy(update={"value": round(v, 6), "classified": c})
        for (p, _), v, c in zip(usable, values, classes, strict=True)
    ] + unusable


def _bands(value: float, rule: DecisionRule) -> list[str]:
    out: list[str] = []
    if rule.increase_at_or_above is not None and value >= rule.increase_at_or_above:
        out.append("increase")
    if rule.decrease_at_or_below is not None and value <= rule.decrease_at_or_below:
        out.append("decrease")
    if rule.no_change_between is not None:
        low, high = rule.no_change_between
        if low <= value <= high:
            out.append("no_change")
    return out or ["indeterminate"]


def _scope(row: ReadoutComparison, m: ObservationMapping) -> ComparisonScope:
    return ComparisonScope(
        experiment_id=row.experiment_id,
        readout=row.readout,
        versus=m.versus,
        reference_conditions=m.reference,
        time_point=m.time_point,
        pairing=row.pairing,
        values=len(row.pairwise)
        if row.kind == "change"
        else len(row.treatment_values) + row.below_detection,
    )


def _reference_link(m: ObservationMapping) -> Literal["structural", "declared_only"] | None:
    if m.reference is None or m.versus is None:
        return None
    carried = {_norm(v) for v in m.reference.values() if isinstance(v, str)}
    return "structural" if _norm(m.versus) in carried else "declared_only"


def _read(
    expected: str,
    versus: str | None,
    unresolved: str | None,
    kind: str,
    observed: str | None,
    why_not: str | None,
    m: ObservationMapping,
) -> tuple[str, str | None]:
    """(match | mismatch | undecided | not_read | held_reference, note)."""
    p_kind = expectation_kind(expected)
    if p_kind is None:
        return "not_read", unresolved or "the plan predicts no value here"
    if p_kind != kind:
        return "not_read", f"a {p_kind} prediction; this mapping reads a {kind}"
    if observed is None:
        return "not_read", why_not or "nothing classified"
    if kind == "change":
        if not versus:
            return "held_reference", "the prediction states no reference"
        if m.versus is None:
            return "held_reference", (
                f"the prediction is vs {versus!r}; the mapping does not say which plan reference "
                "its reference arm stands for"
            )
        if _norm(versus) != _norm(m.versus):
            return "held_reference", (
                f"the prediction is vs {versus!r}; the observation's reference arm stands for "
                f"{m.versus!r}. Compared only on the same reference."
            )
        if _reference_link(m) != "structural":
            return "held_reference", (
                f"the mapping names {m.versus!r}, but the reference arm is selected by "
                f"{m.reference!r}, which does not carry that name. The link is only declared."
            )
    if observed == "indeterminate":
        return "undecided", "between the declared bands"
    return ("match" if observed == expected else "mismatch"), None


def _read_all(
    row: ReadoutComparison,
    predictions: list[Prediction],
    checks: list[AssumptionCheck],
    kind: str,
    observed: str | None,
    why_not: str | None,
    m: ObservationMapping,
) -> None:
    scope = _scope(row, m)
    outcomes: list[PredictionOutcome] = []
    for p in predictions:
        result, note = _read(p.expected.value, p.versus, p.unresolved, kind, observed, why_not, m)
        outcome = {"match": "consistent", "mismatch": "inconsistent"}.get(result, result)
        outcomes.append(
            PredictionOutcome(
                hypothesis_id=p.hypothesis_id,
                expected=p.expected.value,
                versus=p.versus,
                outcome=outcome,
                note=note,
                scope=scope,
            )
        )
    row.by_hypothesis = outcomes
    assumption_outcomes: list[AssumptionOutcome] = []
    for c in checks:
        result, note = _read(c.expected_if_holds.value, c.versus, None, kind, observed, why_not, m)
        outcome = {"match": "holds", "mismatch": "does_not_hold"}.get(result, result)
        assumption_outcomes.append(
            AssumptionOutcome(
                assumption=c.assumption,
                expected_if_holds=c.expected_if_holds.value,
                versus=c.versus,
                outcome=outcome,
                note=note,
                scope=scope,
            )
        )
    row.assumption_outcomes = assumption_outcomes


# --- across mappings ------------------------------------------------------------------------ #


def _exclusive(report: ResearchReport) -> set[frozenset[str]]:
    return {
        frozenset({h.id, other}) for h in report.hypotheses for other in h.mutually_exclusive_with
    }


def _mark_coexistence(report: ResearchReport, comparisons: list[ReadoutComparison]) -> None:
    """Name, per inconsistent outcome, who was consistent on that same readout and may coexist.

    Only hypotheses already read on this readout are named; no combination is built and no mixed
    effect is guessed.
    """
    exclusive = _exclusive(report)
    for row in comparisons:
        consistent = [o.hypothesis_id for o in row.by_hypothesis if o.outcome == "consistent"]
        row.by_hypothesis = [
            o.model_copy(
                update={
                    "may_coexist_with": [
                        h
                        for h in consistent
                        if h != o.hypothesis_id and frozenset({h, o.hypothesis_id}) not in exclusive
                    ]
                }
            )
            if o.outcome == "inconsistent"
            else o
            for o in row.by_hypothesis
        ]


def _dependants(report: ResearchReport, assumption: str) -> list[str]:
    key = _norm(assumption)
    return [
        f"{e.id}:{p.hypothesis_id}:{p.readout}"
        for e in report.experiments
        for p in e.predictions
        if key in {_norm(a) for a in p.assumptions}
    ]


def _assumption_reviews(
    report: ResearchReport, comparisons: list[ReadoutComparison], findings: list[PlanFinding]
) -> list[AssumptionReview]:
    seen: dict[str, tuple[str, list[str], list[str]]] = {}
    for row in comparisons:
        for a in row.assumption_outcomes:
            text, labels, outcomes = seen.setdefault(_norm(a.assumption), (a.assumption, [], []))
            labels.append(f"{row.experiment_id}:{row.readout}={a.outcome}")
            outcomes.append(a.outcome)
    reviews: list[AssumptionReview] = []
    for text, labels, outcomes in seen.values():
        if "does_not_hold" in outcomes and "holds" in outcomes:
            status = "conflicting"
            findings.append(
                PlanFinding(
                    code="assumption_checks_conflict",
                    where=f"assumption:{text}",
                    detail="one check held and another did not; its dependants are re-examined.",
                )
            )
        elif "does_not_hold" in outcomes:
            status = "does_not_hold"
        elif outcomes and all(o == "holds" for o in outcomes):
            status = "holds"
        else:
            status = "not_established"
        reviews.append(
            AssumptionReview(
                assumption=text,
                status=status,
                checks=labels,
                dependent_predictions=_dependants(report, text),
            )
        )
    return reviews


def _prediction(report: ResearchReport, experiment_id: str, hypothesis_id: str, readout: str):
    exp = _experiment(report, experiment_id)
    if exp is None:
        return None
    return next(
        (
            p
            for p in exp.predictions
            if p.hypothesis_id == hypothesis_id and _norm(p.readout) == _norm(readout)
        ),
        None,
    )


def _apply_reviews(
    report: ResearchReport, comparisons: list[ReadoutComparison], reviews: list[AssumptionReview]
) -> list[ReadoutComparison]:
    """Mark each outcome whose prediction names a checked assumption. Outcomes are not changed."""
    status = {_norm(r.assumption): r.status for r in reviews}
    if not status:
        return comparisons
    for row in comparisons:
        updated = []
        for o in row.by_hypothesis:
            p = _prediction(report, row.experiment_id, o.hypothesis_id, row.readout)
            checked = {
                a: status[_norm(a)] for a in (p.assumptions if p else []) if _norm(a) in status
            }
            if checked:
                o = o.model_copy(
                    update={
                        "assumptions_checked": checked,
                        "interpretation": "re_examine"
                        if any(s in _SHAKEN for s in checked.values())
                        else None,
                    }
                )
            updated.append(o)
        row.by_hypothesis = updated
    return comparisons


def _by_hypothesis(
    report: ResearchReport, comparisons: list[ReadoutComparison]
) -> list[HypothesisReading]:
    rows = {h.id: HypothesisReading(hypothesis_id=h.id) for h in report.hypotheses}
    for c in comparisons:
        for o in c.by_hypothesis:
            row = rows.get(o.hypothesis_id)
            if row is not None:
                getattr(row, o.outcome).append(f"{c.experiment_id}:{c.readout}")
                if o.interpretation == "re_examine":
                    row.to_re_examine.append(f"{c.experiment_id}:{c.readout}")
    return list(rows.values())


def _re_examine(
    report: ResearchReport,
    by_id: dict[str, EvidenceItem],
    comparisons: list[ReadoutComparison],
    reviews: list[AssumptionReview],
) -> list[ReExamine]:
    links = {m.id: m for m in report.mechanism_links}
    shaken = {_norm(r.assumption) for r in reviews if r.status in _SHAKEN}
    everything = [(e.id, p) for e in report.experiments for p in e.predictions]
    out: list[ReExamine] = []
    for c in comparisons:
        exp = _experiment(report, c.experiment_id)
        if exp is None:
            continue
        for o in c.by_hypothesis:
            because = []
            if o.outcome == "inconsistent":
                because.append("inconsistent")
            if o.interpretation == "re_examine":
                because.append("assumption_does_not_hold")
            if not because:
                continue
            p = _prediction(report, c.experiment_id, o.hypothesis_id, c.readout)
            link_evidence = list(
                dict.fromkeys(
                    e
                    for lid in p.mechanism_link_ids
                    if lid in links
                    for e in links[lid].evidence_ids
                )
            )
            cited = [*p.evidence_ids, *link_evidence]
            deps = {("a", _norm(a)) for a in p.assumptions}
            deps |= {("m", lid) for lid in p.mechanism_link_ids}
            deps |= {("e", e) for e in p.evidence_ids}
            shared = []
            for eid, q in everything:
                if q is p:
                    continue
                q_deps = {("a", _norm(a)) for a in q.assumptions}
                q_deps |= {("m", lid) for lid in q.mechanism_link_ids}
                q_deps |= {("e", e) for e in q.evidence_ids}
                if deps & q_deps:
                    shared.append(f"{eid}:{q.hypothesis_id}:{q.readout}")
            out.append(
                ReExamine(
                    hypothesis_id=p.hypothesis_id,
                    experiment_id=exp.id,
                    readout=p.readout,
                    expected=p.expected.value,
                    observed=c.observed or "",
                    because=because,
                    basis=p.basis.value,
                    evidence_ids=list(p.evidence_ids),
                    ungrounded_evidence_ids=[
                        e for e in cited if e in by_id and by_id[e].kind not in GROUNDED_KINDS
                    ],
                    mechanism_link_ids=list(p.mechanism_link_ids),
                    mechanism_evidence_ids=link_evidence,
                    assumptions=list(p.assumptions),
                    shaken_assumptions=[a for a in p.assumptions if _norm(a) in shaken],
                    shares_dependencies_with=shared,
                )
            )
    return out


def _check_decisions(
    report: ResearchReport, decisions: list[HostDecision], findings: list[PlanFinding]
) -> None:
    experiments = {e.id for e in report.experiments}
    targets = {h.id for h in report.hypotheses} | experiments
    targets |= {m.id for m in report.mechanism_links}
    targets |= {f"{e.id}:{p.readout}" for e in report.experiments for p in e.predictions}
    targets |= {f"{e.id}:{c.readout}" for e in report.experiments for c in e.assumption_checks}
    assumptions = {
        _norm(a) for e in report.experiments for p in e.predictions for a in p.assumptions
    }
    assumptions |= {_norm(a) for a in report.assumptions}
    for d in decisions:
        if d.target_id not in targets and _norm(d.target_id) not in assumptions:
            findings.append(
                PlanFinding(
                    code="unknown_decision_target",
                    where=f"decision:{d.target_id}",
                    detail="names no hypothesis, experiment, link, readout or assumption.",
                )
            )
        for nxt in d.next_experiment_ids:
            if nxt not in experiments:
                findings.append(
                    PlanFinding(
                        code="unknown_next_experiment",
                        where=f"decision:{d.target_id}",
                        detail=f"{nxt!r} is not an experiment in the plan.",
                    )
                )
