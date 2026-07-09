"""Regression harness: the rule-based baseline must match the benchmark spec.

Loads the machine-readable benchmark (immortalization_v0.yaml) and checks that
``baseline_status`` reproduces every question's ``expected_status`` (and
``expected_flags`` where given). This freezes the Phase-0 self-check as CI: if the
deterministic baseline ever drifts from the fixed expectations, the build fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from virtualcell.agents.immortalization.baseline import baseline_status

SPEC = yaml.safe_load(
    (Path(__file__).parent / "immortalization_v0.yaml").read_text(encoding="utf-8")
)
QUESTIONS = SPEC["questions"]
# Mechanism questions (Q5/Q6) carry no status; only assessment questions are scored here.
STATUS_QUESTIONS = [q for q in QUESTIONS if q.get("expected_status") is not None]


def test_spec_shape_is_stable() -> None:
    assert SPEC["candidate_status_vocab"] == [
        "possible_candidate",
        "senescence_or_stress_prone",
        "insufficient_evidence",
    ]
    assert len(QUESTIONS) == 10
    assert len(STATUS_QUESTIONS) == 8  # Q5 and Q6 are mechanism questions (no status)


@pytest.mark.parametrize("q", STATUS_QUESTIONS, ids=[q["id"] for q in STATUS_QUESTIONS])
def test_baseline_matches_expected(q: dict) -> None:
    status, flags = baseline_status(q["scenario"])

    acceptable = q.get("acceptable_status")
    if acceptable:
        assert status in acceptable, f"{q['id']}: {status} not in {acceptable}"
    else:
        assert status == q["expected_status"], f"{q['id']}: got {status}"

    if "expected_flags" in q:
        assert sorted(flags) == sorted(q["expected_flags"]), f"{q['id']}: flags {flags}"
