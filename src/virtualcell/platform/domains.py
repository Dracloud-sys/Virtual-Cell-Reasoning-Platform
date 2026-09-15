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

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from virtualcell.core.experiment import ExperimentRun, SchemaVersionError
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.platform.contracts import (
    CanonicalIntake,
    DecisionSupport,
    ReasoningQuery,
    ReasoningResponse,
)
from virtualcell.platform.description import DomainDescription, probe_value


class DomainError(ValueError):
    """Base class for domain dispatch failures."""


class UnknownDomainError(DomainError):
    """Raised when no pack is registered for the requested domain."""


class UnsupportedTaskError(DomainError):
    """Raised when a registered pack does not support the requested task."""


class QueryValidationError(DomainError):
    """Raised when a query is well-formed but invalid for its domain/task."""


# The run-identity namespace the literature pipeline mints under. Duplicated as a literal
# rather than imported: `virtualcell.literature` reaches the platform contracts, so an
# import here would close a cycle. A test pins the two together so they cannot drift.
_LITERATURE_NAMESPACE = "literature"


class UndeclaredOutcomeError(RuntimeError):
    """A pack reported a status or flag its own description never declared.

    Deliberately **not** a :class:`DomainError`. Every member of that family is the
    caller's mistake and is reported to them as one — HTTP 422, the MCP
    ``invalid_experiment`` refusal — which would tell them to fix a payload that was
    never the problem, and invite them to send a different one. This is a defect in the
    pack, and the honest answer is that the server is broken, not the request.
    """


@runtime_checkable
class DomainPack(Protocol):
    """A reasoning vertical, addressable by the generic query boundary."""

    domain: str
    """Stable identifier used in :attr:`ReasoningQuery.domain`."""

    supported_tasks: tuple[str, ...]
    """Task identifiers this pack can execute."""

    def describe(self) -> DomainDescription:
        """Everything a caller needs to build a valid request for this domain.

        Required, not optional, because the failure it prevents is silent: a caller that
        cannot ask what the axes are will guess, and PR17 showed that a guessed axis name is
        accepted, preserved and read by nothing. A pack that could decline to describe itself
        would leave that hole open for its own callers.

        The description must be *derived from* whatever the pack already uses to validate and
        classify input, never written beside it. Two statements of the same axis list drift;
        a drift test pins the join, but the structure should make the drift hard first.
        """
        ...

    def validate_experiment(self, task: str, experiment: Mapping[str, Any]) -> None:
        """Accept or refuse an experiment payload, without running any reasoning.

        The same validation ``execute`` performs, exposed so a caller can check a payload
        before paying for an answer — and so the platform can verify a description against the
        input contract it describes **without knowing which vertical it is talking to**.

        Before this existed the drift test named the three domains and imported their Pydantic
        models directly, which quietly made "a new domain is validated the moment it is
        registered" untrue. The validation source stays inside the pack; only the question
        crosses the boundary.

        Raises :class:`QueryValidationError` for a payload the domain cannot accept. Must have
        no side effects and must not reach the knowledge store.
        """
        ...

    def execute(self, query: ReasoningQuery, store: KnowledgeStore) -> ReasoningResponse:
        """Run the domain's own reasoning path and return the generic envelope.

        Implementations must delegate to the vertical's real product path rather than
        re-deriving its rules, and must not weaken its claim boundaries, evidence tiers,
        or citations while converting.
        """
        ...


@runtime_checkable
class CanonicalRunPack(Protocol):
    """A pack that can also read a canonical :class:`ExperimentRun`. **Optional.**

    Deliberately separate from :class:`DomainPack` rather than an optional member of it.
    A ``runtime_checkable`` protocol means "these members are present"; an optional member
    inside one makes the check say something it does not mean, and the two shipped domains
    that read only categorical snapshots would have to grow a stub to keep it true.

    A domain whose evidence is a set of marker calls has nothing a time-series run can
    carry. Refusing such a run explicitly, and naming the entry that does work, is a better
    answer than an empty payload that reasons over nothing.
    """

    def experiment_from_run(self, task: str, run: ExperimentRun) -> CanonicalIntake:
        """Turn a canonical run into this domain's own axis payload.

        The mapping is the pack's because it is biology: only this domain knows that a
        measurement named ``cumulative_PDL`` is the series its trajectory engine reads.
        The platform never infers one.

        Both halves of the returned :class:`CanonicalIntake` matter. A name this domain
        does not recognise must be reported on the ledger rather than dropped, and a
        reading QC did not call valid must be reported as excluded rather than read — the
        two are different failures and collapsing them hides a data problem inside a
        schema problem.
        """
        ...


