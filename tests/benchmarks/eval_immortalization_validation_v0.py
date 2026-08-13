"""Validation-loop scorecard: does measuring what was asked for change what is said next?

Runs the **product path** (`ImmortalizationDomainPack.execute`) per the PR10b rule. Scored
pass/fail rather than out of twelve, because every check here is a contract rather than a
matter of degree — a status that moved, or an assay re-requested after it was run, is not a
weaker answer, it is the defect this benchmark exists to catch.

Run directly for the scorecard::

    python -m tests.benchmarks.eval_immortalization_validation_v0
"""

from __future__ import annotations

import pathlib
import sys

import yaml

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.packs.immortalization import ImmortalizationDomainPack
from virtualcell.reasoning.decision import DecisionReport
from virtualcell.reasoning.kernel import assertion_texts

SPEC = pathlib.Path(__file__).with_name("immortalization_validation_v0.yaml")


def load_spec() -> dict:
    return yaml.safe_load(SPEC.read_text(encoding="utf-8"))


def run_scenario(question: dict) -> ReasoningResponse:
    store = InMemoryKnowledgeStore()
    load_into(ImmortalizationSeedSource(), store)
    query = ReasoningQuery.model_validate(
        {
            "domain": question["domain"],
            "task": question["task"],
            "experiment": question["experiment"],
        }
    )
    return ImmortalizationDomainPack().execute(query, store)


def _check(question: dict, response: ReasoningResponse, forbidden: list[str]) -> list[str]:
    """Every failed contract for one scenario. Empty means the loop is closed for that axis."""
    failures: list[str] = []
    support = response.decision_support
    report = DecisionReport.model_validate(response.domain_details["decision_report"])

    if support.status != question["expect_status"]:
        failures.append(f"status {support.status!r} != {question['expect_status']!r}")

    flags = set(support.flags)
    for flag in question.get("require_flags") or []:
        if flag not in flags:
            failures.append(f"missing flag {flag!r}")
    for flag in question.get("forbid_flags") or []:
        if flag in flags:
            failures.append(f"unexpected flag {flag!r}")

    validation = " | ".join(response.recommended_validation)
    nexts = " | ".join(response.recommended_next_experiments)
    for fragment in question.get("expect_validation_contains") or []:
        if fragment not in validation:
            failures.append(f"validation does not mention {fragment!r}")
    for fragment in question.get("forbid_validation_contains") or []:
        if fragment in validation:
            failures.append(f"answered axis still listed as unverified: {fragment!r}")
    for fragment in question.get("expect_next_contains") or []:
        if fragment not in nexts:
            failures.append(f"next experiments do not mention {fragment!r}")
    for fragment in question.get("forbid_next_contains") or []:
        if fragment in nexts:
            failures.append(f"measured axis re-requested as an experiment: {fragment!r}")

    wanted = question.get("expect_evidence_contains")
    if wanted:
        stated = [
            c.statement for c in (*response.supporting_evidence, *response.contradicting_evidence)
        ]
        if not any(wanted in statement for statement in stated):
            failures.append(f"measurement not stated as evidence: {wanted!r}")

    risk = question.get("expect_risk_contains")
    if risk and not any(risk in line for line in response.overinterpretation_risks):
        failures.append(f"risk does not mention {risk!r}")

    asserted = " ".join(assertion_texts(report)).lower()
    for phrase in forbidden:
        if phrase in asserted:
            failures.append(f"asserted forbidden phrasing: {phrase!r}")

    return failures


def evaluate() -> tuple[int, int, list[dict]]:
    spec = load_spec()
    forbidden = [phrase.lower() for phrase in spec["forbidden_phrases"]]
    rows: list[dict] = []
    for question in spec["questions"]:
        response = run_scenario(question)
        failures = _check(question, response, forbidden)
        rows.append(
            {
                "id": question["id"],
                "title": question["title"],
                "ok": not failures,
                "status": response.decision_support.status,
                "flags": response.decision_support.flags,
                "failures": failures,
            }
        )
    return sum(row["ok"] for row in rows), len(rows), rows


def main() -> int:
    passed, total, rows = evaluate()
    print("=" * 74)
    print(f"immortalization validation loop v0 | passed {passed}/{total}")
    print("-" * 74)
    for row in rows:
        print(
            f"  {row['id']:11} {'PASS' if row['ok'] else 'FAIL'}  "
            f"status={row['status']} flags={row['flags']}  {row['title']}"
        )
        for failure in row["failures"]:
            print(f"              !! {failure}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
