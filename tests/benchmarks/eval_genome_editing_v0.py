"""Genome-editing reasoning scorecard — the third vertical's regression anchor.

Runs the **product path** (`GenomeEditingDomainPack.execute`) per the PR10b rule: a benchmark
that scores a private copy of the logic scores nothing.

Written before the vertical existed, which is the point. If the questions had been written
afterwards they would describe whatever got built; written first, they are the specification
the implementation had to satisfy, and two of them changed the design (the conflict scenario
forced a separate confirmation axis, and GE-Q3 forced the assay-strength rule to run in both
directions rather than only against a positive).

Run directly for the scorecard::

    python -m tests.benchmarks.eval_genome_editing_v0
"""

from __future__ import annotations

import pathlib
import sys

import yaml

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.genome_editing_seed import GenomeEditingSeedSource
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.packs.genome_editing import GenomeEditingDomainPack
from virtualcell.reasoning.decision import DecisionReport
from virtualcell.reasoning.kernel import assertion_texts

SPEC = pathlib.Path(__file__).with_name("genome_editing_v0.yaml")


def load_spec() -> dict:
    return yaml.safe_load(SPEC.read_text(encoding="utf-8"))


def run_scenario(question: dict) -> ReasoningResponse:
    store = InMemoryKnowledgeStore()
    load_into(GenomeEditingSeedSource(), store)
    query = ReasoningQuery.model_validate(
        {
            "domain": "genome_editing",
            "task": question.get("task", "assess_state"),
            "experiment": question["experiment"],
        }
    )
    return GenomeEditingDomainPack().execute(query, store)


def _check(question: dict, response: ReasoningResponse, forbidden: list[str]) -> list[str]:
    """Every contract this scenario broke. Empty means it answered well.

    Pass/fail rather than a score out of twelve: every check here is a contract. A status that
    moved, an overclaim, or a measurement reported as consumed when nothing read it is not a
    weaker answer — it is the defect the question exists to catch.
    """
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

    for axis in question.get("expect_missing") or []:
        if axis not in response.missing_information:
            failures.append(f"missing axis not named: {axis!r}")

    plan = " | ".join(response.recommended_next_experiments)
    for fragment in question.get("expect_next_contains") or []:
        if fragment not in plan:
            failures.append(f"next experiments do not mention {fragment!r}")

    unsupported = set(response.measurement_consumption.unsupported)
    for key in question.get("expect_unsupported") or []:
        if key not in unsupported:
            failures.append(f"unrecognised key not reported back: {key!r}")

    for side in question.get("require_evidence") or []:
        if not getattr(response, f"{side}_evidence"):
            failures.append(f"no {side} evidence")
    if question.get("require_conflict_explanation") and not report.conflict_explanation:
        failures.append("no conflict explanation")
    if question.get("require_mechanistic_chain") and not response.mechanistic_links:
        failures.append("no mechanistic chain")
    if question.get("require_repair_arm"):
        steps = [step for link in response.mechanistic_links for step in link.path]
        if not any("end joining" in s or "Homology-directed" in s for s in steps):
            failures.append("mechanistic chain shows the break but no repair pathway")

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
    print("=" * 78)
    print(f"genome editing v0 | passed {passed}/{total}")
    print("-" * 78)
    for row in rows:
        print(
            f"  {row['id']:8} {'PASS' if row['ok'] else 'FAIL'}  "
            f"status={row['status']} flags={row['flags']}  {row['title']}"
        )
        for failure in row["failures"]:
            print(f"           !! {failure}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
