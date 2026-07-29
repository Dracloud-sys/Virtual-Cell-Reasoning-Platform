"""Benchmark-first regression: pin the DecisionReport re-evaluation of the 10 questions.

Freezes the immortalization vertical so a future change cannot silently regress it: all
10 fixed questions are now answered on a real ``DecisionReport`` and must clear the rubric
threshold — the seven assessment questions via the deterministic builder, and the mechanism
(Q5/Q6) and hypothesis (Q9) questions via the KG-explain formatter (PR9-b). The domain
guardrails (no over-call, Q9's weak-only relations and forbidden P53 phrasings) are pinned
here too.
"""

from __future__ import annotations

import pytest
from eval_immortalization_v0 import (
    PASS_THRESHOLD,
    evaluate,
    load_spec,
)

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import RelationType
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource

_RESULTS = {r.id: r for r in evaluate()}
_MECHANISM = {"IMM-Q5", "IMM-Q6"}  # mechanism questions (no candidate status)
_HYPOTHESIS = "IMM-Q9"


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
