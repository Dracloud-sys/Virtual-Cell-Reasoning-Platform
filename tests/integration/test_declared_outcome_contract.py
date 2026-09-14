"""A pack must not report a verdict its own description never promised.

PR18 closed this on the **input** side: a description that advertised a vocabulary while
the model accepted anything was a contract that lied, and it mattered far more once an
agent read that description and believed it. The output side stayed open. Since PR18 each
pack declares `status_vocabulary` and `flags`; since the MCP server, `describe_domain`
hands both to a calling agent as the authoritative list of what it may see - which is what
publishing a vocabulary is *for*. Nothing checked that what a pack *emits* is in what it
*declared*.

The gap is not hypothetical because no drift exists today. Sweeping every categorical axis
of all three shipped domains produces only 3 of 5 adipogenesis statuses, 2 of 4 genome-edit
statuses and 5 of 16 flags - the rest need trends, series or day values to reach. A
mismatch on one of those paths would be invisible to every test in the tree, and would
reach an agent as a verdict it cannot map and has no reason to distrust.

So the envelope is checked against the pack's own declaration, and the check is at the one
place every surface passes through. It merges no vocabulary: each domain keeps its own, the
pack still owns what its statuses mean, and the generic layer only carries the value and
refuses to carry one that was never declared.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Mapping
from typing import Any

import pytest

from virtualcell.agents.immortalization.limitations import supported_constructs
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.platform.bootstrap import default_registry, seed_registered_domains
from virtualcell.platform.contracts import (
    DecisionSupport,
    QueryProvenance,
    ReasoningQuery,
    ReasoningResponse,
)
from virtualcell.platform.description import (
    AxisDescription,
    AxisKind,
    DomainDescription,
    TaskDescription,
    ValueType,
)
from virtualcell.platform.domains import (
    DomainError,
    DomainRegistry,
    UndeclaredOutcomeError,
)
from virtualcell.platform.service import ReasoningService

REGISTRY = default_registry()
DOMAINS = REGISTRY.domains()
DESCRIPTIONS = {domain: REGISTRY.describe(domain) for domain in DOMAINS}

# Enough to walk every categorical combination of the shipped packs without the sweep
# becoming the slowest test in the suite.
MAX_COMBOS = 240


def _service(registry: DomainRegistry | None = None) -> ReasoningService:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    return ReasoningService(store, registry or REGISTRY)


def _ask(service: ReasoningService, domain: str, task: str, experiment: Mapping[str, Any]):
    query = ReasoningQuery(domain=domain, task=task, experiment=dict(experiment))
    return asyncio.run(service.query(query))


def _payloads(domain: str, task: TaskDescription) -> list[dict[str, Any]]:
    """Every categorical combination this task reads, with one value for the rest."""
    description = DESCRIPTIONS[domain]
    names = [
        name
        for name in (*task.required_axes, *task.reads_axes)
        if description.axis(name) is not None
    ]
    axes = {name: description.axis(name) for name in names}

    sweepable = [name for name in names if axes[name].vocabulary]
    fixed: dict[str, Any] = {}
    for name in names:
        if name in sweepable:
            continue
        axis = axes[name]
        if axis.value_type is ValueType.INTEGER:
            fixed[name] = 1
        elif axis.value_type is ValueType.NUMBER:
            fixed[name] = 1.0
        elif axis.value_type is ValueType.SERIES:
            continue
        else:
            fixed[name] = "x"

    options = [list(axes[name].vocabulary) for name in sweepable]
    combos = itertools.islice(itertools.product(*options), MAX_COMBOS) if options else [()]
    return [{**fixed, **dict(zip(sweepable, combo, strict=True))} for combo in combos]


# --- what the shipped packs actually emit --------------------------------------


@pytest.mark.parametrize("domain", DOMAINS)
def test_no_shipped_pack_emits_an_outcome_it_did_not_declare(domain: str) -> None:
    """The empirical half. It passes today; its job is to keep passing while the packs
    grow, which is exactly when a new status gets added to an enum and not to the
    declaration."""
    service = _service()
    description = DESCRIPTIONS[domain]
    declared_status = set(description.status_vocabulary)
    declared_flags = set(description.flags)

    for task in description.tasks:
        for payload in _payloads(domain, task):
            try:
                response = _ask(service, domain, task.name, payload)
            except DomainError:
                continue  # a refused payload is the input contract's business, not this one
            support = response.decision_support
            if support.status is not None:
                assert support.status in declared_status, (
                    f"{domain}/{task.name} emitted status {support.status!r}, "
                    f"declared {sorted(declared_status)}"
                )
            undeclared = set(support.flags) - declared_flags
            assert not undeclared, f"{domain}/{task.name} emitted undeclared flags {undeclared}"


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_shipped_pack_declares_a_status_vocabulary(domain: str) -> None:
    """An empty declaration is now a promise that the pack returns no status at all."""
    assert DESCRIPTIONS[domain].status_vocabulary


# --- the contract itself, on a pack this repository does not ship ---------------

_DOMAIN = "a-domain-this-repository-does-not-ship"
_AXIS = "fictional_readout"
_VOCAB = ("present", "absent", "unknown")
_STATUS = "fictional_status"
_FLAG = "fictional_flag"


def _description(**overrides: Any) -> DomainDescription:
    return DomainDescription(
        **{
            "domain": _DOMAIN,
            "summary": "A fictional domain that exists only inside this test.",
            "tasks": (
                TaskDescription(
                    name="assess_state",
                    purpose="judges a fictional state",
                    reads_measurements=True,
                    required_axes=(_AXIS,),
                    reads_axes=(_AXIS,),
                ),
            ),
            "axes": (
                AxisDescription(
                    name=_AXIS,
                    description="a fictional readout",
                    value_type=ValueType.CATEGORICAL,
                    vocabulary=_VOCAB,
                    kind=AxisKind.STATUS,
                    unmeasured_value="unknown",
                    used_for=(_STATUS,),
                ),
            ),
            "status_vocabulary": (_STATUS, "insufficient_evidence"),
            "flags": (_FLAG,),
            "unsupported_policy": "Anything undeclared is reported as unsupported.",
            **overrides,
        }
    )


class _Pack:
    """A well-formed pack. Each failing case below is this one told to emit one bad value."""

    domain = _DOMAIN
    supported_tasks = ("assess_state",)

    def __init__(
        self,
        *,
        status: str | None = _STATUS,
        flags: tuple[str, ...] = (_FLAG,),
        description: DomainDescription | None = None,
    ) -> None:
        self._status = status
        self._flags = flags
        self._description = description or _description()

    def describe(self) -> DomainDescription:
        return self._description

    def validate_experiment(self, task: str, experiment: Mapping[str, Any]) -> None:
        return None

    def execute(self, query: ReasoningQuery, store) -> ReasoningResponse:
        return ReasoningResponse(
            domain=_DOMAIN,
            task=query.task,
            summary="A fictional summary that establishes nothing.",
            decision_support=DecisionSupport(status=self._status, flags=list(self._flags)),
            provenance=QueryProvenance(
                domain=_DOMAIN,
                task=query.task,
                pack=type(self).__name__,
                engine="a fictional engine",
                explanation_level=query.explanation_level,
            ),
        )


def _registry_with(pack: Any) -> DomainRegistry:
    registry = DomainRegistry()
    registry.register(pack)
    return registry


def _run(pack: Any):
    registry = _registry_with(pack)
    return _ask(_service(registry), _DOMAIN, "assess_state", {_AXIS: "present"})


def test_a_pack_declaring_its_own_vocabulary_is_accepted() -> None:
    """The check must read the pack's declaration, never a central list - otherwise a
    fourth domain could not introduce a status at all."""
    response = _run(_Pack())
    assert response.decision_support.status == _STATUS
    assert response.decision_support.flags == [_FLAG]


def test_an_undeclared_status_is_refused_and_names_what_was_wrong() -> None:
    with pytest.raises(UndeclaredOutcomeError) as caught:
        _run(_Pack(status="a_status_nobody_declared"))
    message = str(caught.value)
    assert "a_status_nobody_declared" in message
    assert _DOMAIN in message
    assert _STATUS in message, "the refusal must say what the pack did declare"


def test_an_undeclared_flag_is_refused() -> None:
    with pytest.raises(UndeclaredOutcomeError) as caught:
        _run(_Pack(flags=(_FLAG, "a_flag_nobody_declared")))
    assert "a_flag_nobody_declared" in str(caught.value)


def test_a_null_status_is_always_allowed() -> None:
    """`None` is how a pack says it reached no verdict - a mechanism task, or too little
    evidence to have one. It is never a vocabulary violation."""
    response = _run(_Pack(status=None, flags=()))
    assert response.decision_support.status is None


def test_an_empty_declaration_permits_no_status_at_all() -> None:
    """Declaring nothing is a promise, not an exemption. An earlier reading of this would
    have treated `status_vocabulary=()` as 'unconstrained', which is the opposite of what
    an agent reading the description would conclude from it."""
    pack = _Pack(description=_description(status_vocabulary=(), flags=()))
    with pytest.raises(UndeclaredOutcomeError):
        _run(pack)


def test_the_refusal_is_not_a_caller_error() -> None:
    """This is a pack defect. Reported as a `DomainError` it would surface as HTTP 422 and
    as the MCP `invalid_experiment` refusal - both of which tell the caller to fix a
    payload that was never the problem, and invite them to send a different one."""
    assert not issubclass(UndeclaredOutcomeError, DomainError)
    with pytest.raises(UndeclaredOutcomeError) as caught:
        _run(_Pack(status="a_status_nobody_declared"))
    assert not isinstance(caught.value, DomainError)


def test_the_check_runs_on_the_one_path_every_surface_shares() -> None:
    """Placed in the service rather than in each pack, so a pack cannot skip it and a
    fourth domain inherits it without doing anything."""
    registry = _registry_with(_Pack(status="a_status_nobody_declared"))
    pack = registry.get(_DOMAIN)
    # The pack itself still produces the bad value: the refusal is the platform's, and
    # this pins that the pack was not quietly edited to make the test pass.
    direct = pack.execute(ReasoningQuery(domain=_DOMAIN, task="assess_state", experiment={}), None)
    assert direct.decision_support.status == "a_status_nobody_declared"
    with pytest.raises(UndeclaredOutcomeError):
        _ask(_service(registry), _DOMAIN, "assess_state", {})


# --- the other direction: a caller's mistake must not read as a server defect ---


def test_no_ordinary_payload_escapes_as_an_untyped_failure() -> None:
    """The mirror of the contract above, and how it was found.

    Sweeping the packs turned up `immortalization/explain_mechanism` with an empty
    payload: `validate_experiment` accepted it, `execute` then raised the vertical's own
    `UnsupportedMechanismError` - a plain `ValueError` the platform does not classify - and
    the caller got HTTP 500 and, through MCP, the bare string "Error executing tool
    reason". No detail, and nothing to act on.

    It was reachable by doing exactly what the description said: `describe_domain` listed
    no required axes for that task, so an agent following it sent nothing and crashed the
    server.
    """
    service = _service()
    escapes: list[str] = []
    for domain in DOMAINS:
        description = DESCRIPTIONS[domain]
        shapes = {
            "empty": {},
            "unmeasured": {
                axis.name: axis.unmeasured_value
                for axis in description.axes
                if axis.unmeasured_value is not None
            },
        }
        for task in description.tasks:
            for label, payload in shapes.items():
                try:
                    _ask(service, domain, task.name, payload)
                except DomainError:
                    pass  # classified: the caller is told what to fix
                except UndeclaredOutcomeError:  # pragma: no cover - covered above
                    raise
                except Exception as exc:  # noqa: BLE001 - the point is to catch anything
                    escapes.append(f"{domain}/{task.name} [{label}] -> {type(exc).__name__}: {exc}")
    assert not escapes, escapes


def test_an_unanswerable_request_says_what_to_send_instead() -> None:
    """A typed refusal that does not close the loop is only half a fix: the surfaces that
    show it are read by something that will otherwise guess."""
    service = _service()
    with pytest.raises(DomainError) as caught:
        _ask(service, "immortalization", "explain_mechanism", {})
    message = str(caught.value)
    assert "explain_mechanism" in message
    for construct in supported_constructs():
        assert construct in message, f"the refusal must name {construct!r} as a value that works"


def test_a_task_that_cannot_work_without_an_axis_declares_it_required() -> None:
    """The description is the fix; the typed refusal is the safety net. An agent that
    reads `describe_domain` should never reach the refusal at all."""
    description = DESCRIPTIONS["immortalization"]
    task = next(t for t in description.tasks if t.name == "explain_mechanism")
    assert "construct" in task.required_axes


def test_a_safety_error_is_never_converted_into_a_caller_error() -> None:
    """The exclusion that makes the conversion safe. A fired safety guard means the
    vertical produced something it must not ship; reported as a 422 it would tell the
    caller to fix a payload while the real defect stayed quiet - which is the failure this
    platform exists to prevent."""
    from virtualcell.agents.immortalization.hypotheses import HypothesisSafetyError
    from virtualcell.agents.immortalization.rules import ImmortalizationSafetyError
    from virtualcell.platform.packs.immortalization import _UNANSWERABLE

    for safety_error in (HypothesisSafetyError, ImmortalizationSafetyError):
        assert not issubclass(safety_error, _UNANSWERABLE), safety_error
