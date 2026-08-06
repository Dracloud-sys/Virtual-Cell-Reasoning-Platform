"""Domain-independent mechanistic grounding (PR14a).

Turning seed entities into an evidence-graded mechanistic chain is the same procedure in
every vertical: walk outward from each seed, keep the links the domain admits, drop
duplicates, and order the result so a reader sees the strongest, closest reasoning first.
What differs between verticals is only *which links are admissible* — and that is a
statement about biology, which belongs to a pack.

Before this module the procedure existed twice inside the immortalization vertical, once
for mechanism questions and once for hypothesis questions, identical apart from the
admission test. Two copies of a traversal that decides what enters a decision report is
two places for the ordering, the deduplication or the missing-seed check to drift, and a
second domain would have made a third.

A pack supplies an :class:`LinkAdmission` — a predicate over one candidate link. The
combinators below cover the cases the existing verticals need, and a pack is free to pass
any callable instead.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Final

from virtualcell.knowledge.schema import RelationType
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.reasoning.explain import MechanisticLink, explain

LinkAdmission = Callable[[MechanisticLink], bool]
"""Domain policy: may this link enter a decision report?"""

DEFAULT_MAX_HOPS: Final = 2
"""How far grounding walks. Two hops keeps a chain readable and its tier meaningful;
beyond that ``explain`` already grades a path as speculative."""


def rendered_step(relation: RelationType | str) -> str:
    """The ``-relation->`` token :func:`explain` writes into a path.

    Derived from the relation vocabulary rather than spelled out, so a renamed relation
    cannot leave a policy silently matching nothing.
    """
    value = relation.value if isinstance(relation, RelationType) else relation
    return f"-{value}->"


WEAK_RELATIONS: Final[tuple[RelationType, ...]] = (
    RelationType.ASSOCIATED_WITH,
    RelationType.SUGGESTS,
    RelationType.SUGGESTS_NEXT_TEST,
)
"""Relations that carry no causal claim. A path through one is a suggestion, not a
mechanism, and :mod:`virtualcell.reasoning.explain` already caps its tier accordingly."""

WEAK_STEPS: Final[tuple[str, ...]] = tuple(rendered_step(r) for r in WEAK_RELATIONS)


class GroundingError(ValueError):
    """Raised when a policy names a seed entity the store does not contain.

    An absent seed is a broken policy, not an empty result: silently grounding nothing
    would present a report with no mechanistic chain as though the graph had been
    consulted and found nothing to say.
    """


def targets_in(allowed: Iterable[str]) -> LinkAdmission:
    """Admit only links reaching one of ``allowed``.

    Without a target allowlist a chain fills with whatever else the graph happens to
    reach — next-test suggestions, unrelated phenotypes — and a reader cannot tell the
    reasoning from the surroundings.
    """
    permitted = frozenset(allowed)
    return lambda link: link.target_id in permitted


def excludes_weak_relations() -> LinkAdmission:
    """Admit only links whose every step is a causal relation.

    For a *mechanism* claim this is the difference between "A promotes B" and "A has been
    seen alongside B". Both are real; only one is a mechanism.
    """

    def admits(link: MechanisticLink) -> bool:
        joined = " ".join(link.path)
        return not any(step in joined for step in WEAK_STEPS)

    return admits


def all_of(*admissions: LinkAdmission) -> LinkAdmission:
    """Admit a link only if every policy admits it."""
    return lambda link: all(admits(link) for admits in admissions)


def ground_links(
    store: KnowledgeStore,
    seed_ids: Sequence[str],
    admits: LinkAdmission,
    *,
    max_hops: int = DEFAULT_MAX_HOPS,
) -> list[MechanisticLink]:
    """Walk outward from each seed and return the links the domain admits.

    Deterministic in three ways that a decision report depends on:

    * **seed order first** in the result, so every seed's arm surfaces rather than one
      seed's shorter paths crowding another's out entirely;
    * then **fewer hops first**, because a closer path is the stronger explanation;
    * then **target id**, so two equally close links never swap places between runs.

    Duplicate ``(target, path)`` pairs are dropped: the same reasoning reached twice from
    different seeds is one piece of reasoning, and listing it twice would read as
    corroboration it is not.

    Raises :class:`GroundingError` if a seed is absent from the store.
    """
    selected: list[tuple[int, MechanisticLink]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for order, seed_id in enumerate(seed_ids):
        if store.get(seed_id) is None:
            raise GroundingError(f"rule seed entity not in store: {seed_id}")
        for link in explain(store, seed_id, max_hops=max_hops).links:
            if not admits(link):
                continue
            key = (link.target_id, tuple(link.path))
            if key in seen:
                continue
            seen.add(key)
            selected.append((order, link))
    selected.sort(key=lambda item: (item[0], item[1].hops, item[1].target_id))
    return [link for _, link in selected]