def _reject_inconsistent_description(pack: DomainPack) -> None:
    """Structural checks cheap enough to run at registration.

    Deliberately only the ones that need no input validation: a description is a module-level
    constant in every shipped pack, so reading it costs nothing, while probing each declared
    axis costs a validation call per axis and belongs in :func:`validate_pack`.

    The point is that a mis-declared pack cannot register *quietly*. A description naming a
    different domain, or tasks the registry will refuse to dispatch, is a bug that would
    otherwise surface as a caller being told about a task that does not exist.
    """
    description = pack.describe()
    if description.domain != pack.domain:
        raise ValueError(
            f"domain pack {pack.domain!r} describes itself as {description.domain!r}; a caller "
            "reading the description would address a domain that is not registered"
        )

    described = [task.name for task in description.tasks]
    duplicates = sorted({name for name in described if described.count(name) > 1})
    if duplicates:
        raise ValueError(f"domain pack {pack.domain!r} describes a task twice: {duplicates}")

    if set(described) != set(pack.supported_tasks):
        raise ValueError(
            f"domain pack {pack.domain!r} describes tasks {sorted(described)} but supports "
            f"{sorted(pack.supported_tasks)}; a caller would be offered a task the registry "
            "will refuse, or never told about one it would accept"
        )


class CanonicalIntakeUnsupported(QueryValidationError):
    """The domain cannot read canonical runs, so the caller must send an experiment dict.

    A :class:`QueryValidationError` rather than a bare :class:`DomainError`, because it is
    exactly that: a well-formed query that is invalid for the domain it names. Sitting in
    that family gives it the reporting every other caller mistake already has - HTTP 422,
    the MCP `invalid_experiment` refusal - instead of a second shape every surface would
    have to learn.
    """


def accepts_runs(pack: DomainPack) -> bool:
    """Does this pack implement the optional canonical-run hook?"""
    return isinstance(pack, CanonicalRunPack)


def check_run_admissible(run: ExperimentRun) -> None:
    """Refuse a run this boundary must not read, before any pack sees it.

    Two refusals, and the second is the one that matters.

    The schema check is the obvious one: this reads field meanings — passage numbers,
    doubling times — out of a structure it did not build, and a run written against a
    different major version could yield a plausible-looking and wrong trajectory.

    The literature check is not obvious, which is exactly why it is here. A literature
    run declares ``OriginKind.EXPERIMENT`` like any other, because a paper does report a
    real experiment — so nothing in its *shape* stops a number extracted from a PDF
    driving a candidate status at the same weight as a reading someone took. Every
    safeguard the literature layer built (weak `ASSOCIATED_WITH` edges, `pending_review`,
    the never-established downgrade) would be bypassed through a different door, silently.
    What separates the two is the run-identity namespace PR12 introduced, so that is what
    is checked.
    """
    try:
        run.require_compatible_schema()
    except SchemaVersionError as exc:
        raise QueryValidationError(
            f"canonical run {run.run_id!r} declares schema version "
            f"{run.schema_version!r}, which this platform cannot read: {exc}"
        ) from exc

    if run.run_namespace == _LITERATURE_NAMESPACE:
        raise QueryValidationError(
            f"canonical run {run.run_id!r} was produced by the literature pipeline, and a "
            "literature reading is not a measurement the caller took. It would otherwise "
            "reach a verdict at the same weight as a bench reading, which is what the "
            "weak, pending-review evidence policy exists to prevent. Set "
            "allow_literature=true instead: literature evidence is reported separately, "
            "labelled, and never merged into the domain's own evidence."
        )


def resolve_canonical_intake(
    pack: DomainPack, query: ReasoningQuery, run: ExperimentRun
) -> CanonicalIntake:
    """Ask the pack what the run means, and refuse a collision with the caller's dict.

    Where the run and the dict disagree about the same axis, neither answer can be given
    without discarding the other, and nothing in the response could say which was dropped.
    Refusing is the only outcome that cannot quietly lose a measurement.
    """
    if not accepts_runs(pack):
        raise CanonicalIntakeUnsupported(
            f"domain {pack.domain!r} does not read canonical experiment runs; send the "
            "measurements in the 'experiment' payload instead (call describe_domain, or "
            "GET /reasoning/domains, for the axes it accepts)"
        )

    intake = pack.experiment_from_run(query.task, run)
    collisions = sorted(set(intake.experiment) & set(query.experiment))
    if collisions:
        raise QueryValidationError(
            f"canonical run {run.run_id!r} and the 'experiment' payload both supply "
            f"{collisions}; two sources for one value cannot be merged without discarding "
            "one silently. Remove the key from 'experiment', or send the run alone."
        )
    return intake


