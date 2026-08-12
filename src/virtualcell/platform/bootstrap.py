"""Composition root for the platform boundary (PR11).

The **one** place domain packs are registered. Interfaces (API, CLI, services) resolve
domains through the registry and never name a vertical themselves, so adding a domain is
a change here and nowhere else.

Adipogenesis was registered here as the second domain, and the claim held: **one line**,
with no API route, CLI command, request contract or service change. It is addressable as
``{"domain": "adipogenesis", "task": ...}`` through every existing interface.
"""

from __future__ import annotations

from virtualcell.knowledge.sources.adipogenesis_seed import AdipogenesisSeedSource
from virtualcell.knowledge.sources.base import DataSource, load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.platform.domains import DomainRegistry
from virtualcell.platform.packs.adipogenesis import AdipogenesisDomainPack
from virtualcell.platform.packs.immortalization import ImmortalizationDomainPack


def default_registry() -> DomainRegistry:
    """A registry with every shipped domain pack registered."""
    registry = DomainRegistry()
    registry.register(ImmortalizationDomainPack())
    registry.register(AdipogenesisDomainPack())
    return registry


# Registering a pack makes a domain *addressable*; it does not put the graph that domain
# reasons over into the store. Interfaces used to seed one vertical by name, which meant a
# second domain dispatched correctly and then grounded nothing. Which curated graphs ship
# is a composition decision, so it lives here beside the registry rather than in each
# interface — and no interface names a vertical.
DOMAIN_SEEDS: dict[str, type[DataSource]] = {
    "immortalization": ImmortalizationSeedSource,
    "adipogenesis": AdipogenesisSeedSource,
}


def seed_domain(name: str, store: KnowledgeStore) -> tuple[int, int]:
    """Load one shipped domain's curated graph. Raises ``KeyError`` for an unknown name."""
    return load_into(DOMAIN_SEEDS[name](), store)


def seed_registered_domains(store: KnowledgeStore) -> tuple[int, int]:
    """Load every shipped domain pack's curated graph into ``store``."""
    entities = interactions = 0
    for name in DOMAIN_SEEDS:
        added_entities, added_interactions = seed_domain(name, store)
        entities += added_entities
        interactions += added_interactions
    return entities, interactions
