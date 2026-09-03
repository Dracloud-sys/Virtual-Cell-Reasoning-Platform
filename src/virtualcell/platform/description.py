"""Domain self-description — what a caller must know to build a valid request.

Written for a caller that cannot read the source: an LLM assembling an ``experiment`` payload
from a sentence of natural language. Such a caller invents axis names constantly, and PR17's
``unsupported`` state is only a *reactive* correction — it tells you afterwards that the marker
you cared about was dropped. A description turns that into prevention: ask what the axes are,
then send those.

Three rules shape the contract.

**The pack owns the biology.** Which axes exist, what their vocabularies mean, which of them
can move a verdict — all domain judgement. This module owns only the shape those answers come
back in, so a caller comparing two domains reads the same field to mean the same thing.

**One declaration, not two.** Before this, a pack stated its axes twice: once as Pydantic
fields on the assessment input, once as the private ``_STATUS_AXES`` / ``_GUIDANCE_AXES``
tuples PR17 added. Two lists that had to agree, with nothing making them. Here the axis
declaration is the single source: the description is built from it, and each pack's consumption
policy is *derived* from it rather than restated. A drift test pins the remaining join — every
declared axis must be a field the input model actually accepts, and every declared vocabulary
value must actually validate.

**Description is not validation.** Nothing here loosens a Pydantic model. The description
reports what the model already enforces; where the two disagree the model wins and the test
fails.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from virtualcell.core.consumption import ConsumptionLedger, ConsumptionReport


class AxisKind(StrEnum):
    """What an axis is allowed to do to an answer.

    The same three-way split PR17 reports after the fact, declared up front — so a pack's
    consumption ledger can be derived from it instead of repeating it.
    """

    STATUS = "status"
    """Can move the domain's verdict."""

    GUIDANCE = "guidance"
    """Refines a verdict it can never make — flags, evidence, safety caveats, next steps."""

    CONTEXT = "context"
    """Carried, preserved, and read by no rule. Declared rather than omitted, because a caller
    who believes ``species`` steers the reasoning should be able to find out that it does not."""


class ValueType(StrEnum):
    """How a value is written, not what it means."""

    CATEGORICAL = "categorical"
    INTEGER = "integer"
    NUMBER = "number"
    TEXT = "text"
    SERIES = "series"


class AxisDescription(BaseModel):
    """One axis a caller may submit."""

    model_config = ConfigDict(frozen=True)

    name: str
    """The key to send. What a caller writes, not what it resolves to internally."""

    canonical_name: str | None = None
    """What it resolves to, when that differs from ``name`` — immortalization accepts
    ``construct`` and stores ``construct_type``. Defaults to ``name``, and is spelled the same
    as the field on :class:`~virtualcell.core.consumption.MeasurementConsumption` so a caller
    can join a description to a consumption ledger without a mapping table."""

    description: str
    value_type: ValueType
    kind: AxisKind

    vocabulary: tuple[str, ...] = ()
    """Every accepted value, for a categorical axis. Empty for the others."""

    minimum: float | None = None
    maximum: float | None = None

    required: bool = False
    """Whether a verdict is possible without it. Optional does not mean unimportant: a guidance
    axis is never required and can still be the reason a result is unusable."""

    unmeasured_value: str | None = None
    """How to say "no reading was taken" on this axis. Spelled out because it is the distinction
    the platform protects hardest — a measured negative is a result, an unmeasured axis is a
    gap — and a caller who does not know the spelling will conflate them."""

    used_for: tuple[str, ...] = ()
    """The purposes that read this axis: ``candidate_status``, ``flag:mosaic_population``,
    ``next_experiment``. Reused verbatim as the consumption ledger's ``used_for``."""

    @model_validator(mode="after")
    def _shape_matches_the_kind(self) -> AxisDescription:
        if self.value_type is ValueType.CATEGORICAL and not self.vocabulary:
            raise ValueError(
                f"axis {self.name!r} is categorical, so its accepted values must be listed; "
                "a caller cannot guess a vocabulary"
            )
        if self.value_type is not ValueType.CATEGORICAL and self.vocabulary:
            raise ValueError(
                f"axis {self.name!r} is {self.value_type.value}, so a vocabulary is meaningless"
            )
        if self.kind is AxisKind.CONTEXT and self.used_for:
            raise ValueError(
                f"axis {self.name!r} is context: nothing reads it, so it cannot name a purpose "
                f"(got {list(self.used_for)})"
            )
        if self.kind is not AxisKind.CONTEXT and not self.used_for:
            raise ValueError(
                f"axis {self.name!r} claims to be read, so it must name at least one purpose"
            )
        if self.kind is AxisKind.GUIDANCE and self.required:
            raise ValueError(
                f"axis {self.name!r} is guidance and required: an axis that cannot move the "
                "verdict cannot be a precondition for reaching one"
            )
        return self

    @property
    def resolved_name(self) -> str:
        return self.canonical_name or self.name


