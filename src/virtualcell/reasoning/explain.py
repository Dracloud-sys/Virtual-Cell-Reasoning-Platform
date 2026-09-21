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
  is boosted when several **edge-disjoint** paths corroborate the same target
  (:func:`~virtualcell.core.confidence.combine_confidences`), together with
  ``independent_paths`` — how many routes that boost actually rests on.

  Independence is enforced rather than assumed. The noisy-OR aggregation is only
  meaningful for independent evidence, and every path used to be fed to it, so a
  detour that re-entered an already-counted edge read as a second opinion: two
  routes ending on one ``B -> T`` edge lifted 0.50 to 0.75. Paths are now admitted
  strongest-first and only while they share neither an **edge** nor a **study** with
  an admitted one, which can never count one fact twice. It is a *lower bound* on
  corroboration — a greedy choice, not a maximum independent set — and under-counting
  is the safe direction,
* the **provenance** of the reported path, which is what makes the number checkable.

Edge-disjointness alone was a proxy for independence: two distinct edges read out of
one paper are still one reading. ``Edge`` now carries the provenance of the
``Interaction`` it came from, so the traversal can see this. Only ``study_id`` — one
document — constrains independence; the free-form ``evidence`` strings are a mixture of
database names and curation tags that every edge from a connector shares, and treating
those as shared evidence would collapse the curated graph into a single fact.

What is *not* yet graded by provenance is the tier. A curated edge and a weak
literature association at the same distance are still graded identically, because
grading a source is an editorial judgement rather than a traversal property. That gap
is recorded in ``docs/evidence_provenance_findings.md`` and pinned by a test.

This is the platform's core primitive: turning a static graph into ranked,
auditable mechanistic hypotheses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

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
    #: How many edge-disjoint routes the confidence rests on. ``1`` means no
    #: corroboration: the value is one path's own product, not an aggregate. Reported
    #: because ``path`` shows only the shortest route, so the number is otherwise
    #: unauditable — 0.5 from one reading and 0.5 from two overlapping ones look alike.
    independent_paths: int = Field(default=1, ge=1)
    #: The distinct provenance strings behind the edges of ``path``, sorted and
    #: de-duplicated: database names, curation tags, article keys, review state. Empty
    #: when nothing was recorded, never a placeholder. This is the reported route's
    #: support, not the whole target's — ``path`` shows one route and so does this.
    provenance: list[str] = Field(default_factory=list)


class Explanation(BaseModel):
    """The ranked mechanistic reach of a seed entity."""

    seed_id: str
    seed_name: str
    max_hops: int
    links: list[MechanisticLink] = Field(default_factory=list)


#: One traversed edge, identified by endpoints and relation rather than by the readable
#: chain. Two steps between the same pair under the same relation are the same fact; the
#: rendered string would also collide for two entities that happen to share a name.
_EdgeKey = tuple[str, str, str]


class _Step(NamedTuple):
    """One frontier entry: a partial path, and everything needed to judge it later.

    ``chain`` is for the reader. ``edges`` and ``studies`` are what decide whether two
    completed paths are independent evidence; ``provenance`` is the audit trail that
    travels out with the answer.
    """

    node: str
    confidence: float
    chain: list[str]
    visited: frozenset[str]
    ceiling: EvidenceTier
    edges: frozenset[_EdgeKey]
    studies: frozenset[str]
    provenance: frozenset[str]


class _Path(NamedTuple):
    """A completed route to one target, reduced to what independence turns on."""

    confidence: float
    edges: frozenset[_EdgeKey]
    studies: frozenset[str]


