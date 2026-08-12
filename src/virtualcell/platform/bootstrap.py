"""Composition root for the platform boundary (PR11).

The **one** place a shipped domain is declared. Interfaces (API, CLI, services) resolve
domains through the registry and never name a vertical themselves, so adding a domain is a
change here and nowhere else.

Being addressable and having a graph to reason over are two different things, and for a
while they were declared in two different places: a pack list and a seed map. That is a
drift waiting to happen, in both directions — a pack registered without a seed dispatches
correctly and then grounds nothing, and a seed registered without a pack loads a graph no
query can reach. Neither would fail loudly, and both would look fine in review.

So a domain is declared **once**, as a :class:`ShippedDomain` naming both halves, and
everything else is derived from that single tuple: the registry, the per-domain seeding, and
the bulk seeding. There is no second list to keep in step, because there is no second list.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from virtualcell.knowledge.sources.adipogenesis_seed import AdipogenesisSeedSource
from virtualcell.knowledge.sources.base import DataSource, load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.platform.domains import DomainPack, DomainRegistry
from virtualcell.platform.packs.adipogenesis import AdipogenesisDomainPack
from virtualcell.platform.packs.immortalization import ImmortalizationDomainPack


@dataclass(frozen=True)
class ShippedDomain:
    """One domain the platform ships: how to reason in it, and what to reason over.

    Both halves are named together because shipping one without the other is never
    intentional. The pack class is stored rather than an instance so each registry gets its
    own, and the seed source class for the same reason.
    """

    pack: type[DomainPack]
    seed_source: type[DataSource]

    @property
    def name(self) -> str:
        """The domain key, taken from the pack itself.

        Never spelled out again beside the declaration: a hand-written key is one more
        thing that can disagree with what the pack actually answers to.
        """
        return self.pack.domain


SHIPPED_DOMAINS: tuple[ShippedDomain, ...] = (
    ShippedDomain(ImmortalizationDomainPack, ImmortalizationSeedSource),
    ShippedDomain(AdipogenesisDomainPack, AdipogenesisSeedSource),
)


def _unique_names(domains: Sequence[ShippedDomain]) -> tuple[str, ...]:
    """The declared domain names, refusing duplicates.

    Two declarations claiming one domain is a composition bug, and the quiet outcome —
    whichever came last wins — is the bad one: queries would be answered by a pack nobody
    chose, using a graph seeded from the other declaration.
    """
    names = tuple(shipped.name for shipped in domains)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"domain declared more than once: {', '.join(duplicates)}")
    return names


# Checked at import: a composition root that contradicts itself should never get as far as
# building a registry.
_unique_names(SHIPPED_DOMAINS)


def shipped_domain_names(
    domains: Sequence[ShippedDomain] = SHIPPED_DOMAINS,
) -> tuple[str, ...]:
    """Every shipped domain's name, in declaration order."""
    return tuple(shipped.name for shipped in domains)


def shipped_domain(name: str, domains: Sequence[ShippedDomain] = SHIPPED_DOMAINS) -> ShippedDomain:
    """The declaration for ``name``. Raises ``KeyError`` if the platform does not ship it."""
    for shipped in domains:
        if shipped.name == name:
            return shipped
    raise KeyError(name)


def default_registry(domains: Sequence[ShippedDomain] = SHIPPED_DOMAINS) -> DomainRegistry:
    """A registry with every shipped domain pack registered.

    A fresh registry and fresh pack instances on every call, so callers and tests cannot
    leak state into one another.
    """
    _unique_names(domains)
    registry = DomainRegistry()
    for shipped in domains:
        registry.register(shipped.pack())
    return registry


def seed_domain(
    name: str,
    store: KnowledgeStore,
    domains: Sequence[ShippedDomain] = SHIPPED_DOMAINS,
) -> tuple[int, int]:
    """Load one shipped domain's curated graph. Raises ``KeyError`` for an unknown name."""
    return load_into(shipped_domain(name, domains).seed_source(), store)


def seed_registered_domains(
    store: KnowledgeStore, domains: Sequence[ShippedDomain] = SHIPPED_DOMAINS
) -> tuple[int, int]:
    """Load every shipped domain's curated graph into ``store``."""
    entities = interactions = 0
    for shipped in domains:
        added_entities, added_interactions = load_into(shipped.seed_source(), store)
        entities += added_entities
        interactions += added_interactions
    return entities, interactions