def validate_declared_outcome(description: DomainDescription, support: DecisionSupport) -> None:
    """Refuse a verdict the domain's own description never promised.

    The output-side twin of the input validation PR18 added. A description that
    advertises a `status_vocabulary` while the pack may emit anything is a contract that
    lies, and it lies loudest to the reader most likely to believe it: `describe_domain`
    hands an agent that vocabulary as the authoritative list of what it may see, which is
    the whole point of publishing one.

    Three things this deliberately does **not** do:

    * It merges no vocabularies. Each domain keeps its own, and the comparison is always
      against the description that came from the same pack.
    * It ranks and interprets nothing. The generic layer carries the value; what the
      value *means* stays with the pack.
    * It does not treat an empty declaration as "unconstrained". Declaring nothing is a
      promise that the pack returns no status, because that is what an agent reading the
      description would conclude from it.

    ``status`` of ``None`` is always allowed: that is how a pack says it reached no
    verdict, which is a position, not a violation.
    """
    declared_status = set(description.status_vocabulary)
    if support.status is not None and support.status not in declared_status:
        raise UndeclaredOutcomeError(
            f"domain pack {description.domain!r} reported status {support.status!r}, "
            f"which its description does not declare "
            f"(declared: {sorted(declared_status) or 'nothing'})"
        )

    declared_flags = set(description.flags)
    undeclared = [flag for flag in support.flags if flag not in declared_flags]
    if undeclared:
        raise UndeclaredOutcomeError(
            f"domain pack {description.domain!r} reported flags {undeclared}, "
            f"which its description does not declare "
            f"(declared: {sorted(declared_flags) or 'nothing'})"
        )


def validate_pack(pack: DomainPack) -> None:
    """Every consistency check a pack must satisfy, including the expensive one.

    Extends the registration-time checks with the join they cannot afford: **every axis the
    description declares must be a payload the pack's own validation accepts**. That is one
    validation call per axis, which is fine in a composition test and wrong in a constructor.

    Domain-neutral by construction — it reads the description and calls
    ``validate_experiment``, and never learns which vertical it is inspecting.
    """
    _reject_inconsistent_description(pack)
    description = pack.describe()

    for task in description.tasks:
        for axis_name in (*task.required_axes, *task.reads_axes):
            axis = description.axis(axis_name)
            if axis is None:  # pragma: no cover - DomainDescription refuses this first
                raise ValueError(f"task {task.name!r} names an undeclared axis {axis_name!r}")

    for axis in description.axes:
        probe = probe_value(axis)
        for task in description.tasks:
            try:
                pack.validate_experiment(task.name, {axis.name: probe})
            except DomainError as exc:
                raise ValueError(
                    f"domain pack {pack.domain!r} declares axis {axis.name!r} but its own "
                    f"validation refuses it on task {task.name!r}: {exc}"
                ) from exc


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
        if not callable(getattr(pack, "describe", None)):
            raise ValueError(
                f"domain pack {pack.domain!r} does not describe itself; a domain a caller "
                "cannot introspect is a domain a caller will send invented axis names to"
            )
        if not callable(getattr(pack, "validate_experiment", None)):
            raise ValueError(
                f"domain pack {pack.domain!r} cannot validate an experiment payload; without "
                "it, nothing can check that its description matches what it accepts"
            )
        _reject_inconsistent_description(pack)
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

    def describe(self, domain: str) -> DomainDescription:
        """The domain's self-description, or :class:`UnknownDomainError`.

        Deliberately routed through the same resolution as ``execute``: a caller must not be
        able to read a description for a domain it cannot then query.
        """
        return self.get(domain).describe()

    def descriptions(self) -> list[DomainDescription]:
        """Every registered domain's description, in the registry's own order."""
        return [self.get(domain).describe() for domain in self.domains()]

    def __contains__(self, domain: object) -> bool:
        return domain in self._packs
