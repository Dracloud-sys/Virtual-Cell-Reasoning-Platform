"""Benchmark-first re-evaluation of the 10 immortalization questions.

Runs each fixed question (``immortalization_v0.yaml``) through the *real* deterministic
``DecisionReport`` pipeline and scores the machine-checkable rubric axes, so the
benchmark can be re-run as an honest scorecard rather than only a pass/fail test. The
subjective rubric axes (prose quality, expert nuance) still need a human; this harness
scores only what is deterministically decidable and states its own limits.

**Product path.** All ten questions are evaluated through the *same public entry point
API and CLI callers use* — :meth:`ImmortalizationAssessmentAgent.assess` — over a store
built by the normal deterministic seed path. The benchmark never selects an internal
builder by intent; the agent is the sole dispatch authority, so a 10/10 score is
evidence about the shipped product rather than about a benchmark-only code path.
Intent only chooses which *rubric axes* apply (a mechanism question has no status to
score), never which implementation runs.

Run ``python -m tests.benchmarks.eval_immortalization_v0`` for the scorecard.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
from virtualcell.agents.immortalization.hypotheses import assertion_texts
from virtualcell.agents.immortalization.models import ASSESSMENT_INTENTS, AssessmentIntent
from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource

_SPEC_PATH = Path(__file__).parent / "immortalization_v0.yaml"

# Rubric axes this harness can decide deterministically (out of the 6-axis, 12-point
# rubric in immortalization_v0.md). The prose-nuance portions stay human-scored.
AXES = (
    "status_match",
    "multi_marker",
    "both_sides",
    "overinterpretation_controlled",
    "targeted_next_experiment",
    "evidence_tier_discipline",
)


# The benchmark rubric scores each axis 0/1/2 (max 12) and passes a question at >= 9,
# so a single soft axis (e.g. a generic rather than question-specific caveat) costs a
# point but does not fail the question. This harness mirrors that.
MAX_PER_AXIS = 2
MAX_TOTAL = MAX_PER_AXIS * len(AXES)
PASS_THRESHOLD = 9


class AxisScore(BaseModel):
    name: str
    score: int  # 0 / 1 / 2
    detail: str = ""


class QuestionEval(BaseModel):
    id: str
    intent: str
    handled: bool
    deferred_reason: str | None = None
    status: str | None = None
    expected_status: str | None = None
    flags: list[str] = []
    expected_flags: list[str] = []
    axes: list[AxisScore] = []
    # Axes that must not be zero for the question to pass (hard gates: a wrong status, an
    # over-call, or a forbidden phrasing fails the question regardless of total).
    critical: list[str] = []

    @property
    def total(self) -> int:
        return sum(a.score for a in self.axes)

    @property
    def passed(self) -> bool:
        if not self.handled or self.total < PASS_THRESHOLD:
            return False
        return all(a.score > 0 for a in self.axes if a.name in self.critical)


def load_spec() -> dict:
    return yaml.safe_load(_SPEC_PATH.read_text(encoding="utf-8"))


def _tier(claim) -> str | None:
    tier = getattr(claim, "tier", None)
    return tier.value if hasattr(tier, "value") else tier


def _axis_token(axis: str) -> str:
    return axis.lower().replace("-", "").replace("_", "").replace("b", "b")


def _seed_store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    source = ImmortalizationSeedSource()
    for entity in source.entities():
        store.upsert(entity)
    for interaction in source.interactions():
        store.add_interaction(interaction)
    return store


def _report_text(report) -> str:
    """Broad text used for *key-point coverage* only — never for forbidden-phrase
    checking, which must see assertion fields alone (see :func:`_score_hypothesis`)."""
    parts = [
        report.conclusion,
        *report.limitations,
        *report.overinterpretation_risk,
        *report.recommended_validation,
        *report.next_experiment,
        *(link.target_name for link in report.mechanistic_chain),
        *(c.statement for c in report.supporting_evidence),
    ]
    return " ".join(parts).lower()


def build_agent() -> ImmortalizationAssessmentAgent:
    """The product's assessment agent over a normally seeded store."""
    return ImmortalizationAssessmentAgent(store=_seed_store())


