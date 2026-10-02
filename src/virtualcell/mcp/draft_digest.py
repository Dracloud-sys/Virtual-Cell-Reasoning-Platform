"""A shorter reading of one draft check: findings grouped by cause, the plan analysis in brief.

Measured on a real host session (`docs/research_sessions/eval1_persistence/`): one input
mistake, pair strings such as ``"H1 vs H4"`` in ``discriminates``, came back as 39
``unknown_hypothesis_id`` findings and 39 ``discrimination_claimed_without_predictions``
findings that followed from them, the second set listed twice. The three predictions whose
basis was an assumption nobody stated sat only inside ``plan_analysis.prediction_traces``,
and the reply was 337 KB, a third of it each experiment's decision branches copied onto
every one of its 144 prediction traces. The host found the substantive items by writing a
script over the JSON.

Nothing here computes anything new. It regroups what `check_integrity` and `analyze_plan`
already returned, keeps every location and value, and says what it left out and where to
read it. A finding is never dropped to make the reply shorter: a group carries its count
and every occurrence, and a finding that follows from another is nested under it with its
own count rather than deleted.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from virtualcell.research.plan import (
    Conditions,
    Coverage,
    Impact,
    MissingReadoutSpec,
    NonDiscriminating,
    ObjectiveLevel,
    PlanAnalysis,
    UnseparatedPair,
)

#: Trace gaps that are already reported as a finding of their own. Listing them again as a
#: group would count one problem twice.
_GAPS_ALSO_FINDINGS = frozenset({"unknown_mechanism_link"})

#: Where the full detail lives, said on every compact reply.
FULL_VIEW = "Call check_research_draft again with the same arguments and view='full'."


class Occurrence(BaseModel):
    model_config = ConfigDict(frozen=True)

    where: str
    value: str | None = None
    detail: str | None = Field(
        default=None,
        description="Set when this occurrence says more than the group's detail does.",
    )


class FindingGroup(BaseModel):
    """One kind of problem in one field, with every place it occurs."""

    model_config = ConfigDict(frozen=True)

    code: str
    kind: Literal["input", "review"] = Field(
        description=(
            "input: the submitted draft refers to something it does not contain, or two of "
            "its fields disagree; fixing the input resolves it. review: the draft is "
            "well-formed and this is about what it says. Neither judges the biology."
        )
    )
    source: Literal["findings", "prediction_traces"]
    field: str | None = None
    case: str | None = None
    count: int
    detail: str = Field(description="The first occurrence's detail; see occurrences for each.")
    occurrences: list[Occurrence] = Field(default_factory=list)
    caused_by: str | None = Field(
        default=None,
        description=(
            "Set on a derived group whose parent was not found in this reply. Normally a "
            "derived group is nested under its parent in `derived` instead."
        ),
    )
    derived: list[DerivedGroup] = Field(
        default_factory=list,
        description=(
            "Findings that follow from this one and would disappear with it. Counted, not "
            "repeated as separate problems."
        ),
    )


class DerivedGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    count: int
    detail: str
    same_occurrences_as_parent: bool = Field(
        description="True when every derived finding sits at a location and value of the parent."
    )
    occurrences: list[Occurrence] = Field(
        default_factory=list,
        description="Listed only when they are not the parent's own.",
    )


FindingGroup.model_rebuild()


class ExperimentBrief(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str
    hypotheses_with_predictions: list[str] = Field(default_factory=list)
    separated_pairs: list[list[str]] = Field(default_factory=list)
    unseparated_pairs: list[UnseparatedPair] = Field(default_factory=list)
    readout_exclusions: int = 0
    coexistence_notes: int = 0


class MechanismBrief(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    gaps: list[str] = Field(default_factory=list)
    graph_status: str


class EvidenceBrief(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_id: str
    role: str
    span_count: int
    independent_studies: int
    ungrounded_ids: list[str] = Field(default_factory=list)


class PlanSummary(BaseModel):
    """The plan analysis without its per-readout and per-trace detail. Nothing recomputed."""

    model_config = ConfigDict(frozen=True)

    limits: list[str] = Field(default_factory=list)
    conditions: Conditions = Field(default_factory=Conditions)
    unreached_objectives: list[str] = Field(default_factory=list)
    unanswered_sub_questions: list[str] = Field(default_factory=list)
    untested_hypotheses: list[str] = Field(default_factory=list)
    objective_levels: list[ObjectiveLevel] = Field(default_factory=list)
    experiments: list[ExperimentBrief] = Field(default_factory=list)
    pairs_never_separated: list[list[str]] = Field(default_factory=list)
    pairs_not_compared: list[list[str]] = Field(
        default_factory=list,
        description="Pairs not treated as alternatives; see pair_selection in the full view.",
    )
    experiments_without_predictions: list[str] = Field(default_factory=list)
    non_discriminating_experiments: list[NonDiscriminating] = Field(default_factory=list)
    coverage: list[Coverage] = Field(default_factory=list)
    mechanism_links: list[MechanismBrief] = Field(default_factory=list)
    evidence: list[EvidenceBrief] = Field(default_factory=list)
    prediction_count: int = 0
    readout_specs_missing: list[MissingReadoutSpec] = Field(default_factory=list)
    impact: Impact | None = None


def _kind(code: str, case: str | None) -> Literal["input", "review"]:
    if code.startswith(("unknown_", "duplicate_")) or code == "unexpected_model_field":
        return "input"
    if case == "supports_link_not_in_supporting_ids":
        return "input"
    return "review"


def group_findings(
    findings: Iterable[Mapping[str, str]], plan: PlanAnalysis | None
) -> list[FindingGroup]:
    """Group findings by code, field, case and cause; add the prediction-trace gaps.

    Order is input problems first, then review items, each in the order first seen, so the
    first thing a host reads is what to fix in the draft.
    """
    raw: dict[tuple, list[Mapping[str, str]]] = {}
    for finding in findings:
        key = (
            "findings",
            finding["code"],
            finding.get("field"),
            finding.get("case"),
            finding.get("caused_by"),
        )
        raw.setdefault(key, []).append(finding)
    for trace in plan.prediction_traces if plan is not None else []:
        for gap in trace.gaps:
            if gap in _GAPS_ALSO_FINDINGS:
                continue
            where = f"experiment:{trace.experiment_id}:{trace.hypothesis_id}:{trace.readout}"
            key = ("prediction_traces", gap, "experiments[].predictions[]", None, None)
            raw.setdefault(key, []).append({"code": gap, "where": where, "detail": _GAP[gap]})

    groups: dict[tuple, FindingGroup] = {}
    derived: list[tuple[tuple, list[Mapping[str, str]]]] = []
    for key, items in raw.items():
        source, code, field, case, caused_by = key
        if caused_by is not None:
            derived.append((key, items))
            continue
        groups[key] = _group(source, code, field, case, None, items)

    for key, items in derived:
        source, code, field, case, caused_by = key
        parent_key = next(
            (k for k in groups if k[1] == caused_by and k[2] == field and k[0] == source), None
        )
        if parent_key is None:
            groups[key] = _group(source, code, field, case, caused_by, items)
            continue
        parent = groups[parent_key]
        spots = {(o.where, o.value) for o in parent.occurrences}
        mine = [_occurrence(item, items[0]) for item in items]
        same = all((o.where, o.value) in spots for o in mine)
        groups[parent_key] = parent.model_copy(
            update={
                "derived": [
                    *parent.derived,
                    DerivedGroup(
                        code=code,
                        count=len(items),
                        detail=items[0]["detail"],
                        same_occurrences_as_parent=same,
                        occurrences=[] if same else mine,
                    ),
                ]
            }
        )
    ordered = list(groups.values())
    return [g for g in ordered if g.kind == "input"] + [g for g in ordered if g.kind == "review"]


def _occurrence(item: Mapping[str, str], first: Mapping[str, str]) -> Occurrence:
    value, detail = item.get("value"), item["detail"]
    first_value = first.get("value")
    # A detail that differs from the first only by the value it quotes says nothing more.
    templated = (
        value is not None
        and first_value is not None
        and detail == first["detail"].replace(repr(first_value), repr(value))
    )
    return Occurrence(
        where=item["where"],
        value=value,
        detail=None if detail == first["detail"] or templated else detail,
    )


def _group(source, code, field, case, caused_by, items) -> FindingGroup:
    first = items[0]["detail"]
    return FindingGroup(
        code=code,
        kind=_kind(code, case),
        source=source,
        field=field,
        case=case,
        count=len(items),
        detail=first,
        occurrences=[_occurrence(item, items[0]) for item in items],
        caused_by=caused_by,
    )


#: What each trace gap means, said once per group rather than on every trace.
_GAP: dict[str, str] = {
    "basis_unstated": "the prediction does not say how it was arrived at",
    "evidence_observed_without_evidence": "basis is evidence_observed but no evidence id is cited",
    "mechanism_derived_without_links": "basis is mechanism_derived but no mechanism link is named",
    "assumption_without_stated_assumptions": (
        "basis is assumption but the prediction states no assumption"
    ),
    "change_without_reference": "a change is predicted with no versus reference",
    "readout_not_specified": "the readout has no entry in the experiment's readouts",
}


def not_computed(plan: PlanAnalysis | None, groups: list[FindingGroup], what_if: bool) -> list[str]:
    """What the analysis could not compute, and why. Not a finding, and not a pass."""
    out: list[str] = []
    for group in groups:
        if group.code == "unknown_hypothesis_id" and group.field == "experiments[].discriminates":
            per: dict[str, int] = {}
            for o in group.occurrences:
                per[o.where] = per.get(o.where, 0) + 1
            for where, n in per.items():
                out.append(
                    f"{where}: {n} discriminates value(s) are not hypothesis ids, so what the "
                    "experiment was declared to separate is not checked against its "
                    "predictions. What its predictions separate is still computed."
                )
        if (
            group.code == "unknown_hypothesis_id"
            and group.field == "experiments[].predictions[].hypothesis_id"
        ):
            out.append(
                f"{group.count} prediction(s) name a hypothesis id that does not exist and are "
                "left out of every computation."
            )
    if plan is not None:
        for experiment_id in plan.experiments_without_predictions:
            out.append(
                f"experiment:{experiment_id} has no predictions; what it separates is not computed."
            )
        unchecked = [m.id for m in plan.mechanism_links if m.graph.status == "not_checked"]
        if unchecked:
            out.append(
                f"knowledge-graph check not run for {len(unchecked)} mechanism link(s): "
                f"{', '.join(unchecked)}."
            )
    if not what_if:
        out.append("what_if was not sent, so no dependency impact was computed.")
    return out


def summarize_plan(plan: PlanAnalysis) -> PlanSummary:
    return PlanSummary(
        limits=list(plan.limits),
        conditions=plan.conditions,
        unreached_objectives=list(plan.unreached_objectives),
        unanswered_sub_questions=list(plan.unanswered_sub_questions),
        untested_hypotheses=list(plan.untested_hypotheses),
        objective_levels=list(plan.objective_levels),
        experiments=[
            ExperimentBrief(
                experiment_id=e.experiment_id,
                hypotheses_with_predictions=list(e.hypotheses_with_predictions),
                separated_pairs=[list(p.pair) for p in e.separated_pairs],
                unseparated_pairs=list(e.unseparated_pairs),
                readout_exclusions=len(e.readout_exclusions),
                coexistence_notes=sum(len(p.coexistence_notes) for p in e.separated_pairs),
            )
            for e in plan.experiments
        ],
        pairs_never_separated=[list(p) for p in plan.pairs_never_separated],
        pairs_not_compared=[list(s.pair) for s in plan.pair_selection if not s.compared],
        experiments_without_predictions=list(plan.experiments_without_predictions),
        non_discriminating_experiments=list(plan.non_discriminating_experiments),
        coverage=list(plan.coverage),
        mechanism_links=[
            MechanismBrief(id=m.id, gaps=list(m.gaps), graph_status=m.graph.status)
            for m in plan.mechanism_links
        ],
        evidence=[
            EvidenceBrief(
                target_id=r.target_id,
                role=r.role,
                span_count=r.span_count,
                independent_studies=r.independent_studies,
                ungrounded_ids=list(r.ungrounded_ids),
            )
            for r in plan.evidence
        ],
        prediction_count=len(plan.prediction_traces),
        readout_specs_missing=list(plan.readout_specs_missing),
        impact=plan.impact,
    )


#: What the compact view leaves out, each with what it held. Said on every compact reply.
OMITTED: tuple[str, ...] = (
    "findings: the flat list. Every finding is in finding_groups, with its location and value.",
    "plan_analysis.prediction_traces: per-prediction evidence, assumptions and decisions. "
    "Their gaps are in finding_groups (source prediction_traces).",
    "plan_analysis.experiments: per-readout predicted values, coexistence notes, outcome "
    "tables, controls and decision branches. Pairs are in plan_summary.experiments.",
    "plan_analysis.goal_trace, evidence host readings, same_study_spans, pair_selection "
    "reasons and mechanism-link detail (source, relation, target, graph path).",
)
