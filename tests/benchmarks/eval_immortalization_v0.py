"""Benchmark-first re-evaluation of the 10 immortalization questions.

Runs each fixed question (``immortalization_v0.yaml``) through the *real* deterministic
``DecisionReport`` pipeline and scores the machine-checkable rubric axes, so the
benchmark can be re-run as an honest scorecard rather than only a pass/fail test. The
subjective rubric axes (prose quality, expert nuance) still need a human; this harness
scores only what is deterministically decidable and states its own limits.

Coverage note: the deterministic builder answers the four *assessment* intents (7 of the
10 questions). The two mechanism questions (Q5/Q6) and the hypothesis question (Q9) are
refused by the builder *by design* — they are the KG-explain / LLM-synthesis path wired
in a later slice (PR9). Their required knowledge already lives in the seed graph; this
harness records them as ``deferred`` rather than failed.

Run ``python -m tests.benchmarks.eval_immortalization_v0`` for the scorecard.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.models import ASSESSMENT_INTENTS, AssessmentIntent
from virtualcell.agents.immortalization.rules import (
    UnsupportedIntentError,
    build_decision_report,
)

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

    @property
    def total(self) -> int:
        return sum(a.score for a in self.axes)

    @property
    def passed(self) -> bool:
        # A deferred (mechanism/hypothesis) question is not a failure of the assessment
        # builder. A handled question passes at the rubric threshold, and a wrong status
        # is a hard fail regardless of total.
        if not self.handled:
            return False
        status_ok = next(a.score for a in self.axes if a.name == "status_match") > 0
        return status_ok and self.total >= PASS_THRESHOLD


def load_spec() -> dict:
    return yaml.safe_load(_SPEC_PATH.read_text(encoding="utf-8"))


def _tier(claim) -> str | None:
    tier = getattr(claim, "tier", None)
    return tier.value if hasattr(tier, "value") else tier


def _axis_token(axis: str) -> str:
    return axis.lower().replace("-", "").replace("_", "").replace("b", "b")


def _evaluate_question(question: dict) -> QuestionEval:
    qid = question["id"]
    intent = AssessmentIntent(question["intent"])
    scenario = question["scenario"]
    expected_status = question.get("expected_status")
    expected_flags = sorted(question.get("expected_flags", []) or [])

    if intent not in ASSESSMENT_INTENTS:
        return QuestionEval(
            id=qid,
            intent=intent.value,
            handled=False,
            deferred_reason="mechanism/hypothesis intent -- KG-explain/LLM-synthesis path (PR9)",
            expected_status=expected_status,
            expected_flags=expected_flags,
        )

    try:
        report = build_decision_report(input_from_scenario(intent, scenario))
    except UnsupportedIntentError as exc:  # pragma: no cover - guarded by the intent check
        return QuestionEval(
            id=qid,
            intent=intent.value,
            handled=False,
            deferred_reason=str(exc),
            expected_status=expected_status,
            expected_flags=expected_flags,
        )

    status = report.candidate_status.value if report.candidate_status else None
    flags = sorted(f.value for f in report.flags)
    acceptable = question.get("acceptable_status") or ([expected_status] if expected_status else [])

    axes = [
        _score_status(status, flags, acceptable, expected_flags),
        _score_multi_marker(report),
        _score_both_sides(report, question),
        _score_overinterpretation(report),
        _score_next_experiment(report),
        _score_tiers(report),
    ]
    return QuestionEval(
        id=qid,
        intent=intent.value,
        handled=True,
        status=status,
        expected_status=expected_status,
        flags=flags,
        expected_flags=expected_flags,
        axes=axes,
    )


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
    return [_evaluate_question(q) for q in load_spec()["questions"]]


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