def _evaluate_question(question: dict, agent: ImmortalizationAssessmentAgent) -> QuestionEval:
    qid = question["id"]
    intent = AssessmentIntent(question["intent"])
    expected_status = question.get("expected_status")
    expected_flags = sorted(question.get("expected_flags", []) or [])

    # One public call for every question — the agent owns intent dispatch.
    data = input_from_scenario(intent, question["scenario"])
    report = agent.assess(data)

    status = report.candidate_status.value if report.candidate_status else None
    flags = sorted(f.value for f in report.flags)

    # Intent selects the applicable *rubric axes* (a mechanism question has no status
    # to score), not the implementation that produced the report.
    if intent in ASSESSMENT_INTENTS:
        acceptable = question.get("acceptable_status") or (
            [expected_status] if expected_status else []
        )
        axes = [
            _score_status(status, flags, acceptable, expected_flags),
            _score_multi_marker(report),
            _score_both_sides(report, question),
            _score_overinterpretation(report),
            _score_next_experiment(report),
            _score_tiers(report),
        ]
        critical = ["status_match"]
    elif intent is AssessmentIntent.HYPOTHESIS_HANDLING:
        axes = _score_hypothesis(report, question, expected_status)
        critical = ["status_match", "forbidden_absent"]
    else:
        axes = _score_mechanism(report, question)
        critical = ["no_overcall"]

    return QuestionEval(
        id=qid,
        intent=intent.value,
        handled=True,
        status=status,
        expected_status=expected_status,
        flags=flags,
        expected_flags=expected_flags,
        axes=axes,
        critical=critical,
    )


def _covers(text: str, key_point: str) -> bool:
    """Is a benchmark key point (``does_not_bypass_p16_RB``) represented in the text?"""
    stop = {"does", "not", "may", "the", "via", "and", "for", "be"}
    tokens = [t for t in key_point.lower().split("_") if len(t) >= 3 and t not in stop]
    if not tokens:
        return True
    return sum(1 for t in tokens if t in text) / len(tokens) >= 0.5


def _score_mechanism(report, question) -> list[AxisScore]:
    text = _report_text(report)
    key_points = question.get("key_points", [])
    covered = sum(1 for kp in key_points if _covers(text, kp))
    kp_score = 2 if covered == len(key_points) else (1 if covered else 0)
    tiers = {link.tier for link in report.mechanistic_chain}
    return [
        AxisScore(
            name="no_overcall",
            score=2 if report.candidate_status is None else 0,
            detail=f"status={report.candidate_status}",
        ),
        AxisScore(
            name="mechanistic_chain",
            score=2 if report.mechanistic_chain else 0,
            detail=f"{len(report.mechanistic_chain)} link(s)",
        ),
        AxisScore(name="key_points", score=kp_score, detail=f"{covered}/{len(key_points)}"),
        AxisScore(
            name="limitation_present",
            score=2 if report.limitations else 0,
            detail=f"{len(report.limitations)} limitation(s)",
        ),
        AxisScore(
            name="targeted_next_experiment",
            score=2 if report.next_experiment else 0,
            detail=f"{len(report.next_experiment)} step(s)",
        ),
        AxisScore(
            name="evidence_tier_discipline",
            score=2 if len(tiers) >= 2 else (1 if tiers else 0),
            detail=f"tiers={sorted(t.value for t in tiers)}",
        ),
    ]


def _claim_matched(report, required: dict) -> bool:
    want_tier = required["tier"]
    tokens = [t for t in re.findall(r"[a-z0-9]+", required["text"].lower()) if len(t) >= 4]
    for claim in report.supporting_evidence:
        if _tier(claim) != want_tier:
            continue
        statement = claim.statement.lower()
        if sum(1 for t in tokens if t in statement) >= 2:
            return True
    return False


def _score_hypothesis(report, question, expected_status) -> list[AxisScore]:
    text = _report_text(report)
    status = report.candidate_status.value if report.candidate_status else None
    # The benchmark owns its forbidden list, but scans it over the *production* notion
    # of an assertion field (conclusion + evidence claims). Scanning the whole report
    # would fail correct safety guidance that quotes a phrase in order to forbid it —
    # "P53-independent does not mean P53 loss" is required wording, not a violation.
    asserted = " ".join(assertion_texts(report)).lower()
    forbidden_hit = [
        phrase
        for phrase in (p.lower() for p in question.get("forbidden_phrasings", []))
        if phrase in asserted
    ]
    required = question.get("required_claims", [])
    matched = sum(1 for rc in required if _claim_matched(report, rc))
    rc_score = 2 if matched == len(required) else (1 if matched else 0)
    weak_ok = any(
        "spontaneous" in link.target_name.lower() and link.tier is not EvidenceTier.ESTABLISHED
        for link in report.mechanistic_chain
    )
    return [
        AxisScore(
            name="status_match",
            score=2 if status == expected_status else 0,
            detail=f"status={status} vs {expected_status}",
        ),
        AxisScore(name="required_claims", score=rc_score, detail=f"{matched}/{len(required)}"),
        AxisScore(
            name="forbidden_absent",
            score=0 if forbidden_hit else 2,
            detail=f"forbidden present: {forbidden_hit}",
        ),
        AxisScore(
            name="weak_relations",
            score=2 if weak_ok else 0,
            detail="spontaneous route reached only weakly",
        ),
        AxisScore(
            name="overinterpretation_controlled",
            score=2 if "p53-independent" in text else 0,
            detail="P53-independent framing stated",
        ),
        AxisScore(
            name="targeted_next_experiment",
            score=2 if report.next_experiment else 0,
            detail=f"{len(report.next_experiment)} step(s)",
        ),
    ]


