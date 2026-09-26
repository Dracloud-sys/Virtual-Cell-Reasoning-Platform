"""What follows, by code, from a research plan the host wrote.

The host writes the objectives, the hypotheses, the candidate mechanism links, what each
hypothesis predicts for each readout, and what each piece of evidence means. None of that is
checked for biological truth here. What this module computes is only what follows from what
was written:

* **goal trace** — every objective, followed through sub-questions and hypotheses to the
  experiments that test them, so a design that quietly narrowed the goal shows the objective
  it dropped;
* **evidence by study** — how many independent studies stand behind each claim, so three
  spans read from one paper are not counted as three findings; the host's reading of each
  span travels with it, labelled as the host's;
* **mechanism links** — which case-local links carry no evidence, only ungrounded evidence, or
  no conditions, and whether the knowledge graph holds a path between the two ends. The graph
  is read, never written;
* **discrimination** — for each experiment, which hypothesis pairs its predicted values tell
  apart, which it cannot, and where two hypotheses that can both hold would blur a readout;
  across experiments, which pairs no candidate separates, and which experiment's separated
  pairs contain another's.

Two things this deliberately does not do. It never compares wording: two predictions differ
only if their predicted values differ. And it never produces a score, probability or ranking:
an invented number would be a confidence nobody measured. Which experiment to run first stays
the host's argument and the researcher's decision.
"""

from __future__ import annotations

from itertools import combinations
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.research.contracts import (
    GROUNDED_KINDS,
    DecisionBranch,
    EvidenceItem,
    EvidenceKind,
    EvidenceRole,
    Expectation,
    MechanismLink,
    Prediction,
    PredictionBasis,
    ResearchReport,
    expectation_kind,
)

#: How far the graph is walked from one end of a link looking for the other.
_GRAPH_HOPS = 3


class PlanFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    where: str
    detail: str


class Conditions(BaseModel):
    """Who fixed what. The researcher's decisions and the host's assumptions never merge."""

    model_config = ConfigDict(frozen=True)

    confirmed: list[str] = Field(default_factory=list)
    open: list[str] = Field(default_factory=list)
    host_assumptions: list[str] = Field(default_factory=list)


class ObjectiveTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    objective_id: str
    statement: str
    stated_by: str
    sub_question_ids: list[str] = Field(default_factory=list)
    hypothesis_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)


class EvidenceRow(BaseModel):
    """What stands behind one claim in one role, counted by study."""

    model_config = ConfigDict(frozen=True)

    target_id: str
    role: str
    evidence_ids: list[str] = Field(default_factory=list)
    span_count: int = 0
    independent_studies: int = Field(
        default=0,
        description=(
            "Distinct source articles among the read spans. Spans from one paper count once."
        ),
    )
    user_observation_ids: list[str] = Field(default_factory=list)
    ungrounded_ids: list[str] = Field(
        default_factory=list,
        description="Model priors, predictions and inferences. Not observations and not reads.",
    )
    host_readings: list[str] = Field(default_factory=list)
    interpretation_by: Literal["host"] = "host"


