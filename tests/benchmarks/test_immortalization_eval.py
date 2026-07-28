"""Benchmark-first regression: pin the DecisionReport re-evaluation of the 10 questions.

Freezes the current, honest state of the immortalization vertical so a future change
cannot silently regress it: every *assessment* question the deterministic builder handles
must still clear the rubric threshold on a real ``DecisionReport``, and the mechanism /
hypothesis questions remain correctly *deferred* to the later KG-explain/LLM-synthesis
slice (PR9) — with the knowledge their answers need already present in the seed graph.
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
_DEFERRED = {"IMM-Q5", "IMM-Q6", "IMM-Q9"}  # mechanism (Q5/Q6) + hypothesis (Q9)


def test_all_ten_questions_are_covered() -> None:
    assert len(_RESULTS) == 10


@pytest.mark.parametrize("qid", sorted(set(_RESULTS) - _DEFERRED))
def test_handled_assessment_questions_pass_the_rubric(qid: str) -> None:
    result = _RESULTS[qid]
    assert result.handled, f"{qid} should be handled by the deterministic builder"
    assert result.passed, f"{qid} scored {result.total}/12 (threshold {PASS_THRESHOLD})"
    # Status is the hard gate: it must match the frozen expectation (or acceptable set).
    status_axis = next(a for a in result.axes if a.name == "status_match")
    assert status_axis.score > 0, f"{qid}: wrong status {result.status}"


@pytest.mark.parametrize("qid", sorted(_DEFERRED))
def test_mechanism_and_hypothesis_questions_are_deferred(qid: str) -> None:
    result = _RESULTS[qid]
    assert not result.handled  # by design: the deterministic builder refuses these
    assert result.deferred_reason


def test_seed_graph_holds_q9_weak_relations_only() -> None:
    # Q9 (spontaneous route) requires ASSOCIATED_WITH / SUGGESTS and *forbids* a causal
    # claim. The curated seed already encodes exactly that, so the answer is deferred on
    # formatting, not on missing (or over-strong) knowledge.
    spec = {q["id"]: q for q in load_spec()["questions"]}["IMM-Q9"]
    required = {RelationType[r] for r in spec["required_edge_relations"]}  # YAML uses names

    store = InMemoryKnowledgeStore()
    source = ImmortalizationSeedSource()
    for entity in source.entities():
        store.upsert(entity)
    spontaneous_edges = [
        i for i in source.interactions() if i.target_id.endswith("spontaneous_immortalization")
    ]
    relations = {i.relation for i in spontaneous_edges}
    assert relations
    assert relations <= required  # only the weak relations, never a causal/established one


def test_no_handled_question_overcalls_immortalization() -> None:
    # The domain's top failure mode: never present a possibility as confirmed
    # immortalization. There is no such status in the vocabulary, and none is produced.
    for result in _RESULTS.values():
        if result.handled:
            assert result.status in {
                "possible_candidate",
                "senescence_or_stress_prone",
                "insufficient_evidence",
            }
