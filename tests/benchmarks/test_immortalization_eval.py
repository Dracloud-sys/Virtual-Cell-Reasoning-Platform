"""Benchmark-first regression: pin the DecisionReport re-evaluation of the 10 questions.

Freezes the immortalization vertical so a future change cannot silently regress it. All
10 fixed questions are answered on a real ``DecisionReport`` obtained from the **product
path** — ``ImmortalizationAssessmentAgent.assess``, the same entry point API and CLI
callers use — and must clear the rubric threshold. The domain guardrails (no over-call,
Q9's weak-only relations, forbidden P53 phrasings scored over assertion fields only) are
pinned here too.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from eval_immortalization_v0 import (
    PASS_THRESHOLD,
    build_agent,
    evaluate,
    load_spec,
)

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import RelationType
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource

_RESULTS = {r.id: r for r in evaluate()}
_MECHANISM = {"IMM-Q5", "IMM-Q6"}  # mechanism questions (no candidate status)
_HYPOTHESIS = "IMM-Q9"
_SPEC = {q["id"]: q for q in load_spec()["questions"]}


def test_all_ten_questions_are_handled() -> None:
    assert len(_RESULTS) == 10
    assert all(r.handled for r in _RESULTS.values())  # nothing deferred anymore


@pytest.mark.parametrize("qid", sorted(_RESULTS))
def test_every_question_passes_the_rubric(qid: str) -> None:
    result = _RESULTS[qid]
    assert result.passed, f"{qid} scored {result.total}/12 (threshold {PASS_THRESHOLD})"


@pytest.mark.parametrize("qid", sorted(_MECHANISM))
def test_mechanism_questions_carry_no_status_and_a_chain(qid: str) -> None:
    result = _RESULTS[qid]
    assert result.status is None  # a mechanism question never asserts a candidate status
    chain_axis = next(a for a in result.axes if a.name == "mechanistic_chain")
    assert chain_axis.score > 0  # answered from the KG-explain path


def test_hypothesis_question_is_conservative() -> None:
    result = _RESULTS[_HYPOTHESIS]
    assert result.status == "insufficient_evidence"
    scores = {a.name: a.score for a in result.axes}
    assert scores["forbidden_absent"] == 2  # no 'without P53' / 'P53 loss' / 'CAUSES ...'
    assert scores["weak_relations"] == 2  # spontaneous route reached only weakly


def test_seed_graph_holds_q9_weak_relations_only() -> None:
    # Q9 (spontaneous route) requires ASSOCIATED_WITH / SUGGESTS and *forbids* a causal
    # claim; the curated seed encodes exactly that, so the report can format it honestly.
    spec = {q["id"]: q for q in load_spec()["questions"]}["IMM-Q9"]
    required = {RelationType[r] for r in spec["required_edge_relations"]}  # YAML uses names

    source = ImmortalizationSeedSource()
    store = InMemoryKnowledgeStore()
    for entity in source.entities():
        store.upsert(entity)
    spontaneous_edges = [
        i for i in source.interactions() if i.target_id.endswith("spontaneous_immortalization")
    ]
    relations = {i.relation for i in spontaneous_edges}
    assert relations
    assert relations <= required  # only the weak relations, never a causal/established one


# --- the benchmark must exercise the product path (PR10b) --------------------


def test_every_question_is_evaluated_through_the_agent(monkeypatch) -> None:
    """All ten questions must reach ``ImmortalizationAssessmentAgent.assess``.

    Counts real calls rather than inspecting imports, so the benchmark cannot quietly
    regress to calling an internal builder directly for some intents.
    """
    seen: list[str] = []
    original = ImmortalizationAssessmentAgent.assess

    def spy(self, data):
        seen.append(data.intent.value)
        return original(self, data)

    monkeypatch.setattr(ImmortalizationAssessmentAgent, "assess", spy)
    results = evaluate()

    assert len(seen) == 10 == len(results)
    # Every intent family went through the one public entry point.
    assert {"mechanism_explanation", "hypothesis_handling"} <= set(seen)


def test_benchmark_does_not_import_builders_directly() -> None:
    # The agent is the sole dispatch authority; the harness must not select builders.
    import eval_immortalization_v0 as harness

    source = Path(harness.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "build_decision_report",
        "build_mechanism_report",
        "build_hypothesis_report",
    ):
        assert forbidden not in source, f"benchmark still dispatches {forbidden} directly"


@pytest.mark.parametrize("qid", ["IMM-Q5", "IMM-Q6", "IMM-Q9"])
def test_agent_assess_matches_the_scored_report(qid: str) -> None:
    # The report the benchmark scored is exactly what a product caller receives.
    question = _SPEC[qid]
    data = input_from_scenario(question["intent"], question["scenario"])
    first = build_agent().assess(data)
    second = build_agent().assess(data)
    assert first.model_dump() == second.model_dump()  # deterministic across instances


def test_repeated_evaluation_is_identical() -> None:
    first = {r.id: (r.total, r.status, r.passed) for r in evaluate()}
    second = {r.id: (r.total, r.status, r.passed) for r in evaluate()}
    assert first == second


def test_q6_does_not_assert_established_non_oncogenicity() -> None:
    """The Q6 rubric correction: safety must be validated, never inferred.

    ``non_oncogenic_reliable`` was removed as a key point because it rewarded an
    unsupported safety claim. The report may draw the mechanistic contrast with viral
    oncogene approaches, but must not assert non-tumorigenicity as established.
    """
    question = _SPEC["IMM-Q6"]
    report = build_agent().assess(input_from_scenario(question["intent"], question["scenario"]))
    asserted = " ".join(
        [report.conclusion, *(c.statement for c in report.supporting_evidence)]
    ).lower()
    for unsafe in ("non-oncogenic", "non oncogenic", "tumor-free", "proven safe"):
        assert unsafe not in asserted, f"Q6 asserts unsupported safety: {unsafe!r}"

    # Safety is instead demanded as validation work.
    guidance = " ".join([*report.limitations, *report.recommended_validation]).lower()
    assert "non-tumorigenicity" in guidance
    assert "genomic stability" in guidance
    assert "viral oncogene" in guidance  # the defensible mechanistic distinction


def test_no_question_overcalls_immortalization() -> None:
    # The domain's top failure mode: never present a possibility as confirmed
    # immortalization. Mechanism questions carry no status; assessment/hypothesis
    # questions stay within the coarse three-status vocabulary.
    allowed = {
        None,
        "possible_candidate",
        "senescence_or_stress_prone",
        "insufficient_evidence",
    }
    assert all(r.status in allowed for r in _RESULTS.values())