class SameStudySpans(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_id: str
    role: str
    study: str
    evidence_ids: list[str]


class GraphCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["path_found", "no_path_within_hops", "endpoint_not_in_graph", "not_checked"]
    source_entity: str | None = None
    target_entity: str | None = None
    path: list[str] = Field(default_factory=list)
    tier: str | None = None
    independent_paths: int | None = None
    provenance: list[str] = Field(default_factory=list)
    how_matched: str = (
        "Each end is matched to a graph entity only by its exact name or alias. A partial or "
        "word-level match is not treated as the same entity."
    )


class MechanismReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    source: str
    relation: str
    target: str
    conditions: list[str] = Field(default_factory=list)
    hypothesis_ids: list[str] = Field(default_factory=list)
    grounded_evidence_ids: list[str] = Field(default_factory=list)
    ungrounded_evidence_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(
        default_factory=list,
        description=(
            "no_evidence | only_ungrounded_evidence | no_conditions | no_hypothesis | "
            "not_in_graph | graph_path_without_case_conditions"
        ),
    )
    graph: GraphCheck
    status: Literal["case_candidate"] = "case_candidate"


class ReadoutDifference(BaseModel):
    model_config = ConfigDict(frozen=True)

    readout: str
    expected: dict[str, str]


class SeparatedPair(BaseModel):
    model_config = ConfigDict(frozen=True)

    pair: list[str]
    readouts: list[ReadoutDifference]
    coexistence_notes: list[str] = Field(default_factory=list)


class UnseparatedPair(BaseModel):
    model_config = ConfigDict(frozen=True)

    pair: list[str]
    reason: Literal[
        "same_prediction_on_every_shared_readout",
        "no_shared_predicted_readout",
        "not_comparable_on_shared_readouts",
    ]


class ReadoutExclusion(BaseModel):
    """A shared readout on which two predictions were not compared, and why."""

    model_config = ConfigDict(frozen=True)

    pair: list[str]
    readout: str
    reason: Literal["different_prediction_kinds", "different_reference"]
    detail: str


class OutcomeRow(BaseModel):
    """For one readout: which hypotheses predict each value."""

    model_config = ConfigDict(frozen=True)

    readout: str
    by_expected: dict[str, list[str]]


class ExperimentDiscrimination(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str
    hypotheses_with_predictions: list[str] = Field(default_factory=list)
    separated_pairs: list[SeparatedPair] = Field(default_factory=list)
    unseparated_pairs: list[UnseparatedPair] = Field(default_factory=list)
    outcome_table: list[OutcomeRow] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    readout_exclusions: list[ReadoutExclusion] = Field(default_factory=list)
    next_decisions: list[DecisionBranch] = Field(default_factory=list)
    next_decisions_by: Literal["host"] = "host"


class Coverage(BaseModel):
    """A set relation between two experiments' separated pairs. Not a preference."""

    model_config = ConfigDict(frozen=True)

    experiment_id: str
    covers_experiment_id: str
    relation: Literal["same_pairs", "strict_superset"]


class PairSelection(BaseModel):
    """Whether two hypotheses were treated as alternatives, and on what grounds."""

    model_config = ConfigDict(frozen=True)

    pair: list[str]
    compared: bool
    reason: Literal[
        "shared_sub_question",
        "declared_alternative",
        "no_sub_question_links",
        "no_shared_sub_question_and_not_declared_alternatives",
    ]


class ObjectiveLevel(BaseModel):
    """How directly each objective is tested. The levels are the declarer's judgement."""

    model_config = ConfigDict(frozen=True)

    objective_id: str
    direct: list[str] = Field(default_factory=list)
    proxy: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    reached_without_stated_level: list[str] = Field(
        default_factory=list,
        description="Experiments linked to the objective through hypotheses, with no level stated.",
    )
    directly_measured: bool = False
    judged_by: list[str] = Field(default_factory=list)


class NonDiscriminating(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str
    purposes: list[str] = Field(default_factory=list)
    note: str = (
        "Separates no hypothesis pair as written. That is not a defect: an experiment can be "
        "needed as a method check, a function check or a baseline."
    )


class MissingReadoutSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str
    readout: str
    missing: list[str]


class MechanismRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    gaps: list[str] = Field(default_factory=list)


class PredictionTrace(BaseModel):
    """From evidence and mechanism, through the expected biology, to the reading and decision."""

    model_config = ConfigDict(frozen=True)

    experiment_id: str
    hypothesis_id: str
    readout: str
    expected: str
    kind: str | None = Field(default=None, description="state, change, or null (not predicted)")
    versus: str | None = None
    condition: str | None = None
    biological_expectation: str | None = None
    basis: str
    basis_stated_by: Literal["host"] = "host"
    direct_evidence_ids: list[str] = Field(default_factory=list)
    mechanism_evidence_ids: list[str] = Field(default_factory=list)
    grounded_evidence_ids: list[str] = Field(default_factory=list)
    ungrounded_evidence_ids: list[str] = Field(default_factory=list)
    independent_studies: int = 0
    mechanism_links: list[MechanismRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unresolved: str | None = None
    checked_by: list[str] = Field(
        default_factory=list,
        description="Assumption checks (experiment:readout) testing this prediction's assumptions.",
    )
    separates: list[list[str]] = Field(
        default_factory=list,
        description="Pairs whose predicted values differ on this readout in this experiment.",
    )
    decisions: list[DecisionBranch] = Field(default_factory=list)
    gaps: list[str] = Field(
        default_factory=list,
        description=(
            "basis_unstated | evidence_observed_without_evidence | "
            "mechanism_derived_without_links | assumption_without_stated_assumptions | "
            "change_without_reference | readout_not_specified | unknown_mechanism_link"
        ),
    )


class WhatIf(BaseModel):
    """A question about dependency: which predictions rest on this evidence or condition?"""

    model_config = ConfigDict(extra="forbid")

    remove_evidence_ids: list[str] = Field(default_factory=list)
    changed_conditions: list[str] = Field(
        default_factory=list,
        description="Condition text, matched exactly (case and spacing ignored).",
    )


class AffectedPrediction(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str
    hypothesis_id: str
    readout: str
    via: list[str]


class Impact(BaseModel):
    model_config = ConfigDict(frozen=True)

    removed_evidence_ids: list[str] = Field(default_factory=list)
    changed_conditions: list[str] = Field(default_factory=list)
    affected_predictions: list[AffectedPrediction] = Field(default_factory=list)
    affected_mechanism_links: list[str] = Field(default_factory=list)
    affected_hypotheses: list[str] = Field(default_factory=list)
    affected_experiments: list[str] = Field(default_factory=list)
    note: str = (
        "These rest on what was withdrawn or changed and need re-examining. No predicted value "
        "is changed or reversed here, and nothing is propagated from one assay to another."
    )


class PlanAnalysis(BaseModel):
    """What code computed from the plan. The plan itself, and its meaning, are the host's."""

    model_config = ConfigDict(frozen=True)

    limits: list[str] = Field(default_factory=list)
    conditions: Conditions = Field(default_factory=Conditions)
    goal_trace: list[ObjectiveTrace] = Field(default_factory=list)
    unreached_objectives: list[str] = Field(default_factory=list)
    unanswered_sub_questions: list[str] = Field(default_factory=list)
    untested_hypotheses: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRow] = Field(default_factory=list)
    same_study_spans: list[SameStudySpans] = Field(default_factory=list)
    mechanism_links: list[MechanismReport] = Field(default_factory=list)
    experiments: list[ExperimentDiscrimination] = Field(default_factory=list)
    pairs_never_separated: list[list[str]] = Field(default_factory=list)
    experiments_without_predictions: list[str] = Field(
        default_factory=list,
        description="Experiments with no predictions; what they separate cannot be computed.",
    )
    coverage: list[Coverage] = Field(default_factory=list)
    pair_selection: list[PairSelection] = Field(default_factory=list)
    objective_levels: list[ObjectiveLevel] = Field(default_factory=list)
    non_discriminating_experiments: list[NonDiscriminating] = Field(default_factory=list)
    prediction_traces: list[PredictionTrace] = Field(default_factory=list)
    readout_specs_missing: list[MissingReadoutSpec] = Field(default_factory=list)
    impact: Impact | None = None
    findings: list[PlanFinding] = Field(default_factory=list)
    wrote_to_knowledge_graph: bool = False


LIMITS: tuple[str, ...] = (
    "Everything here follows from what the host wrote. Discrimination is computed from the "
    "predicted values given, so a wrong prediction produces a wrong separation.",
    "Two predictions differ only when their values differ. Wording is never compared, and two "
    "readouts named differently are treated as different readouts.",
    "Evidence roles and readings are the host's interpretation. Counting studies says how many "
    "papers were cited, not that any of them supports the claim.",
    "Mechanism links are case candidates. A graph path means the curated graph holds a route "
    "between two exactly-matched entities; it says nothing about this case's conditions.",
    "Nothing here ranks experiments. Which to run first is the host's argument and the "
    "researcher's decision.",
    "Two hypotheses predicting different values on a readout is not a measure of how well the "
    "experiment would discriminate them, and says nothing about separating causes acting "
    "together: effect size, noise and interference are not modelled.",
    "A state (present/absent) and a change (increase/decrease/no_change) are different claims "
    "and are never compared; neither are two changes stated against different references.",
    "Prediction traces follow the references the host gave. A connected path is not a verified "
    "causal chain.",
)


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def analyze_plan(
    report: ResearchReport,
    evidence: list[EvidenceItem],
    *,
    store: KnowledgeStore | None = None,
    what_if: WhatIf | None = None,
) -> PlanAnalysis:
    findings: list[PlanFinding] = []
    by_id = {item.id: item for item in evidence}
    hypothesis_ids = [h.id for h in report.hypotheses]
    link_ids = [m.id for m in report.mechanism_links]

    conditions = _conditions(report, findings)
    trace, unreached, unanswered, untested = _goal_trace(report, findings)
    rows, same_study = _evidence(report, by_id, set(hypothesis_ids) | set(link_ids), findings)
    mechanisms = [
        _mechanism(link, by_id, set(hypothesis_ids), store, findings)
        for link in report.mechanism_links
    ]
    experiments = [_discriminate(exp, report, findings) for exp in report.experiments]

    traces = _traces(report, by_id, mechanisms, experiments, findings)
    findings.extend(assumption_check_findings(report))
    return PlanAnalysis(
        pair_selection=_pair_selection(report),
        objective_levels=_objective_levels(report, trace, findings),
        non_discriminating_experiments=[
            NonDiscriminating(
                experiment_id=e.experiment_id,
                purposes=[pp.value for pp in _experiment(report, e.experiment_id).purposes],
            )
            for e in experiments
            if not e.separated_pairs
        ],
        prediction_traces=traces,
        readout_specs_missing=_missing_specs(report),
        impact=_impact(report, what_if) if what_if is not None else None,
        limits=list(LIMITS),
        conditions=conditions,
        goal_trace=trace,
        unreached_objectives=unreached,
        unanswered_sub_questions=unanswered,
        untested_hypotheses=untested,
        evidence=rows,
        same_study_spans=same_study,
        mechanism_links=mechanisms,
        experiments=experiments,
        pairs_never_separated=_never_separated(hypothesis_ids, report, experiments),
        experiments_without_predictions=[e.id for e in report.experiments if not e.predictions],
        coverage=_coverage(experiments),
        findings=findings,
    )


# --- A1 ------------------------------------------------------------------------------------ #


def _conditions(report: ResearchReport, findings: list[PlanFinding]) -> Conditions:
    confirmed = {_norm(c): c for c in report.confirmed_conditions}
    for item in report.open_conditions:
        if _norm(item) in confirmed:
            findings.append(
                PlanFinding(
                    code="condition_both_confirmed_and_open",
                    where="conditions",
                    detail=f"{item!r} is listed as both confirmed and still open.",
                )
            )
    return Conditions(
        confirmed=list(report.confirmed_conditions),
        open=list(report.open_conditions),
        host_assumptions=list(report.assumptions),
    )


def _tested_by(report: ResearchReport) -> dict[str, list[str]]:
    """Hypothesis id -> experiments that name it or predict something for it."""
    tested: dict[str, list[str]] = {h.id: [] for h in report.hypotheses}
    for exp in report.experiments:
        named = set(exp.discriminates) | {p.hypothesis_id for p in exp.predictions}
        for hid in named:
            if hid in tested and exp.id not in tested[hid]:
                tested[hid].append(exp.id)
    return tested


def _goal_trace(report: ResearchReport, findings: list[PlanFinding]):
    objective_ids = {o.id for o in report.objectives}
    sub_ids = {q.id for q in report.sub_questions}
    tested = _tested_by(report)

    for q in report.sub_questions:
        for oid in q.objective_ids:
            if oid not in objective_ids:
                findings.append(
                    PlanFinding(
                        code="unknown_objective_id",
                        where=f"sub_question:{q.id}",
                        detail=f"serves {oid!r}, which is not an objective here.",
                    )
                )
    for h in report.hypotheses:
        for qid in h.sub_question_ids:
            if qid not in sub_ids:
                findings.append(
                    PlanFinding(
                        code="unknown_sub_question_id",
                        where=f"hypothesis:{h.id}",
                        detail=f"answers {qid!r}, which is not a sub-question here.",
                    )
                )

    trace: list[ObjectiveTrace] = []
    for o in report.objectives:
        subs = [q.id for q in report.sub_questions if o.id in q.objective_ids]
        hyps = [h.id for h in report.hypotheses if set(h.sub_question_ids) & set(subs)]
        exps: list[str] = []
        for hid in hyps:
            exps.extend(e for e in tested.get(hid, []) if e not in exps)
        trace.append(
            ObjectiveTrace(
                objective_id=o.id,
                statement=o.statement,
                stated_by=o.stated_by,
                sub_question_ids=subs,
                hypothesis_ids=hyps,
                experiment_ids=exps,
            )
        )
    unreached = [t.objective_id for t in trace if not t.experiment_ids]
    unanswered = [
        q.id
        for q in report.sub_questions
        if not any(q.id in h.sub_question_ids for h in report.hypotheses)
    ]
    untested = [hid for hid, exps in tested.items() if not exps]
    return trace, unreached, unanswered, untested


# --- A2 ------------------------------------------------------------------------------------ #


def _study_key(item: EvidenceItem) -> str | None:
    if item.kind is EvidenceKind.RETRIEVED_SOURCE and item.locator is not None:
        return item.locator.article.stable_key()
    return None


def _evidence(report, by_id, targets, findings):
    # (target, role) -> [(evidence id, reading)]
    claims: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for h in report.hypotheses:
        for eid in h.supporting_evidence_ids:
            claims.setdefault((h.id, EvidenceRole.SUPPORTS.value), []).append((eid, ""))
        for eid in h.contradicting_evidence_ids:
            claims.setdefault((h.id, EvidenceRole.CONTRADICTS.value), []).append((eid, ""))
    for link in report.evidence_links:
        if link.target_id not in targets:
            findings.append(
                PlanFinding(
                    code="unknown_link_target",
                    where=f"evidence_link:{link.evidence_id}",
                    detail=(
                        f"points at {link.target_id!r}, which is no hypothesis or mechanism link."
                    ),
                )
            )
            continue
        claims.setdefault((link.target_id, link.role.value), []).append(
            (link.evidence_id, link.reading)
        )

    rows: list[EvidenceRow] = []
    same_study: list[SameStudySpans] = []
    for (target, role), cited in claims.items():
        ids: list[str] = []
        readings: list[str] = []
        studies: dict[str, list[str]] = {}
        observations: list[str] = []
        ungrounded: list[str] = []
        for eid, reading in cited:
            if eid in ids:
                continue
            ids.append(eid)
            if reading.strip():
                readings.append(reading)
            item = by_id.get(eid)
            if item is None:
                findings.append(
                    PlanFinding(
                        code="unknown_evidence_id",
                        where=f"{target}:{role}",
                        detail=f"cites {eid!r}, which was not supplied as evidence.",
                    )
                )
                continue
            key = _study_key(item)
            if key is not None:
                studies.setdefault(key, []).append(eid)
            elif item.kind is EvidenceKind.USER_OBSERVATION:
                observations.append(eid)
            elif item.kind not in GROUNDED_KINDS:
                ungrounded.append(eid)
        for key, eids in studies.items():
            if len(eids) > 1:
                same_study.append(
                    SameStudySpans(target_id=target, role=role, study=key, evidence_ids=eids)
                )
        rows.append(
            EvidenceRow(
                target_id=target,
                role=role,
                evidence_ids=ids,
                span_count=sum(len(v) for v in studies.values()),
                independent_studies=len(studies),
                user_observation_ids=observations,
                ungrounded_ids=ungrounded,
                host_readings=readings,
            )
        )
    return rows, same_study


# --- A3 ------------------------------------------------------------------------------------ #


def _exact_entity(store: KnowledgeStore, phrase: str):
    wanted = _norm(phrase)
    for entity in store.search(phrase, k=25):
        if _norm(entity.name) == wanted or any(_norm(a) == wanted for a in entity.aliases):
            return entity
    return None


def _graph(link: MechanismLink, store: KnowledgeStore | None) -> GraphCheck:
    if store is None:
        return GraphCheck(status="not_checked")
    source = _exact_entity(store, link.source)
    target = _exact_entity(store, link.target)
    if source is None or target is None:
        return GraphCheck(
            status="endpoint_not_in_graph",
            source_entity=source.id if source else None,
            target_entity=target.id if target else None,
        )
    from virtualcell.reasoning.explain import explain

    for direction in ("forward", "any"):
        for reached in explain(store, source.id, max_hops=_GRAPH_HOPS, direction=direction).links:
            if reached.target_id == target.id:
                return GraphCheck(
                    status="path_found",
                    source_entity=source.id,
                    target_entity=target.id,
                    path=list(reached.path),
                    tier=reached.tier.value,
                    independent_paths=reached.independent_paths,
                    provenance=list(reached.provenance),
                )
    return GraphCheck(
        status="no_path_within_hops", source_entity=source.id, target_entity=target.id
    )


def _mechanism(link, by_id, hypothesis_ids, store, findings) -> MechanismReport:
    grounded: list[str] = []
    ungrounded: list[str] = []
    for eid in link.evidence_ids:
        item = by_id.get(eid)
        if item is None:
            findings.append(
                PlanFinding(
                    code="unknown_evidence_id",
                    where=f"mechanism_link:{link.id}",
                    detail=f"cites {eid!r}, which was not supplied as evidence.",
                )
            )
        elif item.kind in GROUNDED_KINDS:
            grounded.append(eid)
        else:
            ungrounded.append(eid)
    for hid in link.hypothesis_ids:
        if hid not in hypothesis_ids:
            findings.append(
                PlanFinding(
                    code="unknown_hypothesis_id",
                    where=f"mechanism_link:{link.id}",
                    detail=f"serves {hid!r}, which is not a hypothesis here.",
                )
            )

    graph = _graph(link, store)
    gaps: list[str] = []
    if not link.evidence_ids:
        gaps.append("no_evidence")
    elif not grounded:
        gaps.append("only_ungrounded_evidence")
    if not link.conditions:
        gaps.append("no_conditions")
    if not link.hypothesis_ids:
        gaps.append("no_hypothesis")
    if graph.status in ("endpoint_not_in_graph", "no_path_within_hops"):
        gaps.append("not_in_graph")
    if graph.status == "path_found" and link.conditions:
        # Curated edges carry provenance, not the conditions this case states; the path
        # therefore cannot vouch for the relation under those conditions.
        gaps.append("graph_path_without_case_conditions")
    return MechanismReport(
        id=link.id,
        source=link.source,
        relation=link.relation,
        target=link.target,
        conditions=list(link.conditions),
        hypothesis_ids=list(link.hypothesis_ids),
        grounded_evidence_ids=grounded,
        ungrounded_evidence_ids=ungrounded,
        gaps=gaps,
        graph=graph,
    )


# --- A4 ------------------------------------------------------------------------------------ #

#: Only a rise against a fall can offset. `absent` is a null like `no_change`, not an opposite
#: effect: treating present/absent as opposed reported a cell-free interference control as two
#: effects that "may offset" (found on development case 2).
_OPPOSED = {frozenset({Expectation.INCREASE, Expectation.DECREASE})}
_NULL = {Expectation.NO_CHANGE, Expectation.ABSENT}


def _selection_reason(report: ResearchReport, a: str, b: str) -> str:
    """Why two hypotheses are, or are not, treated as alternatives.

    Comparing across sub-questions listed a degradation-route hypothesis and a handover
    hypothesis as "never separated" (found on development case 1): they are not competing
    explanations of one thing. But the host can say two hypotheses explain the same observation
    whatever questions they sit under (`alternative_to`), and a hypothesis with no sub-question
    links is compared with every other, so a draft that does not use them keeps the earlier
    behaviour. Every excluded pair is reported with this reason, never silently dropped.
    """
    by_id = {h.id: h for h in report.hypotheses}
    ha, hb = by_id.get(a), by_id.get(b)
    first = set(ha.sub_question_ids) if ha else set()
    second = set(hb.sub_question_ids) if hb else set()
    if first & second:
        return "shared_sub_question"
    if (ha and b in ha.alternative_to) or (hb and a in hb.alternative_to):
        return "declared_alternative"
    if not first or not second:
        return "no_sub_question_links"
    return "no_shared_sub_question_and_not_declared_alternatives"


def _comparable(report: ResearchReport, a: str, b: str) -> bool:
    return _selection_reason(report, a, b) != "no_shared_sub_question_and_not_declared_alternatives"


def _pair_selection(report: ResearchReport) -> list[PairSelection]:
    ids = [h.id for h in report.hypotheses]
    out = []
    for a, b in combinations(ids, 2):
        reason = _selection_reason(report, a, b)
        out.append(
            PairSelection(
                pair=[a, b],
                compared=reason != "no_shared_sub_question_and_not_declared_alternatives",
                reason=reason,
            )
        )
    return out


def _exclusive(report: ResearchReport, a: str, b: str) -> bool:
    for h in report.hypotheses:
        if (h.id == a and b in h.mutually_exclusive_with) or (
            h.id == b and a in h.mutually_exclusive_with
        ):
            return True
    return False


def _coexistence(a: str, b: str, readout: str, ea: Expectation, eb: Expectation) -> list[str]:
    if frozenset({ea, eb}) in _OPPOSED:
        return [
            f"{a} and {b} can both hold and predict opposite values for {readout!r}: their "
            "effects may offset, so an intermediate or unchanged result could mean both, not "
            "neither."
        ]
    if eb in _NULL and ea not in _NULL:
        active, quiet = a, b
    elif ea in _NULL and eb not in _NULL:
        active, quiet = b, a
    else:
        return []
    return [
        f"On {readout!r}, a change tells that {active} holds; it cannot rule out {quiet}, "
        f"because {quiet} predicts no change there and both can be true."
    ]


def _discriminate(exp, report: ResearchReport, findings) -> ExperimentDiscrimination:
    known = {h.id for h in report.hypotheses}
    measured = {_norm(m) for m in exp.measurements}
    # hypothesis -> readout -> expected (and the prediction, for its kind and reference)
    table: dict[str, dict[str, Expectation]] = {}
    preds: dict[str, dict[str, Prediction]] = {}
    labels: dict[str, str] = {}
    for p in exp.predictions:
        if p.hypothesis_id not in known:
            findings.append(
                PlanFinding(
                    code="unknown_hypothesis_id",
                    where=f"experiment:{exp.id}",
                    detail=f"predicts for {p.hypothesis_id!r}, which is not a hypothesis here.",
                )
            )
            continue
        key = _norm(p.readout)
        labels.setdefault(key, p.readout)
        if key not in measured:
            findings.append(
                PlanFinding(
                    code="readout_not_measured",
                    where=f"experiment:{exp.id}",
                    detail=f"{p.readout!r} is predicted but is not among the measurements.",
                )
            )
        table.setdefault(p.hypothesis_id, {})[key] = p.expected
        preds.setdefault(p.hypothesis_id, {})[key] = p

    if exp.predictions and not exp.controls:
        findings.append(
            PlanFinding(
                code="predictions_without_controls",
                where=f"experiment:{exp.id}",
                detail="makes predictions but names no control to read them against.",
            )
        )
    for hid in exp.discriminates if exp.predictions else []:
        if hid not in table:
            findings.append(
                PlanFinding(
                    code="discrimination_claimed_without_predictions",
                    where=f"experiment:{exp.id}",
                    detail=(
                        f"says it tells {hid!r} apart but gives no prediction for it, so what "
                        "it separates cannot be computed."
                    ),
                )
            )

    order = [h.id for h in report.hypotheses if h.id in table]
    separated: list[SeparatedPair] = []
    unseparated: list[UnseparatedPair] = []
    exclusions: list[ReadoutExclusion] = []
    for a, b in combinations(order, 2):
        if not _comparable(report, a, b):
            continue
        predicted = [
            r
            for r in table[a]
            if r in table[b] and Expectation.NOT_PREDICTED not in (table[a][r], table[b][r])
        ]
        if not predicted:
            unseparated.append(UnseparatedPair(pair=[a, b], reason="no_shared_predicted_readout"))
            continue
        shared = []
        for r in predicted:
            pa, pb = preds[a][r], preds[b][r]
            kind_a, kind_b = (
                expectation_kind(pa.expected.value),
                expectation_kind(pb.expected.value),
            )
            if kind_a != kind_b:
                exclusions.append(
                    ReadoutExclusion(
                        pair=[a, b],
                        readout=labels[r],
                        reason="different_prediction_kinds",
                        detail=(
                            f"{a} predicts a {kind_a} ({pa.expected.value}) and {b} a {kind_b} "
                            f"({pb.expected.value}); a state and a change are different claims."
                        ),
                    )
                )
                continue
            if (
                kind_a == "change"
                and pa.versus
                and pb.versus
                and _norm(pa.versus) != _norm(pb.versus)
            ):
                exclusions.append(
                    ReadoutExclusion(
                        pair=[a, b],
                        readout=labels[r],
                        reason="different_reference",
                        detail=f"changes against {pa.versus!r} and {pb.versus!r}.",
                    )
                )
                continue
            shared.append(r)
        if not shared:
            unseparated.append(
                UnseparatedPair(pair=[a, b], reason="not_comparable_on_shared_readouts")
            )
            continue
        differing = [r for r in shared if table[a][r] != table[b][r]]
        if not differing:
            unseparated.append(
                UnseparatedPair(pair=[a, b], reason="same_prediction_on_every_shared_readout")
            )
            continue
        notes: list[str] = []
        if not _exclusive(report, a, b):
            for r in differing:
                notes.extend(_coexistence(a, b, labels[r], table[a][r], table[b][r]))
        separated.append(
            SeparatedPair(
                pair=[a, b],
                readouts=[
                    ReadoutDifference(
                        readout=labels[r], expected={a: table[a][r].value, b: table[b][r].value}
                    )
                    for r in differing
                ],
                coexistence_notes=notes,
            )
        )

    outcome: list[OutcomeRow] = []
    for key, label in labels.items():
        by_expected: dict[str, list[str]] = {}
        for hid in order:
            value = table[hid].get(key)
            if value is not None and value is not Expectation.NOT_PREDICTED:
                by_expected.setdefault(value.value, []).append(hid)
        outcome.append(OutcomeRow(readout=label, by_expected=by_expected))

    return ExperimentDiscrimination(
        experiment_id=exp.id,
        hypotheses_with_predictions=order,
        separated_pairs=separated,
        unseparated_pairs=unseparated,
        outcome_table=outcome,
        controls=list(exp.controls),
        readout_exclusions=exclusions,
        next_decisions=list(exp.branches),
    )


def _pairs(experiment: ExperimentDiscrimination) -> set[tuple[str, str]]:
    return {(p.pair[0], p.pair[1]) for p in experiment.separated_pairs}


def _never_separated(
    hypothesis_ids: list[str], report: ResearchReport, experiments: list[ExperimentDiscrimination]
) -> list[list[str]]:
    predicted = {h for e in experiments for h in e.hypotheses_with_predictions}
    ordered = [h for h in hypothesis_ids if h in predicted]
    covered: set[tuple[str, str]] = set()
    for e in experiments:
        covered |= _pairs(e)
    return [
        [a, b]
        for a, b in combinations(ordered, 2)
        if (a, b) not in covered and _comparable(report, a, b)
    ]


def _coverage(experiments: list[ExperimentDiscrimination]) -> list[Coverage]:
    out: list[Coverage] = []
    for first in experiments:
        mine = _pairs(first)
        for second in experiments:
            if first.experiment_id == second.experiment_id:
                continue
            theirs = _pairs(second)
            if not theirs or not theirs <= mine:
                continue
            if mine == theirs:
                if first.experiment_id < second.experiment_id:
                    out.append(
                        Coverage(
                            experiment_id=first.experiment_id,
                            covers_experiment_id=second.experiment_id,
                            relation="same_pairs",
                        )
                    )
            else:
                out.append(
                    Coverage(
                        experiment_id=first.experiment_id,
                        covers_experiment_id=second.experiment_id,
                        relation="strict_superset",
                    )
                )
    return out


# --- how directly objectives are tested, and readouts' specifications ----------------------- #


def _experiment(report: ResearchReport, experiment_id: str):
    return next(e for e in report.experiments if e.id == experiment_id)


def _objective_levels(report, trace, findings) -> list[ObjectiveLevel]:
    objective_ids = {o.id for o in report.objectives}
    declared: dict[str, dict[str, list[str]]] = {}
    judges: dict[str, list[str]] = {}
    for exp in report.experiments:
        for cov in exp.objective_coverage:
            if cov.objective_id not in objective_ids:
                findings.append(
                    PlanFinding(
                        code="unknown_objective_id",
                        where=f"experiment:{exp.id}",
                        detail=f"covers {cov.objective_id!r}, which is not an objective here.",
                    )
                )
                continue
            declared.setdefault(cov.objective_id, {}).setdefault(cov.level, []).append(exp.id)
            if cov.judged_by not in judges.setdefault(cov.objective_id, []):
                judges[cov.objective_id].append(cov.judged_by)
    reached = {t.objective_id: t.experiment_ids for t in trace}
    out = []
    for o in report.objectives:
        levels = declared.get(o.id, {})
        stated = {e for exps in levels.values() for e in exps}
        out.append(
            ObjectiveLevel(
                objective_id=o.id,
                direct=levels.get("direct", []),
                proxy=levels.get("proxy", []),
                out_of_scope=levels.get("out_of_scope", []),
                reached_without_stated_level=[e for e in reached.get(o.id, []) if e not in stated],
                directly_measured=bool(levels.get("direct")),
                judged_by=judges.get(o.id, []),
            )
        )
    return out


_SPEC_FIELDS = ("target", "assay", "compartment", "timepoint", "reference", "normalization", "unit")


def _missing_specs(report: ResearchReport) -> list[MissingReadoutSpec]:
    out = []
    for exp in report.experiments:
        for spec in exp.readouts:
            missing = [f for f in _SPEC_FIELDS if not getattr(spec, f)]
            if missing:
                out.append(
                    MissingReadoutSpec(experiment_id=exp.id, readout=spec.name, missing=missing)
                )
    return out


# --- from evidence to prediction, and what depends on what ---------------------------------- #


def _traces(report, by_id, mechanisms, experiments, findings) -> list[PredictionTrace]:
    known = {h.id for h in report.hypotheses}
    links = {m.id: m for m in report.mechanism_links}
    link_reports = {m.id: m for m in mechanisms}
    discrimination = {e.experiment_id: e for e in experiments}
    out: list[PredictionTrace] = []
    for exp in report.experiments:
        spec_names = {_norm(s.name) for s in exp.readouts}
        for p in exp.predictions:
            if p.hypothesis_id not in known:
                continue
            kind = expectation_kind(p.expected.value)
            gaps: list[str] = []
            mechanism_evidence: list[str] = []
            refs: list[MechanismRef] = []
            for lid in p.mechanism_link_ids:
                link = links.get(lid)
                if link is None:
                    gaps.append("unknown_mechanism_link")
                    findings.append(
                        PlanFinding(
                            code="unknown_mechanism_link",
                            where=f"experiment:{exp.id}:{p.hypothesis_id}:{p.readout}",
                            detail=f"depends on {lid!r}, which is not a mechanism link here.",
                        )
                    )
                    continue
                refs.append(MechanismRef(id=lid, gaps=list(link_reports[lid].gaps)))
                mechanism_evidence.extend(
                    e for e in link.evidence_ids if e not in mechanism_evidence
                )
            for eid in p.evidence_ids:
                if eid not in by_id:
                    findings.append(
                        PlanFinding(
                            code="unknown_evidence_id",
                            where=f"experiment:{exp.id}:{p.hypothesis_id}:{p.readout}",
                            detail=f"cites {eid!r}, which was not supplied as evidence.",
                        )
                    )
            cited = list(dict.fromkeys([*p.evidence_ids, *mechanism_evidence]))
            grounded = [e for e in cited if e in by_id and by_id[e].kind in GROUNDED_KINDS]
            ungrounded = [e for e in cited if e in by_id and by_id[e].kind not in GROUNDED_KINDS]
            studies = {_study_key(by_id[e]) for e in grounded} - {None}
            observations = [e for e in grounded if _study_key(by_id[e]) is None]

            if kind is not None:
                if p.basis is PredictionBasis.UNSTATED:
                    gaps.append("basis_unstated")
                elif p.basis is PredictionBasis.EVIDENCE_OBSERVED and not p.evidence_ids:
                    gaps.append("evidence_observed_without_evidence")
                elif p.basis is PredictionBasis.MECHANISM_DERIVED and not p.mechanism_link_ids:
                    gaps.append("mechanism_derived_without_links")
                elif p.basis is PredictionBasis.ASSUMPTION and not p.assumptions:
                    gaps.append("assumption_without_stated_assumptions")
                if kind == "change" and not p.versus:
                    gaps.append("change_without_reference")
                if spec_names and _norm(p.readout) not in spec_names:
                    gaps.append("readout_not_specified")

            separates = [
                pair.pair
                for pair in discrimination[exp.id].separated_pairs
                if p.hypothesis_id in pair.pair
                and any(_norm(d.readout) == _norm(p.readout) for d in pair.readouts)
            ]
            out.append(
                PredictionTrace(
                    experiment_id=exp.id,
                    hypothesis_id=p.hypothesis_id,
                    readout=p.readout,
                    expected=p.expected.value,
                    kind=kind,
                    versus=p.versus,
                    condition=p.condition,
                    biological_expectation=p.biological_expectation,
                    basis=p.basis.value,
                    direct_evidence_ids=list(p.evidence_ids),
                    mechanism_evidence_ids=mechanism_evidence,
                    grounded_evidence_ids=grounded,
                    ungrounded_evidence_ids=ungrounded,
                    independent_studies=len(studies) + len(observations),
                    mechanism_links=refs,
                    assumptions=list(p.assumptions),
                    unresolved=p.unresolved,
                    separates=separates,
                    decisions=list(exp.branches),
                    gaps=gaps,
                    checked_by=[
                        f"{e.id}:{c.readout}"
                        for e in report.experiments
                        for c in e.assumption_checks
                        if _norm(c.assumption) in {_norm(a) for a in p.assumptions}
                    ],
                )
            )
    return out


def _impact(report: ResearchReport, what_if: WhatIf) -> Impact:
    removed = set(what_if.remove_evidence_ids)
    changed = {_norm(c) for c in what_if.changed_conditions}
    affected_links = [
        m.id
        for m in report.mechanism_links
        if removed & set(m.evidence_ids) or changed & {_norm(c) for c in m.conditions}
    ]
    predictions: list[AffectedPrediction] = []
    for exp in report.experiments:
        for p in exp.predictions:
            via = [f"evidence:{e}" for e in p.evidence_ids if e in removed]
            via += [
                f"mechanism_link:{lid}" for lid in p.mechanism_link_ids if lid in affected_links
            ]
            if p.condition and _norm(p.condition) in changed:
                via.append("condition")
            if via:
                predictions.append(
                    AffectedPrediction(
                        experiment_id=exp.id,
                        hypothesis_id=p.hypothesis_id,
                        readout=p.readout,
                        via=via,
                    )
                )
    hypotheses = list(dict.fromkeys(a.hypothesis_id for a in predictions))
    for h in report.hypotheses:
        cites = set(h.supporting_evidence_ids) | set(h.contradicting_evidence_ids)
        cites |= {lk.evidence_id for lk in report.evidence_links if lk.target_id == h.id}
        if cites & removed and h.id not in hypotheses:
            hypotheses.append(h.id)
    return Impact(
        removed_evidence_ids=sorted(removed),
        changed_conditions=list(what_if.changed_conditions),
        affected_predictions=predictions,
        affected_mechanism_links=affected_links,
        affected_hypotheses=hypotheses,
        affected_experiments=list(dict.fromkeys(a.experiment_id for a in predictions)),
    )


def assumption_check_findings(report: ResearchReport) -> list[PlanFinding]:
    """An assumption check must name an assumption the plan states, written the same way.

    Matched as written (case and spacing aside), never by synonym: a check of an assumption no
    prediction names would mark nothing, silently.
    """
    stated = {_norm(a) for e in report.experiments for p in e.predictions for a in p.assumptions}
    stated |= {_norm(a) for a in report.assumptions}
    out: list[PlanFinding] = []
    for e in report.experiments:
        measured = {_norm(x) for x in e.measurements} | {_norm(r.name) for r in e.readouts}
        for c in e.assumption_checks:
            if _norm(c.assumption) not in stated:
                out.append(
                    PlanFinding(
                        code="assumption_check_names_no_assumption",
                        where=f"experiment:{e.id}:{c.readout}",
                        detail=(
                            f"checks {c.assumption!r}, which no prediction or plan assumption "
                            "states in these words; nothing would be marked by it."
                        ),
                    )
                )
            if measured and _norm(c.readout) not in measured:
                out.append(
                    PlanFinding(
                        code="assumption_check_readout_not_measured",
                        where=f"experiment:{e.id}:{c.readout}",
                        detail="names a readout that is not among the experiment's measurements.",
                    )
                )
    return out
