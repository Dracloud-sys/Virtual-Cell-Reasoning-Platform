"""Provenance has to survive the traversal boundary, and independence has to use it.

PR #30 made corroboration require **edge-disjoint** paths. Its own recorded limit was that
edge-disjointness is a *proxy* for independence: two distinct edges read out of the same
paper are still one reading, and nothing could detect that because ``Interaction`` carries
provenance and the traversal ``Edge`` in ``knowledge/store.py`` did not. Provenance was
stored and then dropped one layer below the reasoning that needed it.

Closing that gap is not a mechanical field pass-through, and these questions say why. The
provenance strings the connectors write today are two different kinds of thing wearing one
type:

* **source-level** — ``curated:immortalization_seed``, ``reactome:IEA``, ``intact``,
  ``uniprot``, ``review_status:pending_review``. Every edge from one connector carries the
  same token. Treating a shared token as shared evidence would collapse the entire curated
  graph into a single fact and delete corroboration everywhere.
* **study-level** — ``article:<key>``, ``run:<id>``, ``source_hash:<...>``. These identify
  one document, and two facts read from one document are not two findings.

So the discriminator cannot be a string heuristic applied downstream; a connector that
invents a new prefix would silently opt out of the rule, which is the same class of defect
as the one being fixed. Provenance becomes **typed at the point it is created**:
``Interaction.study_id`` names the single study an edge was read from, or is ``None`` when
no single study backs it — which is the honest answer for a curated seed table.

The rule these questions pin: **paths corroborate only when they share neither an edge nor
a study**, ``None`` imposes no constraint (so the curated graph is untouched), and the
provenance of the reported path travels with the answer.

Written against hand-built graphs, before the implementation, for the reason the sibling
file gives: a seed graph's topology is biology and may change; these are properties of the
traversal and must hold for any graph at all.
"""

from __future__ import annotations

import pytest

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import Interaction, Protein, RelationType
from virtualcell.reasoning.explain import explain

#: One edge: source, target, confidence, provenance strings, and the study it was read
#: from (``None`` when no single study backs it).
_Edge = tuple[str, str, float, list[str], str | None]


def _store(*edges: _Edge) -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    for name in {end for src, dst, _c, _e, _s in edges for end in (src, dst)}:
        store.upsert(Protein(id=f"protein:{name}", name=name))
    for src, dst, confidence, evidence, study in edges:
        store.add_interaction(
            Interaction(
                source_id=f"protein:{src}",
                target_id=f"protein:{dst}",
                relation=RelationType.PROMOTES,
                confidence=confidence,
                evidence=evidence,
                study_id=study,
            )
        )
    return store


def _link(store: InMemoryKnowledgeStore, seed: str, target: str, hops: int = 2):
    result = explain(store, f"protein:{seed}", max_hops=hops)
    return next(link for link in result.links if link.target_id == f"protein:{target}")


# --- the boundary itself ---------------------------------------------------------------


def test_the_traversal_edge_carries_the_provenance_it_was_built_from() -> None:
    """The gap PR #30 recorded: an `Edge` that has forgotten where its fact came from.

    Nothing above the store can reason about provenance it is never handed, so this is
    the precondition for every other question here.
    """
    store = _store(("A", "B", 0.9, ["article:one", "reactome:IEA"], "article:one"))

    edge = next(e for e in store.edges("protein:A") if e.target_id == "protein:B")

    assert edge.evidence == ["article:one", "reactome:IEA"]
    assert edge.study_id == "article:one"


def test_an_edge_with_no_recorded_study_says_so_rather_than_guessing() -> None:
    """A curated seed row is not a study, and must not be given a synthetic one."""
    store = _store(("A", "B", 0.9, ["curated:immortalization_seed"], None))

    edge = next(e for e in store.edges("protein:A") if e.target_id == "protein:B")

    assert edge.evidence == ["curated:immortalization_seed"]
    assert edge.study_id is None


# --- the defect: edge-disjoint is not independent -----------------------------------------


def test_edge_disjoint_paths_from_one_study_do_not_corroborate() -> None:
    """Two routes, no shared edge, one paper.

        A -> B (0.5) -> D (0.5)     both edges read from article:one
        A -> C (0.5) -> D (0.5)     both edges read from article:one

    Edge-disjointness is satisfied and independence is not. One paper reporting a thing
    twice is one reading; noisy-OR over 0.25 and 0.25 claims it is two.
    """
    one = ["article:one"]
    link = _link(
        _store(
            ("A", "B", 0.5, one, "article:one"),
            ("B", "D", 0.5, one, "article:one"),
            ("A", "C", 0.5, one, "article:one"),
            ("C", "D", 0.5, one, "article:one"),
        ),
        "A",
        "D",
    )

    # 0.4375 was the old answer: 1 - (1-0.25)^2, as though the paper were two papers.
    assert link.confidence == pytest.approx(0.25)
    assert link.independent_paths == 1


def test_paths_from_different_studies_corroborate() -> None:
    """The guard against over-correcting. Two papers agreeing is the whole point.

    Also pins that a study repeated *within* one path is not self-defeating: each route
    here is two edges from the same article, and the route is still one piece of evidence
    rather than zero.
    """
    link = _link(
        _store(
            ("A", "B", 0.5, ["article:one"], "article:one"),
            ("B", "D", 0.5, ["article:one"], "article:one"),
            ("A", "C", 0.5, ["article:two"], "article:two"),
            ("C", "D", 0.5, ["article:two"], "article:two"),
        ),
        "A",
        "D",
    )

    assert link.confidence == pytest.approx(0.4375)
    assert link.independent_paths == 2