@dataclass
class _Reach:
    """Accumulator for one reached target across all discovered paths.

    Keeps each path's confidence *with the edges and studies it used*, because whether
    two paths corroborate is a question about their support, not about their scores.
    """

    #: One entry per discovered path, in discovery order.
    paths: list[_Path] = field(default_factory=list)
    best_hops: int = 10**9
    best_conf: float = -1.0
    best_path: list[str] = field(default_factory=list)
    best_ceiling: EvidenceTier = EvidenceTier.ESTABLISHED
    best_provenance: frozenset[str] = frozenset()

    def record(self, hops: int, step: _Step) -> None:
        self.paths.append(_Path(step.confidence, step.edges, step.studies))
        if hops < self.best_hops or (hops == self.best_hops and step.confidence > self.best_conf):
            self.best_hops = hops
            self.best_conf = step.confidence
            self.best_path = step.chain
            self.best_ceiling = step.ceiling
            self.best_provenance = step.provenance

    def independent(self) -> list[float]:
        """The confidences of a mutually independent subset of paths, strongest first.

        Greedy: take the strongest path, then every next-strongest path that shares
        neither an **edge** nor a **study** with one already taken. Edge-disjointness
        alone was a proxy — two distinct edges read out of one paper are one finding, and
        a path whose study is already counted adds nothing. An edge with no recorded
        study contributes no constraint, so unattributed and curated graphs behave exactly
        as they did when edges were the only test.

        A maximum independent set would need a flow computation and could only ever admit
        *more* paths, so the greedy answer is a floor on corroboration — the direction
        that cannot overstate the evidence.

        Ties are broken by path length and then by the sorted keys so the result does not
        depend on the order the traversal happened to discover paths in.
        """
        chosen: list[float] = []
        used_edges: set[_EdgeKey] = set()
        used_studies: set[str] = set()
        for path in sorted(
            self.paths,
            key=lambda p: (-p.confidence, len(p.edges), sorted(p.edges), sorted(p.studies)),
        ):
            if path.edges & used_edges or path.studies & used_studies:
                continue
            chosen.append(path.confidence)
            used_edges |= path.edges
            used_studies |= path.studies
        return chosen


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
    established = EvidenceTier.ESTABLISHED
    frontier: list[_Step] = [
        _Step(
            node=seed_id,
            confidence=1.0,
            chain=[],
            visited=frozenset({seed_id}),
            ceiling=established,
            edges=frozenset(),
            studies=frozenset(),
            provenance=frozenset(),
        )
    ]

    for hop in range(1, max_hops + 1):
        next_frontier: list[_Step] = []
        for current in frontier:
            for edge in store.edges(current.node, direction=direction):
                target = edge.target_id
                if target in current.visited:  # no cycles within a single path
                    continue
                rendered = f"{name_of(current.node)} -{edge.relation}-> {name_of(target)}"
                step = _Step(
                    node=target,
                    confidence=current.confidence * edge.confidence,
                    chain=[*current.chain, rendered],
                    visited=current.visited | {target},
                    ceiling=_weaker_of(
                        current.ceiling, _WEAK_RELATION_CEILING.get(edge.relation, established)
                    ),
                    edges=current.edges | {(current.node, edge.relation, target)},
                    # An edge with no recorded study adds no study, rather than a shared
                    # "unknown" that would make every unattributed path dependent.
                    studies=(
                        current.studies
                        if edge.study_id is None
                        else current.studies | {edge.study_id}
                    ),
                    provenance=current.provenance | frozenset(edge.evidence),
                )
                reached.setdefault(target, _Reach()).record(hop, step)
                next_frontier.append(step)
        # Bound growth: keep only the most-confident frontier entries for the next hop.
        next_frontier.sort(key=lambda entry: entry.confidence, reverse=True)
        frontier = next_frontier[:_MAX_FRONTIER]

    links = []
    for target_id, reach in reached.items():
        independent = reach.independent()
        links.append(
            MechanisticLink(
                target_id=target_id,
                target_name=name_of(target_id),
                hops=reach.best_hops,
                tier=_weaker_of(_tier_for_hops(reach.best_hops), reach.best_ceiling),
                confidence=combine_confidences(independent),
                path=reach.best_path,
                independent_paths=len(independent),
                provenance=sorted(reach.best_provenance),
            )
        )
    # Rank by confidence, then closeness, then id for stable ordering.
    links.sort(key=lambda link: (-link.confidence, link.hops, link.target_id))

    return Explanation(
        seed_id=seed_id,
        seed_name=seed.name,
        max_hops=max_hops,
        links=links[:top_k],
    )
