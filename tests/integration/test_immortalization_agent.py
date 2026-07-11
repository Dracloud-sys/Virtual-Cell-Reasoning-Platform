"""End-to-end agent regression over the whole benchmark (PR5c-3).

Every benchmark question passes through the real agent entry points
(`input_from_scenario` -> `agent.assess`, and `AgentInput` -> `agent.run`), and the
status/flags/tier/citation boundaries are pinned so the agent never overrides the
builders or policy.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.agent import (
    AssessmentInputError,
    ImmortalizationAssessmentAgent,
)
from virtualcell.agents.immortalization.baseline import baseline_status
from virtualcell.core.contracts import AgentInput
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.reasoning.decision import DecisionReport

_SPEC = yaml.safe_load(
    (Path(__file__).parent.parent / "benchmarks" / "immortalization_v0.yaml").read_text(
        encoding="utf-8"
    )
)
_QUESTIONS = _SPEC["questions"]
_ASSESSMENT = {
    "immortalization_assessment",
    "senescence_assessment",
    "immortalization_vs_functionality",
    "conflicting_evidence_assessment",
}
_FORBIDDEN = [
    "confirmed immortalized",
    "definitively immortal",
    "without p53",
    "p53 loss",
    "p53 knockout",
    "p53 deletion",
    "causes spontaneous immortalization",
    "directly inhibits p16",
    "guarantees immortalization",
]


def _agent() -> ImmortalizationAssessmentAgent:
    store = InMemoryKnowledgeStore()
    load_into(ImmortalizationSeedSource(), store)
    return ImmortalizationAssessmentAgent(store)


def _report(q: dict) -> DecisionReport:
    return _agent().assess(input_from_scenario(q["intent"], q["scenario"]))


@pytest.mark.parametrize("q", _QUESTIONS, ids=[q["id"] for q in _QUESTIONS])
def test_e2e_status_and_flags_per_question(q: dict) -> None:
    report = _report(q)
    expected = q.get("expected_status")
    if expected is None:  # mechanism questions Q5/Q6
        assert report.candidate_status is None
    elif "acceptable_status" in q:
        assert report.candidate_status in q["acceptable_status"]
    else:
        assert report.candidate_status == expected
    if "expected_flags" in q:
        assert sorted(report.flags) == sorted(q["expected_flags"])


def test_status_source_boundaries() -> None:
    for q in _QUESTIONS:
        data = input_from_scenario(q["intent"], q["scenario"])
        report = _agent().assess(data)
        if q["intent"] in _ASSESSMENT:
            assert report.candidate_status == baseline_status(data.marker_dict())[0]
        elif q["intent"] == "mechanism_explanation":
            assert report.candidate_status is None
        elif q["intent"] == "hypothesis_handling":
            assert report.candidate_status == "insufficient_evidence"


@pytest.mark.parametrize("q", _QUESTIONS, ids=[q["id"] for q in _QUESTIONS])
def test_no_forbidden_phrasing_in_assertion_fields(q: dict) -> None:
    report = _report(q)
    blob = " ".join(
        [
            report.conclusion,
            *(c.statement for c in report.supporting_evidence),
            *(c.statement for c in report.contradicting_evidence),
        ]
    ).lower()
    for phrase in _FORBIDDEN:
        assert phrase not in blob, f"{q['id']}: {phrase!r}"


def test_q9_hypothesis_details() -> None:
    q9 = next(q for q in _QUESTIONS if q["id"] == "IMM-Q9")
    report = _report(q9)
    assert report.candidate_status == "insufficient_evidence"
    assert len(report.supporting_evidence) == 4
    p53 = next(c for c in report.supporting_evidence if "P53-independent" in c.statement)
    assert p53.citations  # citation preserved


async def test_run_round_trip_assessment() -> None:
    agent = _agent()
    payload = {
        "intent": "immortalization_assessment",
        "PDL_trend": "increasing",
        "DT_trend": "stable",
        "gammaH2AX": "low",
    }
    out = await agent.run(AgentInput(query="Assess", context={"assessment": payload}))
    report = DecisionReport.model_validate(out.result)

    assert out.agent == "immortalization_assessment"
    assert out.notes == report.conclusion
    assert out.result == report.model_dump(mode="json")
    assert 0.0 <= out.confidence <= 1.0
    assert [c.statement for c in out.claims] == [
        c.statement for c in report.supporting_evidence
    ] + [c.statement for c in report.contradicting_evidence]


async def test_run_mechanism_status_is_json_null() -> None:
    agent = _agent()
    payload = {"intent": "mechanism_explanation", "construct": "TERT_plus_CDK4"}
    out = await agent.run(AgentInput(query="x", context={"assessment": payload}))
    assert out.result["candidate_status"] is None


async def test_run_hypothesis_status_is_insufficient() -> None:
    agent = _agent()
    out = await agent.run(
        AgentInput(query="x", context={"assessment": {"intent": "hypothesis_handling"}})
    )
    assert out.result["candidate_status"] == "insufficient_evidence"


async def test_run_rejects_bad_payloads() -> None:
    agent = _agent()
    with pytest.raises(AssessmentInputError):
        await agent.run(AgentInput(query="x"))  # no assessment payload
    with pytest.raises(AssessmentInputError):
        await agent.run(AgentInput(query="x", context={"assessment": "not-a-dict"}))
    with pytest.raises(AssessmentInputError):
        await agent.run(AgentInput(query="x", context={"assessment": {}}))  # no intent
    with pytest.raises(AssessmentInputError):
        await agent.run(
            AgentInput(
                query="x",
                context={"assessment": {"intent": "immortalization_assessment", "p16": "nope"}},
            )
        )
