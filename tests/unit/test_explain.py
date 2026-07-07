"""Tests for the evidence-graded multi-hop mechanistic reasoning primitive."""

from __future__ import annotations

import pytest

from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import Interaction, Protein, RelationType
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.sample import SampleDataSource
from virtualcell.reasoning.explain import explain


@pytest.fixture
def store() -> InMemoryKnowledgeStore:
    s = InMemoryKnowledgeStore()
    load_into(SampleDataSource(), s)
    return s


def test_direct_edge_is_established_multi_hop_is_downgraded(store) -> None:
    result = explain(store, "gene:TP53", max_hops=2)
    by_id = {link.target_id: link for link in result.links}

    # gene:TP53 -encodes-> protein:P04637 is a direct, curated edge → established.
    p53 = by_id["protein:P04637"]
    assert p53.hops == 1
    assert p53.tier == EvidenceTier.ESTABLISHED
    assert p53.confidence == pytest.approx(1.0)

    # apoptosis is reached only across 2 hops → an inference, so hypothesis, not fact.
    apop = by_id["pathway:apoptosis"]
    assert apop.hops == 2
    assert apop.tier == EvidenceTier.HYPOTHESIS
    assert apop.confidence < 1.0
    assert apop.path  # the "why" chain is populated


def test_seed_is_excluded_and_results_ranked_by_confidence(store) -> None:
    result = explain(store, "gene:TP53", max_hops=2)
    assert all(link.target_id != "gene:TP53" for link in result.links)
    confs = [link.confidence for link in result.links]
    assert confs == sorted(confs, reverse=True)


def test_max_hops_limits_reach(store) -> None:
    one_hop = explain(store, "gene:TP53", max_hops=1)
    ids = {link.target_id for link in one_hop.links}
    # Only the directly encoded protein is within one hop.
    assert ids == {"protein:P04637"}


def test_multiple_paths_corroborate_confidence() -> None:
    store = InMemoryKnowledgeStore()
    for pid in ("A", "B", "C", "D"):
        store.upsert(Protein(id=f"protein:{pid}", name=pid))
    for src, dst in (("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")):
        store.add_interaction(
            Interaction(
                source_id=f"protein:{src}",
                target_id=f"protein:{dst}",
                relation=RelationType.INTERACTS_WITH,
                confidence=0.5,
            )
        )

    result = explain(store, "protein:A", max_hops=2)
    d = next(link for link in result.links if link.target_id == "protein:D")
    # Two independent 2-hop paths (each 0.5*0.5=0.25) corroborate via noisy-OR:
    # 1 - (1-0.25)(1-0.25) = 0.4375, higher than either path alone.
    assert d.hops == 2
    assert d.confidence == pytest.approx(0.4375)


def test_unknown_seed_raises(store) -> None:
    with pytest.raises(ValueError, match="entity not found"):
        explain(store, "gene:DOES_NOT_EXIST")
