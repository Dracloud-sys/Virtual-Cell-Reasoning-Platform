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
    ResearchReport,
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
    reason: Literal["same_prediction_on_every_shared_readout", "no_shared_predicted_readout"]


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
    next_decisions: list[DecisionBranch] = Field(default_factory=list)
    next_decisions_by: Literal["host"] = "host"


class Coverage(BaseModel):
    """A set relation between two experiments' separated pairs. Not a preference."""

    model_config = ConfigDict(frozen=True)

    experiment_id: str
    covers_experiment_id: str
    relation: Literal["same_pairs", "strict_superset"]


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
)


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def analyze_plan(
    report: ResearchReport,
    evidence: list[EvidenceItem],
    *,
    store: KnowledgeStore | None = None,
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

    return PlanAnalysis(
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


def _comparable(report: ResearchReport, a: str, b: str) -> bool:
    """Two hypotheses are alternatives only if they answer a shared sub-question.

    Comparing across sub-questions listed a degradation-route hypothesis and a handover
    hypothesis as "never separated" (found on development case 1): they are not competing
    explanations of one thing. A hypothesis with no sub-question links is compared with every
    other, so a draft that does not use sub-questions keeps the earlier behaviour.
    """
    subs = {h.id: set(h.sub_question_ids) for h in report.hypotheses}
    first, second = subs.get(a, set()), subs.get(b, set())
    return not first or not second or bool(first & second)


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
    # hypothesis -> readout -> expected
    table: dict[str, dict[str, Expectation]] = {}
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
    for a, b in combinations(order, 2):
        if not _comparable(report, a, b):
            continue
        shared = [
            r
            for r in table[a]
            if r in table[b] and Expectation.NOT_PREDICTED not in (table[a][r], table[b][r])
        ]
        if not shared:
            unseparated.append(UnseparatedPair(pair=[a, b], reason="no_shared_predicted_readout"))
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
