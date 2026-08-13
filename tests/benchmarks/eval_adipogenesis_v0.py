"""Adipogenesis reasoning scorecard — the second vertical's regression anchor.

Runs the **product path** (`AdipogenesisDomainPack.execute`, the same entry point the API and
CLI use), not a re-implementation of its rules. That is the PR10b lesson: a benchmark that
scores a private copy of the logic scores nothing.

Scoring is deliberately harsher than "did it pick the right label". A scenario passes only if
it reaches the right status *and* names what is missing, refuses the forbidden phrasings, and
proposes a next step that would reduce the uncertainty it just reported. Soft criteria are
scored separately so a report can be correct and still be visibly weaker than it should be.

Run directly for the scorecard::

    python -m tests.benchmarks.eval_adipogenesis_v0
"""

from __future__ import annotations

import pathlib
import sys

import yaml

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.adipogenesis_seed import AdipogenesisSeedSource
from virtualcell.knowledge.sources.base import load_into
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.packs.adipogenesis import AdipogenesisDomainPack
from virtualcell.reasoning.kernel import assertion_texts

SPEC = pathlib.Path(__file__).with_name("adipogenesis_v0.yaml")
HARD_POINTS = 8
SOFT_POINTS = 4
MAX_POINTS = HARD_POINTS + SOFT_POINTS
PASS_THRESHOLD = 9


def load_spec() -> dict:
    return yaml.safe_load(SPEC.read_text(encoding="utf-8"))


def _store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(AdipogenesisSeedSource(), store)
    return store


def run_scenario(question: dict) -> ReasoningResponse:
    """Answer one scenario through the shipped pack."""
    experiment = dict(question["input"])
    intent = experiment.pop("intent", None)
    task = "explain_mechanism" if intent == "mechanism_explanation" else "assess_state"
    query = ReasoningQuery.model_validate(
        {"domain": "adipogenesis", "task": task, "experiment": experiment}
    )
    return AdipogenesisDomainPack().execute(query, _store())


def _hard_score(
    question: dict, response: ReasoningResponse, forbidden: list[str]
) -> tuple[int, list[str]]:
    """Points for getting the science right. Failures here fail the scenario."""
    points = 0
    failures: list[str] = []
    report = response.domain_details["decision_report"]

    expected = question.get("expect_status")
    actual = response.decision_support.status
    if actual == expected:
        points += 3
    else:
        failures.append(f"status {actual!r} != {expected!r}")

    asserted = " ".join(assertion_texts(_as_report(report))).lower()
    leaked = [phrase for phrase in forbidden if phrase in asserted]
    if leaked:
        failures.append(f"asserted forbidden phrasing: {leaked}")
    else:
        points += 3

    required_flags = set(question.get("require_flags") or [])
    actual_flags = set(response.decision_support.flags)
    if required_flags <= actual_flags:
        points += 1
    else:
        failures.append(f"missing flags {sorted(required_flags - actual_flags)}")

    forbidden_flags = set(question.get("forbid_flags") or [])
    if forbidden_flags & actual_flags:
        failures.append(f"unexpected flags {sorted(forbidden_flags & actual_flags)}")
    else:
        points += 1

    if question.get("require_mechanistic_chain") and not response.mechanistic_links:
        failures.append("no mechanistic chain")
    if question.get("require_inhibitory_arm"):
        steps = [step for link in response.mechanistic_links for step in link.path]
        if not any("-inhibits->" in step for step in steps):
            failures.append("mechanistic chain shows no inhibitory arm")
    if question.get("require_conflict_explanation") and not report["conflict_explanation"]:
        failures.append("no conflict explanation")
    for side in question.get("require_evidence") or []:
        key = f"{side}_evidence"
        if not report[key]:
            failures.append(f"no {side} evidence")

    return points, failures


def _soft_score(question: dict, response: ReasoningResponse) -> tuple[int, list[str]]:
    """Points for reasoning quality. Losses here are reported, not fatal."""
    points = 0
    lost: list[str] = []

    expected_missing = set(question.get("expect_missing") or [])
    if expected_missing <= set(response.missing_information):
        points += 1
    else:
        lost.append("names_missing_axes")

    wanted = question.get("expect_next_experiment_contains") or []
    joined = " ".join(response.recommended_next_experiments)
    if all(fragment in joined for fragment in wanted):
        points += 1
    else:
        lost.append("next_step_addresses_gap")

    if response.limitations:
        points += 1
    else:
        lost.append("limitations_stated")

    positive = response.decision_support.status in ("differentiating", "partially_differentiated")
    if not positive or "maturation_unverified" in response.decision_support.flags:
        points += 1
    else:
        lost.append("maturity_not_assumed")

    return points, lost


def _as_report(payload: dict):
    from virtualcell.reasoning.decision import DecisionReport

    return DecisionReport.model_validate(payload)


def evaluate() -> tuple[int, int, list[dict]]:
    spec = load_spec()
    forbidden = [phrase.lower() for phrase in spec["forbidden_phrases"]]
    rows: list[dict] = []
    passed = 0

    for question in spec["questions"]:
        response = run_scenario(question)
        hard, failures = _hard_score(question, response, forbidden)
        soft, lost = _soft_score(question, response)
        total = hard + soft
        ok = not failures and total >= PASS_THRESHOLD
        passed += int(ok)
        rows.append(
            {
                "id": question["id"],
                "ok": ok,
                "score": total,
                "status": response.decision_support.status,
                "flags": response.decision_support.flags,
                "failures": failures,
                "soft_lost": lost,
            }
        )
    return passed, len(spec["questions"]), rows


def main() -> int:
    passed, total, rows = evaluate()
    print("=" * 68)
    print(f"adipogenesis v0 | passed {passed}/{total} (threshold {PASS_THRESHOLD}/{MAX_POINTS})")
    print("-" * 68)
    for row in rows:
        verdict = "PASS" if row["ok"] else "FAIL"
        soft = f"  (soft: {', '.join(row['soft_lost'])})" if row["soft_lost"] else ""
        print(
            f"  {row['id']:8} {verdict}  {row['score']}/{MAX_POINTS}  "
            f"status={row['status']} flags={row['flags']}{soft}"
        )
        for failure in row["failures"]:
            print(f"           !! {failure}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
