"""B1: reading quantitative observations against a plan's predictions.

The observations are the platform's own :class:`~virtualcell.core.experiment.ExperimentRun`
records; their quality vocabulary, bound flags, units, time points and effective conditions
are reused as they are, and nothing about a measurement is restated here. What this module
adds is the comparison, in a fixed order:

1. **comparability first** — the readout exists in the plan; the run's method is the assay the
   readout declares; the unit is the unit the rule assumes; the time point and condition arms
   are found; readings that are bounded, suspect, excluded, missing or above detection are left
   out and counted, never used;
2. **classification only by a declared rule** — a change is read as increase, decrease or
   no_change only through a :class:`~virtualcell.research.contracts.DecisionRule` someone
   declared. With no rule, nothing is classified. No threshold, mean or test statistic is
   invented: every treatment/reference pairing is classified on its own, and replicates count
   only when every pairing agrees;
3. **each prediction read against the result** — consistent, inconsistent, undecided, or not
   read, with the assumptions, mechanism links and evidence an inconsistent prediction depends
   on, and every other prediction resting on the same ones.

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
    DecisionRule,
    EvidenceItem,
    HostDecision,
    ObservationMapping,
    Prediction,
    ProposedExperiment,
    ResearchReport,
    expectation_kind,
)
from virtualcell.research.plan import PlanFinding

Status = Literal["compared", "insufficient", "not_comparable"]
Outcome = Literal["consistent", "inconsistent", "undecided", "not_read"]

_TIME_POINT = TypeAdapter(TimePoint)

#: Qualities that make a reading unusable as a value. Below detection is handled separately:
#: for a state it is the reading "absent"; for a change it is not a number.
_LEFT_OUT_QUALITIES = {
    MeasurementQuality.MISSING: "missing",
    MeasurementQuality.SUSPECT: "suspect",
    MeasurementQuality.EXCLUDED: "excluded",
    MeasurementQuality.ABOVE_DETECTION: "above_detection",
}


class PredictionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    hypothesis_id: str
    expected: str
    versus: str | None = None
    outcome: Outcome
    note: str | None = None


class ReadoutComparison(BaseModel):
    """One mapping: which readings were used, what they show under the rule, and per hypothesis."""

    experiment_id: str
    readout: str
    measurement_name: str
    run_ids: list[str] = Field(default_factory=list)
    kind: Literal["state", "change"] | None = None
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
    pairwise: list[float] = Field(
        default_factory=list,
        description="Each treatment/reference pairing under the rule's comparison. No mean.",
    )
    pairwise_classes: list[str] = Field(default_factory=list)
    below_detection: int = 0
    left_out: dict[str, int] = Field(
        default_factory=dict, description="Readings not used, counted by why."
    )
    rule: DecisionRule | None = None
    by_hypothesis: list[PredictionOutcome] = Field(default_factory=list)


class HypothesisReading(BaseModel):
    hypothesis_id: str
    consistent: list[str] = Field(default_factory=list)
    inconsistent: list[str] = Field(default_factory=list)
    undecided: list[str] = Field(default_factory=list)
    not_read: list[str] = Field(default_factory=list)


class ReExamine(BaseModel):
    """An inconsistent prediction and what it rested on — the things to look at again."""

    hypothesis_id: str
    experiment_id: str
    readout: str
    expected: str
    observed: str
    basis: str
    evidence_ids: list[str] = Field(default_factory=list)
    ungrounded_evidence_ids: list[str] = Field(default_factory=list)
    mechanism_link_ids: list[str] = Field(default_factory=list)
    mechanism_evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
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
    re_examine: list[ReExamine] = Field(default_factory=list)
    host_decisions: list[HostDecision] = Field(default_factory=list)
    decisions_by: Literal["host"] = "host"
    findings: list[PlanFinding] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)


LIMITS: tuple[str, ...] = (
    "A change is classified only by the rule declared for it. The rule's bounds are whoever "
    "declared them; nothing here checks that they are biologically or statistically adequate.",
    "No mean, variance or test statistic is computed. Each treatment/reference pairing is "
    "classified on its own and replicates count only when every pairing agrees.",
    "'Consistent' means the classified result equals the predicted value. It does not show the "
    "hypothesis holds: other hypotheses may predict the same value, and causes can act together.",
    "'present' means the producer recorded a valid non-zero reading and did not mark it below "
    "detection; the detection limit is the producer's. A zero is not below detection.",
    "Units are compared as written; nothing is converted. The run's method is compared with the "
    "readout's declared assay as written.",
    "Interference seen on one assay is not carried to another; each readout is read on its own.",
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
    findings: list[PlanFinding] = []
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
        re_examine=_re_examine(report, by_id, comparisons),
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
    if not predictions:
        row.reasons.append("unknown_readout")
        findings.append(
            PlanFinding(
                code="unknown_readout",
                where=where,
                detail=f"no prediction in {exp.id!r} names readout {m.readout!r}.",
            )
        )
        return row

    kind: Literal["state", "change"] = "change" if m.reference is not None else "state"
    row.kind = kind
    spec = next((s for s in exp.readouts if _norm(s.name) == _norm(m.readout)), None)
    unit = m.unit if m.unit is not None else (spec.unit if spec else None)
    if spec and spec.unit and m.unit and spec.unit != m.unit:
        row.reasons.append("rule_unit_differs_from_readout_spec")
    if kind == "change" and not any(
        expectation_kind(p.expected.value) == "change" for p in predictions
    ):
        row.reasons.append("reference_given_but_no_change_prediction")

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

    if row.reasons:
        row.status = "not_comparable"
        row.reasons = list(dict.fromkeys(row.reasons))
        row.by_hypothesis = _outcomes(predictions, kind, None, "not comparable")
        return row

    if kind == "state":
        _classify_state(row, t_values, t_below, t_zero)
    else:
        _classify_change(row, t_values, r_values, m.rule, findings, where)
    row.by_hypothesis = _outcomes(
        predictions, kind, row.observed if row.status == "compared" else None, None
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


def _classify_change(
    row: ReadoutComparison,
    t_values: list[float],
    r_values: list[float],
    rule: DecisionRule | None,
    findings: list[PlanFinding],
    where: str,
) -> None:
    if row.below_detection:
        row.left_out["below_detection"] = row.below_detection
    if not t_values or not r_values:
        row.status = "insufficient"
        row.reasons.append("no_usable_readings")
        return
    if rule is None:
        row.status = "insufficient"
        row.reasons.append("no_decision_rule")
        return
    if (
        rule.increase_at_or_above is None
        and rule.decrease_at_or_below is None
        and rule.no_change_between is None
    ):
        row.status = "insufficient"
        row.reasons.append("rule_declares_no_band")
        return
    if rule.comparison == "ratio" and any(r == 0 for r in r_values):
        row.status = "insufficient"
        row.reasons.append("reference_zero_for_ratio")
        return
    overlap = False
    for t, r in product(t_values, r_values):
        value = t / r if rule.comparison == "ratio" else t - r
        row.pairwise.append(round(value, 6))
        classes = _bands(value, rule)
        overlap = overlap or len(classes) > 1
        row.pairwise_classes.append(classes[0] if len(classes) == 1 else "indeterminate")
    if overlap:
        findings.append(
            PlanFinding(
                code="rule_bands_overlap",
                where=where,
                detail="a value fell in more than one declared band; read as indeterminate.",
            )
        )
    distinct = set(row.pairwise_classes)
    if len(distinct) > 1:
        row.status = "insufficient"
        row.reasons.append("replicates_disagree")
        return
    row.status = "compared"
    (row.observed,) = distinct


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


def _outcomes(
    predictions: list[Prediction], kind: str, observed: str | None, why_not: str | None
) -> list[PredictionOutcome]:
    out: list[PredictionOutcome] = []
    for p in predictions:
        expected = p.expected.value
        p_kind = expectation_kind(expected)
        if p_kind != kind:
            outcome, note = "not_read", f"a {p_kind} prediction; this mapping reads a {kind}"
        elif observed is None:
            outcome, note = "not_read", why_not or "nothing classified"
        elif observed == "indeterminate":
            outcome, note = "undecided", "between the declared bands"
        elif kind == "change" and not p.versus:
            outcome, note = "undecided", "the prediction states no reference"
        else:
            outcome = "consistent" if observed == expected else "inconsistent"
            note = None
        out.append(
            PredictionOutcome(
                hypothesis_id=p.hypothesis_id,
                expected=expected,
                versus=p.versus,
                outcome=outcome,
                note=note,
            )
        )
    return out


# --- across mappings ------------------------------------------------------------------------ #


def _by_hypothesis(
    report: ResearchReport, comparisons: list[ReadoutComparison]
) -> list[HypothesisReading]:
    rows = {h.id: HypothesisReading(hypothesis_id=h.id) for h in report.hypotheses}
    for c in comparisons:
        for o in c.by_hypothesis:
            row = rows.get(o.hypothesis_id)
            if row is not None:
                getattr(row, o.outcome).append(f"{c.experiment_id}:{c.readout}")
    return list(rows.values())


def _re_examine(
    report: ResearchReport, by_id: dict[str, EvidenceItem], comparisons: list[ReadoutComparison]
) -> list[ReExamine]:
    links = {m.id: m for m in report.mechanism_links}
    everything = [(e.id, p) for e in report.experiments for p in e.predictions]
    out: list[ReExamine] = []
    for c in comparisons:
        exp = _experiment(report, c.experiment_id)
        if exp is None:
            continue
        for o in c.by_hypothesis:
            if o.outcome != "inconsistent":
                continue
            p = next(
                p
                for p in exp.predictions
                if p.hypothesis_id == o.hypothesis_id and _norm(p.readout) == _norm(c.readout)
            )
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
                    basis=p.basis.value,
                    evidence_ids=list(p.evidence_ids),
                    ungrounded_evidence_ids=[
                        e for e in cited if e in by_id and by_id[e].kind not in GROUNDED_KINDS
                    ],
                    mechanism_link_ids=list(p.mechanism_link_ids),
                    mechanism_evidence_ids=link_evidence,
                    assumptions=list(p.assumptions),
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