def test_sharing_only_a_database_name_is_not_sharing_a_study() -> None:
    """The failure mode a string heuristic would cause, stated as a question.

    Every Reactome edge carries ``reactome:IEA``; every immortalization seed edge carries
    ``curated:immortalization_seed``. If a shared provenance *string* meant shared
    evidence, the curated graph would corroborate nothing with anything, and every
    scorecard would move. A source is not a study.
    """
    reactome = ["reactome:IEA"]
    link = _link(
        _store(
            ("A", "B", 0.5, reactome, None),
            ("B", "D", 0.5, reactome, None),
            ("A", "C", 0.5, reactome, None),
            ("C", "D", 0.5, reactome, None),
        ),
        "A",
        "D",
    )

    assert link.confidence == pytest.approx(0.4375)
    assert link.independent_paths == 2


def test_an_unattributed_path_neither_gains_nor_loses_corroboration() -> None:
    """``None`` is not a study that every unattributed edge shares.

    Two routes with no recorded provenance at all behave exactly as they did before this
    change: edge-disjointness remains the only test that applies to them.
    """
    link = _link(
        _store(
            ("A", "B", 0.5, [], None),
            ("B", "D", 0.5, [], None),
            ("A", "C", 0.5, [], None),
            ("C", "D", 0.5, [], None),
        ),
        "A",
        "D",
    )

    assert link.confidence == pytest.approx(0.4375)
    assert link.independent_paths == 2


# --- a mixed graph: one study's second route is the one dropped ---------------------------


def test_the_strongest_route_per_study_is_the_one_kept() -> None:
    """Three edge-disjoint routes to T, from two papers.

        A -> X (1.0) -> T (0.50)    article:one   -> 0.50
        A -> Y (1.0) -> T (0.40)    article:one   -> 0.40
        A -> Z (1.0) -> T (0.25)    article:two   -> 0.25

    Strongest first: 0.50 is admitted, 0.40 is refused for repeating article:one, and
    0.25 is admitted as a genuinely second source. 1 - (1-0.5)(1-0.25).
    """
    one, two = ["article:one"], ["article:two"]
    link = _link(
        _store(
            ("A", "X", 1.0, one, "article:one"),
            ("X", "T", 0.5, one, "article:one"),
            ("A", "Y", 1.0, one, "article:one"),
            ("Y", "T", 0.4, one, "article:one"),
            ("A", "Z", 1.0, two, "article:two"),
            ("Z", "T", 0.25, two, "article:two"),
        ),
        "A",
        "T",
    )

    # 0.775 was the old answer: 1 - (1-0.5)(1-0.4)(1-0.25), three readings from two papers.
    assert link.confidence == pytest.approx(0.625)
    assert link.independent_paths == 2


def test_a_shared_edge_is_still_refused_when_no_study_is_recorded() -> None:
    """PR #30's rule is added to, not replaced. Both tests must hold at once."""
    link = _link(
        _store(
            ("A", "B", 1.0, [], None),
            ("B", "T", 0.5, [], None),
            ("A", "C", 1.0, [], None),
            ("C", "B", 1.0, [], None),
        ),
        "A",
        "T",
        hops=3,
    )

    assert link.confidence == pytest.approx(0.5)
    assert link.independent_paths == 1


# --- the audit trail ------------------------------------------------------------------------


def test_the_reported_link_carries_the_provenance_of_the_path_it_reports() -> None:
    """A confidence a reader cannot trace to its support is the defect, not the number.

    ``path`` says which route was taken; ``provenance`` says what that route rests on.
    """
    link = _link(
        _store(
            ("A", "B", 0.9, ["curated:seed"], None),
            ("B", "T", 0.8, ["article:one", "run:r1"], "article:one"),
        ),
        "A",
        "T",
    )

    assert link.provenance == ["article:one", "curated:seed", "run:r1"]


def test_provenance_is_deduplicated_rather_than_repeated_per_edge() -> None:
    """Two edges from one paper cite it once; a repeated token reads as a second source."""
    one = ["article:one"]
    link = _link(
        _store(
            ("A", "B", 0.9, one, "article:one"),
            ("B", "T", 0.8, one, "article:one"),
        ),
        "A",
        "T",
    )

    assert link.provenance == ["article:one"]


def test_an_unattributed_path_reports_no_provenance_rather_than_a_placeholder() -> None:
    link = _link(_store(("A", "B", 0.9, [], None), ("B", "T", 0.8, [], None)), "A", "T")

    assert link.provenance == []


# --- a recorded finding, pinned -------------------------------------------------------------


def test_evidence_tier_is_still_derived_from_shape_alone_not_from_provenance() -> None:
    """The half of the gap this change does **not** close, pinned so it cannot be forgotten.

    ``Edge`` now carries provenance, but the tier a link is given still comes only from
    hop count and relation strength: a hand-curated edge and a weak literature association
    at the same distance are graded identically. Grading a source is a biological and
    editorial judgement — is a Reactome ``IEA`` inference ``established`` or
    ``hypothesis``? — and this repository's rule is that such a judgement is a stop
    condition for an unattended change, recorded in
    ``docs/evidence_provenance_findings.md`` rather than invented here.

    This test asserts the gap, so closing it will fail loudly and deliberately.
    """
    curated = _link(_store(("A", "B", 0.9, ["curated:seed"], None)), "A", "B", hops=1)
    literature = _link(
        _store(("A", "B", 0.9, ["review_status:pending_review"], "article:one")),
        "A",
        "B",
        hops=1,
    )

    assert curated.tier is literature.tier
