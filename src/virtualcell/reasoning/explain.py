"""Evidence-graded multi-hop mechanistic reasoning.

Given a seed entity, :func:`explain` traverses the knowledge graph outward and
reports which entities are mechanistically reachable, each with:

* the **path** taken (the "why"),
* an **evidence tier** that honestly reflects both inference distance and edge
  strength — a direct curated edge is ``established``, a 2-hop inference is at most
  ``hypothesis`` and 3+ hops ``speculative``, *and* any path through a weak
  relation (``ASSOCIATED_WITH`` / ``SUGGESTS`` / ``SUGGESTS_NEXT_TEST``) is capped
  at ``hypothesis`` no matter how few hops. Relation type stays independent of
  tier; a multi-hop or weak inference is never presented as an established fact,
* a **confidence** that decays with path length (product of edge confidences) and
  is boosted when several independent paths corroborate the same target
  (:func:`~virtualcell.core.confidence.combine_confidences`).

This is the platform's core primitive: turning a static graph into ranked,
auditable mechanistic hypotheses.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from virtualcell.core.confidence import combine_confidences
from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.schema import RelationType
from virtualcell.knowledge.store import KnowledgeStore

# Bounds that keep traversal tractable on large real graphs (e.g. Reactome).
_DEFAULT_MAX_HOPS = 2
_MAX_ALLOWED_HOPS = 4
_MAX_FRONTIER = 2000

# Relations whose epistemic strength is inherently weak: a path through one of
# these can be at most a hypothesis, regardless of hop count. Relation type stays
# independent of tier; strong relations impose no ceiling (i.e. ``established``).
_WEAK_RELATION_CEILING: dict[str, EvidenceTier] = {
    RelationType.ASSOCIATED_WITH.value: EvidenceTier.HYPOTHESIS,
    RelationType.SUGGESTS.value: EvidenceTier.HYPOTHESIS,
    RelationType.SUGGESTS_NEXT_TEST.value: EvidenceTier.HYPOTHESIS,
}


def _weaker_of(a: EvidenceTier, b: EvidenceTier) -> EvidenceTier:
    """Return the weaker (lower-rank) of two tiers."""
    return a if a.rank <= b.rank else b


def _tier_for_hops(hops: int) -> EvidenceTier:
    """Downgrade the epistemic tier as inference distance grows."""
    if hops <= 1:
        return EvidenceTier.ESTABLISHED
    if hops == 2:
        return EvidenceTier.HYPOTHESIS
    return EvidenceTier.SPECULATIVE


class MechanisticLink(BaseModel):
    """One reachable entity and how strongly/why it is implicated."""

    target_id: str
    target_name: str
    hops: int
    tier: EvidenceTier
    confidence: float = Field(ge=0.0, le=1.0)
    path: list[str] = Field(default_factory=list)


class Explanation(BaseModel):
    """The ranked mechanistic reach of a seed entity."""

    seed_id: str
    seed_name: str
    max_hops: int
    links: list[MechanisticLink] = Field(default_factory=list)


@dataclass
class _Reach:
    """Accumulator for one reached target across all discovered paths."""

    confidences: list[float] = field(default_factory=list)
    best_hops: int = 10**9
    best_conf: float = -1.0
    best_path: list[str] = field(default_factory=list)
    best_ceiling: EvidenceTier = EvidenceTier.ESTABLISHED

    def record(self, hops: int, conf: float, path: list[str], ceiling: EvidenceTier) -> None:
        self.confidences.append(conf)
        if hops < self.best_hops or (hops == self.best_hops and conf > self.best_conf):
            self.best_hops = hops
            self.best_conf = conf
            self.best_path = path
            self.best_ceiling = ceiling


def explain(
    store: KnowledgeStore,
    seed_id: str,
    max_hops: int = _DEFAULT_MAX_HOPS,
    top_k: int = 25,
    direction: str = "forward",
) -> Explanation:
    """Return the ranked, evidence-graded mechanistic reach of ``seed_id``.

    ``direction`` defaults to ``"forward"`` so traversal follows biological arrows
    (a causal/downstream reach); pass ``"any"`` for undirected graph reachability.
    """
    seed = store.get(seed_id)
    if seed is None:
        raise ValueError(f"entity not found: {seed_id}")
    max_hops = max(1, min(max_hops, _MAX_ALLOWED_HOPS))

    names: dict[str, str] = {seed_id: seed.name}

    def name_of(entity_id: str) -> str:
        if entity_id not in names:
            entity = store.get(entity_id)
            names[entity_id] = entity.name if entity is not None else entity_id
        return names[entity_id]

    reached: dict[str, _Reach] = {}
    # Frontier entries: (current_id, path_confidence, readable_chain, visited_ids, ceiling)
    established = EvidenceTier.ESTABLISHED
    frontier: list[tuple[str, float, list[str], frozenset[str], EvidenceTier]] = [
        (seed_id, 1.0, [], frozenset({seed_id}), established)
    ]

    for hop in range(1, max_hops + 1):
        next_frontier: list[tuple[str, float, list[str], frozenset[str], EvidenceTier]] = []
        for current, conf, chain, visited, ceiling in frontier:
            for edge in store.edges(current, direction=direction):
                target = edge.target_id
                if target in visited:  # no cycles within a single path
                    continue
                new_conf = conf * edge.confidence
                new_ceiling = _weaker_of(
                    ceiling, _WEAK_RELATION_CEILING.get(edge.relation, established)
                )
                step = f"{name_of(current)} -{edge.relation}-> {name_of(target)}"
                new_chain = [*chain, step]
                reached.setdefault(target, _Reach()).record(hop, new_conf, new_chain, new_ceiling)
                next_frontier.append((target, new_conf, new_chain, visited | {target}, new_ceiling))
        # Bound growth: keep only the most-confident frontier entries for the next hop.
        next_frontier.sort(key=lambda entry: entry[1], reverse=True)
        frontier = next_frontier[:_MAX_FRONTIER]

    links = [
        MechanisticLink(
            target_id=target_id,
            target_name=name_of(target_id),
            hops=reach.best_hops,
            tier=_weaker_of(_tier_for_hops(reach.best_hops), reach.best_ceiling),
            confidence=combine_confidences(reach.confidences),
            path=reach.best_path,
        )
        for target_id, reach in reached.items()
    ]
    # Rank by confidence, then closeness, then id for stable ordering.
    links.sort(key=lambda link: (-link.confidence, link.hops, link.target_id))

    return Explanation(
        seed_id=seed_id,
        seed_name=seed.name,
        max_hops=max_hops,
        links=links[:top_k],
    )