def _score_status(status, flags, acceptable, expected_flags) -> AxisScore:
    # 2 = right status and flags; 1 = right status, wrong flags; 0 = wrong status.
    if status not in acceptable:
        score = 0
    elif flags == expected_flags:
        score = 2
    else:
        score = 1
    return AxisScore(
        name="status_match",
        score=score,
        detail=f"status={status} in {acceptable}; flags={flags} vs {expected_flags}",
    )


def _score_multi_marker(report) -> AxisScore:
    n = len(report.supporting_evidence) + len(report.contradicting_evidence)
    score = 2 if n >= 2 else (1 if n == 1 else 0)
    return AxisScore(name="multi_marker", score=score, detail=f"{n} evidence item(s)")


def _score_both_sides(report, question) -> AxisScore:
    has_support = bool(report.supporting_evidence)
    has_contra = bool(report.contradicting_evidence)
    if has_support and has_contra:
        score = 2
    elif question.get("must_report_both_sides"):
        score = 0  # the conflict question must show both sides explicitly
    elif (has_support or has_contra) and bool(report.missing_axes or report.uncertainty):
        # A clear one-directional case (e.g. senescence) legitimately has no
        # "supporting immortalization" side; the missing-axis caveat is the other side.
        score = 1
    else:
        score = 0
    detail = (
        f"support={len(report.supporting_evidence)} "
        f"contra={len(report.contradicting_evidence)} missing={len(report.missing_axes)}"
    )
    return AxisScore(name="both_sides", score=score, detail=detail)


def _score_overinterpretation(report) -> AxisScore:
    # 2 = a question-specific risk beyond the generic single-marker caveat; 1 = only the
    # generic caveat; 0 = no risk stated. Status is never an over-call by construction
    # (there is no 'immortalized' status), so over-calling cannot occur here.
    risks = report.overinterpretation_risk
    specific = [r for r in risks if "single-marker" not in r.lower()]
    score = 2 if specific else (1 if risks else 0)
    return AxisScore(
        name="overinterpretation_controlled",
        score=score,
        detail=f"{len(risks)} risk(s), {len(specific)} specific",
    )


def _score_next_experiment(report) -> AxisScore:
    text = " ".join(report.next_experiment).lower().replace("-", "").replace("_", "")
    if not report.next_experiment:
        return AxisScore(name="targeted_next_experiment", score=0, detail="none")
    if report.missing_axes:
        hit = any(_axis_token(axis) in text for axis in report.missing_axes)
        detail = f"missing {report.missing_axes} targeted={hit}"
    else:
        # No missing axis (e.g. the conflict case): a time-course re-measure is the
        # targeted follow-up.
        hit = any(k in text for k in ("recheck", "remeasure", "timecourse", "time course"))
        detail = f"no missing axis; re-measure suggested={hit}"
    return AxisScore(name="targeted_next_experiment", score=2 if hit else 1, detail=detail)


def _score_tiers(report) -> AxisScore:
    tiers = {_tier(c) for c in report.supporting_evidence + report.contradicting_evidence}
    tiers.discard(None)
    known = tiers.issubset({"established", "hypothesis", "reported", "inferred"})
    score = 2 if (known and tiers) else (1 if tiers else 0)
    return AxisScore(name="evidence_tier_discipline", score=score, detail=f"tiers={sorted(tiers)}")


def evaluate() -> list[QuestionEval]:
    """Score all ten questions through one product-path agent."""
    agent = build_agent()
    return [_evaluate_question(q, agent) for q in load_spec()["questions"]]


def scorecard(results: list[QuestionEval]) -> str:
    handled = [r for r in results if r.handled]
    deferred = [r for r in results if not r.handled]
    passed = [r for r in handled if r.passed]
    lines = [
        "Immortalization v0 -- DecisionReport re-evaluation",
        "=" * 68,
        f"handled {len(handled)}/10 | deferred {len(deferred)}/10 | "
        f"passed {len(passed)}/{len(handled)} of handled (threshold {PASS_THRESHOLD}/{MAX_TOTAL})",
        "-" * 68,
    ]
    for r in results:
        if not r.handled:
            lines.append(f"  {r.id:8} DEFERRED  {r.deferred_reason}")
            continue
        mark = "PASS" if r.passed else "FAIL"
        soft = [f"{a.name}={a.score}" for a in r.axes if a.score < MAX_PER_AXIS]
        suffix = f"  (soft: {', '.join(soft)})" if soft else ""
        lines.append(
            f"  {r.id:8} {mark}  {r.total:2}/{MAX_TOTAL}  status={r.status} flags={r.flags}{suffix}"
        )
    return "\n".join(lines)


def main() -> None:  # pragma: no cover - manual scorecard
    print(scorecard(evaluate()))


if __name__ == "__main__":  # pragma: no cover
    main()
