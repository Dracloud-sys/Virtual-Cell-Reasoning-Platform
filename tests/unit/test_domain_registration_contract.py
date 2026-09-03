"""A mis-declared pack must not register quietly.

The registry is the one place every domain passes through, so it is the place a contradiction
between what a pack *claims* and what it *is* can still be cheap to catch. The failures below
are not hypothetical shapes — each is a mistake someone writing a fourth pack would plausibly
make, and each would surface much later as a caller being told about an axis or a task that
does not work.

Split by cost, deliberately:

* :func:`DomainRegistry.register` runs the structural checks, which read a description that is
  a module-level constant in every shipped pack and therefore cost nothing.
* :func:`validate_pack` adds the one that probes each declared axis through the pack's own
  validation — a call per axis, which is right for a composition test and wrong for a
  constructor.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.description import (
    AxisDescription,
    AxisKind,
    DomainDescription,
    TaskDescription,
    ValueType,
)
from virtualcell.platform.domains import DomainRegistry, QueryValidationError, validate_pack

VOCAB = ("yes", "no", "unknown")


def _axis(name: str = "signal", **overrides) -> AxisDescription:
    return AxisDescription(
        **{
            "name": name,
            "description": "a fictional readout",
            "value_type": ValueType.CATEGORICAL,
            "vocabulary": VOCAB,
            "kind": AxisKind.STATUS,
            "unmeasured_value": "unknown",
            "used_for": ("fictional_status",),
            **overrides,
        }
    )


def _description(**overrides) -> DomainDescription:
    return DomainDescription(
        **{
            "domain": "myogenesis",
            "summary": "A fictional domain that exists only inside this test.",
            "tasks": (
                TaskDescription(
                    name="assess_state",
                    purpose="judges a fictional state",
                    required_axes=("signal",),
                ),
            ),
            "axes": (_axis(),),
            **overrides,
        }
    )


class _Pack:
    """A well-formed pack. Every failing case below is this one with a single thing spoiled."""

    domain = "myogenesis"
    supported_tasks: tuple[str, ...] = ("assess_state",)

    def __init__(self, description: DomainDescription | None = None, accepts: bool = True) -> None:
        self._description = description or _description()
        self._accepts = accepts

    def describe(self) -> DomainDescription:
        return self._description

    def validate_experiment(self, task: str, experiment: Mapping[str, Any]) -> None:
        if not self._accepts:
            raise QueryValidationError(f"this pack accepts nothing (got {dict(experiment)})")

    def execute(self, query: ReasoningQuery, store) -> ReasoningResponse:  # pragma: no cover
        raise NotImplementedError


def _register(pack) -> None:
    DomainRegistry().register(pack)


# --- the well-formed case ------------------------------------------------------


def test_a_consistent_pack_registers_and_validates() -> None:
    pack = _Pack()
    _register(pack)
    validate_pack(pack)


# --- what registration itself refuses -----------------------------------------


def test_a_pack_that_cannot_describe_itself_is_refused() -> None:
    class _Mute(_Pack):
        describe = None

    with pytest.raises(ValueError, match="does not describe itself"):
        _register(_Mute())


def test_a_pack_that_cannot_validate_a_payload_is_refused() -> None:
    """Without it nothing can check a description against what the domain accepts, so the
    description would be unfalsifiable rather than merely unchecked."""

    class _Unchecked(_Pack):
        validate_experiment = None

    with pytest.raises(ValueError, match="cannot validate an experiment payload"):
        _register(_Unchecked())


def test_a_description_naming_a_different_domain_is_refused() -> None:
    """A caller reading the description would address a domain that is not registered."""
    with pytest.raises(ValueError, match="describes itself as"):
        _register(_Pack(_description(domain="adipogenesis")))


def test_a_description_that_names_a_task_twice_is_refused() -> None:
    duplicated = _description(
        tasks=(
            TaskDescription(name="assess_state", purpose="judges a fictional state"),
            TaskDescription(name="assess_state", purpose="judges it again"),
        )
    )
    with pytest.raises(ValueError, match="describes a task twice"):
        _register(_Pack(duplicated))


def test_described_tasks_that_disagree_with_supported_tasks_are_refused() -> None:
    """Both directions are wrong for the same reason: a caller is told something the registry
    will not honour, or is not told something it would."""
    extra = _description(
        tasks=(
            TaskDescription(name="assess_state", purpose="judges a fictional state"),
            TaskDescription(name="explain_mechanism", purpose="explains a fictional mechanism"),
        )
    )
    with pytest.raises(ValueError, match="describes tasks"):
        _register(_Pack(extra))

    class _Extra(_Pack):
        supported_tasks = ("assess_state", "explain_mechanism")

    with pytest.raises(ValueError, match="describes tasks"):
        _register(_Extra())


# --- what the description model refuses before a registry ever sees it --------


def test_a_task_requiring_an_undeclared_axis_is_unconstructable() -> None:
    with pytest.raises(ValueError, match="names axes this domain does not declare"):
        _description(
            tasks=(
                TaskDescription(
                    name="assess_state", purpose="judges", required_axes=("no_such_axis",)
                ),
            )
        )


def test_an_axis_declared_twice_is_unconstructable() -> None:
    with pytest.raises(ValueError, match="axis declared twice"):
        _description(axes=(_axis(), _axis()))


def test_a_categorical_axis_without_a_vocabulary_is_unconstructable() -> None:
    """A caller cannot guess a vocabulary, and an empty one is the shape of a description
    that would have to be read as "anything goes"."""
    with pytest.raises(ValueError, match="accepted values must be listed"):
        _axis(vocabulary=())


def test_a_context_axis_cannot_claim_a_purpose() -> None:
    with pytest.raises(ValueError, match="cannot name a purpose"):
        _axis(kind=AxisKind.CONTEXT, used_for=("fictional_status",))


def test_a_guidance_axis_cannot_be_required() -> None:
    """An axis that cannot move the verdict cannot be a precondition for reaching one."""
    with pytest.raises(ValueError, match="guidance and required"):
        _axis(kind=AxisKind.GUIDANCE, required=True)


# --- what only the expensive check can catch ----------------------------------


def test_an_axis_the_pack_will_not_accept_is_caught_by_validate_pack() -> None:
    """The join that costs a validation call per axis: a description can name an axis the
    domain's own model refuses, and only asking the pack finds it."""
    pack = _Pack(accepts=False)
    _register(pack)  # registration is structural, so this passes...

    with pytest.raises(ValueError, match="its own validation refuses it"):
        validate_pack(pack)  # ...and the full check does not