def probe_value(axis: AxisDescription) -> Any:
    """A minimal value of the right shape for ``axis``.

    Exists so a contract check can ask "would you accept this axis at all?" without knowing
    the domain. For a categorical axis the answer is its own first declared value; for the
    others it is the emptiest thing of the right type. Never a *meaningful* value - this
    probes the shape of the contract, not the science.
    """
    if axis.vocabulary:
        return axis.vocabulary[0]
    return {
        ValueType.INTEGER: 0,
        ValueType.NUMBER: 0.0,
        ValueType.SERIES: [],
        ValueType.TEXT: "x",
    }[axis.value_type]


class TaskDescription(BaseModel):
    """One task the domain can execute."""

    model_config = ConfigDict(frozen=True)

    name: str
    purpose: str

    reads_measurements: bool = True
    """``False`` for a task that answers from curated policy alone. Declaring it matters:
    immortalization's ``handle_hypothesis`` reads no submitted value at all, which is
    defensible and was undiscoverable until PR17 reported it after the fact."""

    required_axes: tuple[str, ...] = ()
    """Axes a verdict is impossible without. Empty when the task reads no measurements."""

    reads_axes: tuple[str, ...] = ()
    """The axes this task actually consults, when that is narrower than the domain's whole
    set. Empty means "all of them".

    Needed because ``reads_measurements`` is too coarse for the real case: immortalization's
    ``explain_mechanism`` reads exactly one axis (the construct) and ignores every marker. A
    domain-wide axis kind cannot express that, and without it a mechanism response would
    report markers as consumed that no rule looked at."""

    example: dict[str, Any] | None = None
    """A minimal payload this task accepts, so a caller can copy rather than infer."""

    @model_validator(mode="after")
    def _a_task_that_reads_nothing_requires_nothing(self) -> TaskDescription:
        if not self.reads_measurements:
            if self.required_axes:
                raise ValueError(
                    f"task {self.name!r} reads no measurements, so it cannot require "
                    f"{list(self.required_axes)}"
                )
            if self.reads_axes:
                raise ValueError(
                    f"task {self.name!r} reads no measurements, so it cannot also name "
                    f"{list(self.reads_axes)} as axes it reads"
                )
        unread = [
            axis for axis in self.required_axes if self.reads_axes and axis not in self.reads_axes
        ]
        if unread:
            raise ValueError(
                f"task {self.name!r} requires {unread} but does not list them among the axes "
                "it reads"
            )
        return self

    def reads(self, axis: str) -> bool:
        """Does this task consult ``axis``?"""
        if not self.reads_measurements:
            return False
        return not self.reads_axes or axis in self.reads_axes


class DomainDescription(BaseModel):
    """Everything a caller needs to build a valid request for one domain."""

    model_config = ConfigDict(frozen=True)

    domain: str
    summary: str
    """A sentence or two on what this vertical decides — and, where it matters, what it
    refuses to decide."""

    tasks: tuple[TaskDescription, ...]
    axes: tuple[AxisDescription, ...]

    status_vocabulary: tuple[str, ...] = ()
    """Every value this domain's ``decision_support.status`` can take, so a caller does not have
    to discover the vocabulary by hitting it."""

    flags: tuple[str, ...] = ()

    unsupported_policy: str = (
        "An unrecognised key is accepted and preserved on the input, reaches no reasoning, and "
        "is reported in measurement_consumption with status 'unsupported'."
    )
    """What becomes of a key this domain does not know. Stated because the honest answer is
    surprising: it is neither rejected nor used."""

    @model_validator(mode="after")
    def _the_description_is_internally_consistent(self) -> DomainDescription:
        names = [axis.name for axis in self.axes]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"axis declared twice: {duplicates}")

        known = set(names)
        for task in self.tasks:
            unknown = [
                axis for axis in (*task.required_axes, *task.reads_axes) if axis not in known
            ]
            if unknown:
                raise ValueError(
                    f"task {task.name!r} names axes this domain does not declare: {unknown}"
                )
        if not self.tasks:
            raise ValueError(f"domain {self.domain!r} must declare at least one task")
        return self

    def axis(self, name: str) -> AxisDescription | None:
        """The axis a submitted key names, or ``None`` if the domain does not know it."""
        return next((a for a in self.axes if a.name == name), None)

    def axes_of(self, kind: AxisKind) -> tuple[AxisDescription, ...]:
        return tuple(a for a in self.axes if a.kind is kind)

    def task(self, name: str) -> TaskDescription | None:
        return next((t for t in self.tasks if t.name == name), None)


