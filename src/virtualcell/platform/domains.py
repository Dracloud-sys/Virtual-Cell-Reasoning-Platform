"""Domain pack interface and registry (PR11).

The smallest abstraction that lets the platform dispatch a :class:`ReasoningQuery` to a
vertical without knowing anything about that vertical's science. A pack declares which
domain it serves and which tasks it supports, and turns a query into a
:class:`ReasoningResponse`.

Deliberate non-features: this is not a plugin framework. There is no discovery protocol,
no versioned capability negotiation, and no dynamic loading — a pack is registered once
in composition code (see :mod:`virtualcell.platform.bootstrap`). Adding a second domain
means writing a pack and registering it; **no API, CLI, or service change is required.**

The registry contains no scientific rules, no thresholds, and no per-domain branches. It
resolves an identifier and verifies a task, and it never falls back to a default domain —
an unknown domain is an error, never silently answered by immortalization.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse


class DomainError(ValueError):
    """Base class for domain dispatch failures."""


class UnknownDomainError(DomainError):
    """Raised when no pack is registered for the requested domain."""


class UnsupportedTaskError(DomainError):
    """Raised when a registered pack does not support the requested task."""


class QueryValidationError(DomainError):
    """Raised when a query is well-formed but invalid for its domain/task."""


@runtime_checkable
class DomainPack(Protocol):
    """A reasoning vertical, addressable by the generic query boundary."""

    domain: str
    """Stable identifier used in :attr:`ReasoningQuery.domain`."""

    supported_tasks: tuple[str, ...]
    """Task identifiers this pack can execute."""

    def execute(self, query: ReasoningQuery, store: KnowledgeStore) -> ReasoningResponse:
        """Run the domain's own reasoning path and return the generic envelope.

        Implementations must delegate to the vertical's real product path rather than
        re-deriving its rules, and must not weaken its claim boundaries, evidence tiers,
        or citations while converting.
        """
        ...


class DomainRegistry:
    """Resolves a domain pack by identifier and verifies the requested task."""

    def __init__(self) -> None:
        self._packs: dict[str, DomainPack] = {}

    def register(self, pack: DomainPack) -> None:
        """Register a pack. Re-registering the same domain is an error, not a silent
        overwrite — two packs claiming one domain is a composition bug."""
        if not getattr(pack, "domain", None):
            raise ValueError("a domain pack must declare a non-empty 'domain'")
        if not getattr(pack, "supported_tasks", None):
            raise ValueError(f"domain pack {pack.domain!r} declares no supported tasks")
        if pack.domain in self._packs:
            raise ValueError(f"domain already registered: {pack.domain}")
        self._packs[pack.domain] = pack

    def get(self, domain: str) -> DomainPack:
        """Return the pack for ``domain``, or raise :class:`UnknownDomainError`."""
        pack = self._packs.get(domain)
        if pack is None:
            raise UnknownDomainError(f"unknown domain: {domain!r} (registered: {self.domains()})")
        return pack

    def resolve(self, domain: str, task: str) -> DomainPack:
        """Return the pack that can run ``task`` for ``domain``.

        Both failure modes are distinct and explicit: an unregistered domain raises
        :class:`UnknownDomainError`, a registered domain that cannot do the task raises
        :class:`UnsupportedTaskError`. Neither ever degrades into a default.
        """
        pack = self.get(domain)
        if task not in pack.supported_tasks:
            raise UnsupportedTaskError(
                f"domain {domain!r} does not support task {task!r} "
                f"(supported: {list(pack.supported_tasks)})"
            )
        return pack

    def domains(self) -> list[str]:
        return sorted(self._packs)

    def tasks(self, domain: str) -> list[str]:
        return sorted(self.get(domain).supported_tasks)

    def __contains__(self, domain: object) -> bool:
        return domain in self._packs
