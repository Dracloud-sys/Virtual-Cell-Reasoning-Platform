"""Composition root for the platform boundary (PR11).

The **one** place domain packs are registered. Interfaces (API, CLI, services) resolve
domains through the registry and never name a vertical themselves, so adding a domain is
a change here and nowhere else.

Registering a second domain — say adipogenesis — is the whole diff::

    from virtualcell.platform.packs.adipogenesis import AdipogenesisDomainPack

    def default_registry() -> DomainRegistry:
        registry = DomainRegistry()
        registry.register(ImmortalizationDomainPack())
        registry.register(AdipogenesisDomainPack())   # <- the only line added
        return registry

No API route, CLI command, request contract, or service change is required: the new
domain is immediately addressable as ``{"domain": "adipogenesis", "task": ...}``.
"""

from __future__ import annotations

from virtualcell.platform.domains import DomainRegistry
from virtualcell.platform.packs.immortalization import ImmortalizationDomainPack


def default_registry() -> DomainRegistry:
    """A registry with every shipped domain pack registered."""
    registry = DomainRegistry()
    registry.register(ImmortalizationDomainPack())
    return registry