# --- deriving the consumption ledger from the declaration ---------------------
#
# Extracted only after three packs wanted it. The immortalization and adipogenesis packs
# each walked the submitted keys, classified them, and emitted a ledger entry; the third
# domain would have been a third copy of the same loop over a different declaration. The
# *procedure* is what repeats, so the procedure is what moves here — the declarations stay in
# the packs, where the biology is.
#
# It also closes the duplication PR17 left behind. `_STATUS_AXES` / `_GUIDANCE_AXES` were a
# second statement of what the axes are; now `AxisKind` on the description is the only one,
# and both the description and the ledger read it.

_CONTEXT_REASON = (
    "carried as request context and preserved in the response, but no rule in this domain reads it"
)


def _unmeasured_reason(axis: AxisDescription) -> str:
    spelling = axis.unmeasured_value or "unknown"
    return (
        f"submitted as {spelling!r}, so there was no reading for the reasoning to consult; "
        "it is reported as a gap rather than as a value"
    )


def derive_consumption(
    description: DomainDescription,
    *,
    task: str,
    experiment: Mapping[str, Any],
    has_reading: Callable[[AxisDescription], bool],
    ignore: Iterable[str] = ("intent",),
    provenance: str = "query.experiment",
    context_reason: str = _CONTEXT_REASON,
    unread_task_reason: str | None = None,
    unmeasured_reason: Callable[[AxisDescription], str] = _unmeasured_reason,
) -> ConsumptionReport:
    """Build a consumption ledger from what the domain declared about its own axes.

    ``has_reading`` is the one genuinely domain-specific input: every vertical spells "no
    reading" differently (``MarkerValue.UNKNOWN``, the string ``"unknown"``, ``None``, an
    empty series), and only the pack can answer it. Everything else — which axis can move a
    verdict, what purposes read it, what happens to a name nobody recognises — is read off the
    description, so a pack cannot declare one thing and report another.

    Which axes a *task* reads is read off :meth:`TaskDescription.reads`, so a mechanism
    question does not report a marker panel as consumed. ``unread_task_reason`` overrides the
    wording when the generic sentence is not the honest one.
    """
    ledger = ConsumptionLedger(provenance=provenance)
    skip = set(ignore)
    task_description = description.task(task)
    unread = unread_task_reason
    if unread is None and task_description is not None:
        purpose = task_description.purpose
        unread = f"task {task!r} does not read this axis; it {purpose[0].lower()}{purpose[1:]}"

    for key in experiment:
        if key in skip:
            continue
        axis = description.axis(key)
        if axis is None:
            ledger.unsupported(key, reason=description.unsupported_policy)
        elif axis.kind is AxisKind.CONTEXT:
            ledger.not_applicable(key, canonical_name=axis.resolved_name, reason=context_reason)
        elif task_description is not None and not task_description.reads(key):
            ledger.not_applicable(key, canonical_name=axis.resolved_name, reason=unread)
        elif not has_reading(axis):
            ledger.not_applicable(
                key, canonical_name=axis.resolved_name, reason=unmeasured_reason(axis)
            )
        elif axis.kind is AxisKind.STATUS:
            ledger.used_for_status(
                key, canonical_name=axis.resolved_name, used_for=list(axis.used_for)
            )
        else:
            ledger.used_for_guidance(
                key, canonical_name=axis.resolved_name, used_for=list(axis.used_for)
            )
    return ledger.report()
