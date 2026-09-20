"""Corroboration requires independence, and the report has to show it.

`explain` boosts a target's confidence when several paths reach it, via the noisy-OR in
`combine_confidences`. That aggregation is only meaningful for **independent** evidence:
its docstring says so, and nothing enforced it. Every path to a target was combined,
including paths that traverse the *same edge*, so re-reading one fact through a longer
detour read as a second opinion.

The failure is worse than a wrong number. A `MechanisticLink` reports one path — the
shortest — so a caller saw a confidence inflated by a redundant route with no way to
discover that from the output. On a platform whose stated identity is auditable,
evidence-graded reasoning, a number that cannot be traced to its support is the defect.

These questions were written before the fix. The rule they pin: **paths corroborate only
when they are edge-disjoint**, the selection prefers the strongest paths, and the count of
independent paths that contributed travels with the answer.

They are deliberately written against a hand-built graph rather than a seed source. A
seed graph's topology is biology and may legitimately change; these are properties of the
traversal, and must hold for any graph at all.
"""

from __future__ import annotations

import pytest

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import Interaction, Protein, RelationType
from virtualcell.reasoning.explain import explain


def _store(*edges: tuple[str, str, float]) -> InMemoryKnowledgeStore:
    """A store holding exactly the named nodes and the given directed edges."""
    store = InMemoryKnowledgeStore()
    for name in {end for src, dst, _ in edges for end in (src, dst)}:
        store.upsert(Protein(id=f"protein:{name}", name=name))
    for src, dst, confidence in edges:
        store.add_interaction(
            Interaction(
                source_id=f"protein:{src}",
                target_id=f"protein:{dst}",
                relation=RelationType.PROMOTES,
                confidence=confidence,
            )
        )
    return store


def _link(store: InMemoryKnowledgeStore, seed: str, target: str, hops: int):
    result = explain(store, f"protein:{seed}", max_hops=hops)
    return next(link for link in result.links if link.target_id == f"protein:{target}")


# --- the defect, reproduced ---------------------------------------------------------------


def _shared_edge_store() -> InMemoryKnowledgeStore:
    """Two routes from A to T, both ending on the very same ``B -> T`` edge.

        A -> B (1.0) -> T (0.5)          the direct route, 2 hops
        A -> C (1.0) -> B (1.0) -> T     a detour that re-uses ``B -> T``, 3 hops

    Whatever supports ``B -> T`` is one fact. Reaching B a second way does not make it
    two.
    """
    return _store(("A", "B", 1.0), ("B", "T", 0.5), ("A", "C", 1.0), ("C", "B", 1.0))


def test_paths_sharing_an_edge_do_not_corroborate() -> None:
    link = _link(_shared_edge_store(), "A", "T", hops=3)

    # 0.75 was the old answer: noisy-OR over 0.5 and 0.5 as though they were two findings.
    assert link.confidence == pytest.approx(0.5)


def test_reaching_further_never_inflates_a_nearer_target() -> None:
    """Raising `max_hops` admits longer routes; it must not raise an existing answer.

    This is the caller-visible shape of the bug: the same graph and the same question
    returned a *more* confident answer purely because the search was allowed to wander.
    """
    store = _shared_edge_store()

    near = _link(store, "A", "T", hops=2)
    far = _link(store, "A", "T", hops=3)

    assert far.confidence == pytest.approx(near.confidence)
    assert far.hops == near.hops


# --- the feature that must survive ---------------------------------------------------------


def test_edge_disjoint_paths_still_corroborate() -> None:
    """The guard against over-correcting: real corroboration is the point of the aggregation.

    Mirrors `test_multiple_paths_corroborate_confidence`, stated here as the explicit
    counterpart to the shared-edge case so the two sit side by side.
    """
    store = _store(("A", "B", 0.5), ("A", "C", 0.5), ("B", "D", 0.5), ("C", "D", 0.5))

    link = _link(store, "A", "D", hops=2)

    # Two disjoint 2-hop routes at 0.25 each: 1 - (1-0.25)^2.
    assert link.confidence == pytest.approx(0.4375)
    assert link.independent_paths == 2


def test_a_single_route_keeps_its_confidence_exactly() -> None:
    """The ordinary case has no aggregation to do, and must be left alone."""
    link = _link(_store(("A", "B", 0.6), ("B", "T", 0.5)), "A", "T", hops=2)

    assert link.confidence == pytest.approx(0.3)
    assert link.independent_paths == 1


# --- a mixed graph: exclude the redundant route, keep the genuine one ----------------------


def test_only_the_disjoint_alternative_is_admitted() -> None:
    """Three routes to T. One is a detour over an already-counted edge; one is genuine.

        A -> X (1.0) -> T (0.5)              strongest, 0.5
        A -> Y (1.0) -> X (1.0) -> T         0.5, but re-uses ``X -> T``
        A -> Z (1.0) -> T (0.25)             0.25, shares nothing

    The strongest route is taken first, the detour is refused for sharing ``X -> T``, and
    the independent weaker route is admitted: 1 - (1-0.5)(1-0.25).
    """
    store = _store(
        ("A", "X", 1.0),
        ("X", "T", 0.5),
        ("A", "Y", 1.0),
        ("Y", "X", 1.0),
        ("A", "Z", 1.0),
        ("Z", "T", 0.25),
    )

    link = _link(store, "A", "T", hops=3)

    assert link.confidence == pytest.approx(0.625)
    assert link.independent_paths == 2


def test_the_strongest_route_is_the_one_kept() -> None:
    """When two routes conflict over a shared edge, the weaker one is the one dropped.

    Both reach T through ``X -> T``; keeping the 0.9 route rather than the 0.2 route is
    what makes the selection a lower bound on the evidence rather than an arbitrary one.
    """
    store = _store(("A", "X", 0.9), ("A", "Y", 0.2), ("Y", "X", 1.0), ("X", "T", 1.0))

    link = _link(store, "A", "T", hops=3)

    assert link.confidence == pytest.approx(0.9)
    assert link.independent_paths == 1


# --- the audit trail ------------------------------------------------------------------------


def test_the_count_distinguishes_a_boost_from_a_single_reading() -> None:
    """The number alone cannot be checked; the count is what makes it checkable.

    0.5 from one route and 0.5 from two routes that happened to overlap are the same
    number. Without `independent_paths` a reader cannot tell which they were handed, and
    `path` shows only the shortest route either way.
    """
    shared = _link(_shared_edge_store(), "A", "T", hops=3)
    alone = _link(_store(("A", "B", 1.0), ("B", "T", 0.5)), "A", "T", hops=2)

    assert shared.confidence == pytest.approx(alone.confidence)
    assert shared.independent_paths == alone.independent_paths == 1


def test_independent_paths_is_never_zero_for_a_reached_target() -> None:
    """A target appears in the reach because something reached it."""
    store = _store(("A", "B", 0.5), ("A", "C", 0.5), ("B", "D", 0.5), ("C", "D", 0.5))

    result = explain(store, "protein:A", max_hops=2)

    assert result.links
    assert all(link.independent_paths >= 1 for link in result.links)
