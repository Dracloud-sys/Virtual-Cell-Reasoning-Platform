"""Run a small Boolean candidate model under an intervention, and say what follows from it.

The question answered is *if this candidate model and these conditions held, what would
follow?*, never *this is what the cell does*. The specification, written before this module,
is `docs/research_sessions/logic_model_v0/SPEC.md`.

Why this is not a :class:`~virtualcell.simulation.engine.SimulationEngine`: that protocol
carries `dict[str, float]` layers, a `time: float` and a `dt: float`. A logic model has values
that are only active or inactive, values that are unknown and must not become 0, and steps
that are not time. Fitting it into `CellState` would turn unknown into a number and step 1
into a duration, so the protocol is left as it is and this is a separate, small representation.

What it does, in one place (the MCP tool calls this and nothing else):

* rules are structured expressions over declared components: ``const``, ``var``, ``not``,
  ``and``, ``or``. Nothing is parsed from a string and nothing is evaluated as code;
* update is synchronous: every rule reads the same previous state, so the order components or
  rules are listed in cannot change anything;
* a step is a logical update, not a unit of time;
* clamps fix a component or input over an inclusive range of state indices without touching the
  model;
* unknown initial values and unknown input segments are expanded into cases, each kept as its
  own path; nothing unknown is ever read as inactive;
* a missing rule or input makes a value *not computed*, never inactive and never "held".
"""

from __future__ import annotations

import hashlib
import json
from itertools import product
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_COMPONENTS = 32
MAX_STEPS = 100
DEFAULT_MAX_CASES = 256
MAX_CASES = 4096
MAX_EXPR_DEPTH = 16

#: A value inside one case: active, inactive, or not computed (a rule or an input is missing).
Value = bool | None


class LogicModelError(ValueError):
    """The model or scenario cannot be run as given. The message says what and where."""


# --- the model -------------------------------------------------------------------------- #


class Expr(BaseModel):
    """One node of a rule. Exactly one of the fields is set."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    const: bool | None = Field(default=None, description="A constant: true or false.")
    var: str | None = Field(default=None, description="A declared component id.")
    not_: Expr | None = Field(default=None, alias="not", description="Negation of one node.")
    and_: list[Expr] | None = Field(
        default=None, alias="and", description="True when every node is true (at least one)."
    )
    or_: list[Expr] | None = Field(
        default=None, alias="or", description="True when any node is true (at least one)."
    )

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> dict[str, Any]:
        """Published flat: a recursive schema cannot be inlined into one tool parameter."""
        node = {
            "type": "object",
            "description": "Any expression node, as described above.",
        }
        return {
            "type": "object",
            "description": (
                "One expression node with exactly one key: const (true/false), var (a declared "
                "component id), not (one node), and (a list of at least one node), or (a list "
                "of at least one node). Nested nodes have the same form. No other key exists."
            ),
            "properties": {
                "const": {"type": "boolean"},
                "var": {"type": "string"},
                "not": node,
                "and": {"type": "array", "items": node, "minItems": 1},
                "or": {"type": "array", "items": node, "minItems": 1},
            },
            "minProperties": 1,
            "maxProperties": 1,
            "additionalProperties": False,
            "examples": [{"or": [{"var": "S"}, {"var": "P"}]}],
        }

    @model_validator(mode="after")
    def _exactly_one(self) -> Expr:
        set_ = [k for k in ("const", "var", "not_", "and_", "or_") if getattr(self, k) is not None]
        if len(set_) != 1:
            raise ValueError(
                "an expression node has exactly one of const, var, not, and, or; "
                f"this one has {[s.rstrip('_') for s in set_] or 'none'}"
            )
        for key in ("and_", "or_"):
            if getattr(self, key) == []:
                raise ValueError(f"{key.rstrip('_')} needs at least one operand")
        return self

    def variables(self) -> set[str]:
        if self.var is not None:
            return {self.var}
        if self.const is not None:
            return set()
        if self.not_ is not None:
            return self.not_.variables()
        return set().union(*(e.variables() for e in (self.and_ or self.or_ or [])))

    def depth(self) -> int:
        if self.var is not None or self.const is not None:
            return 1
        if self.not_ is not None:
            return 1 + self.not_.depth()
        return 1 + max(e.depth() for e in (self.and_ or self.or_ or []))

    def evaluate(self, state: dict[str, Value]) -> Value:
        """Kleene logic: a not-computed operand decides nothing it cannot decide."""
        if self.const is not None:
            return self.const
        if self.var is not None:
            return state[self.var]
        if self.not_ is not None:
            inner = self.not_.evaluate(state)
            return None if inner is None else not inner
        values = [e.evaluate(state) for e in (self.and_ or self.or_ or [])]
        if self.and_ is not None:
            if False in values:
                return False
            return None if None in values else True
        if True in values:
            return True
        return None if None in values else False


class Component(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["input", "internal"] = Field(
        description="input: given by the scenario. internal: given by exactly one rule."
    )
    description: str | None = None


class Rule(BaseModel):
    """A candidate rule, recorded with who stated it and what it rests on. Not validated."""

    model_config = ConfigDict(extra="forbid")

    id: str
    target: str = Field(description="The internal component this rule computes.")
    expr: Expr
    evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    stated_by: Literal["host", "researcher"] = "host"
    note: str | None = None


class LogicModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str = "v0"
    description: str | None = None
    components: list[Component]
    rules: list[Rule] = Field(default_factory=list)
    update: str = Field(
        default="synchronous",
        description="Only 'synchronous' is supported; any other value is refused, not converted.",
    )

    @field_validator("update")
    @classmethod
    def _synchronous_only(cls, v: str) -> str:
        if v != "synchronous":
            raise ValueError(
                f"update {v!r} is not supported: v0 runs synchronous updates only, and does not "
                "convert another mode into it"
            )
        return v

    @model_validator(mode="after")
    def _consistent(self) -> LogicModel:
        if not self.components:
            raise ValueError("a model needs at least one component")
        if len(self.components) > MAX_COMPONENTS:
            raise ValueError(f"at most {MAX_COMPONENTS} components (an operational limit)")
        ids = [c.id for c in self.components]
        if len(set(ids)) != len(ids):
            raise ValueError("component ids must be unique")
        kinds = {c.id: c.kind for c in self.components}
        rule_ids = [r.id for r in self.rules]
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("rule ids must be unique")
        targets: dict[str, str] = {}
        for r in self.rules:
            if r.target not in kinds:
                raise ValueError(f"rule {r.id!r} targets {r.target!r}, which is not declared")
            if kinds[r.target] == "input":
                raise ValueError(
                    f"rule {r.id!r} targets input {r.target!r}; inputs are given by the "
                    "scenario, never by a rule"
                )
            if r.target in targets:
                raise ValueError(
                    f"{r.target!r} has two rules ({targets[r.target]!r}, {r.id!r}); one "
                    "component has one rule"
                )
            targets[r.target] = r.id
            unknown = sorted(r.expr.variables() - set(kinds))
            if unknown:
                raise ValueError(f"rule {r.id!r} reads undeclared components {unknown}")
            if r.expr.depth() > MAX_EXPR_DEPTH:
                raise ValueError(f"rule {r.id!r} is nested deeper than {MAX_EXPR_DEPTH}")
        return self

    def kind(self, component: str) -> str:
        return next(c.kind for c in self.components if c.id == component)

    def rule_for(self, component: str) -> Rule | None:
        return next((r for r in self.rules if r.target == component), None)

    def content_hash(self) -> str:
        """Over components and rules sorted by id, so listing order does not change it."""
        payload = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        payload["components"] = sorted(payload["components"], key=lambda c: c["id"])
        payload["rules"] = sorted(payload["rules"], key=lambda r: r["id"])
        return _sha(payload)


# --- the scenario ----------------------------------------------------------------------- #


class Segment(BaseModel):
    """An input's value over an inclusive range of state indices."""

    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int | None = Field(default=None, ge=0, description="Inclusive; null means to the end.")
    value: bool | Literal["unknown", "unknown_each_step"] = Field(
        description=(
            "unknown: one unknown value held over the whole segment. unknown_each_step: an "
            "independent unknown at every index of the segment."
        )
    )


class Clamp(BaseModel):
    """Fix a component or input over an inclusive range. The model itself is not changed."""

    model_config = ConfigDict(extra="forbid")

    target: str
    value: bool
    start: int = Field(ge=0, description="First state index fixed; rules for start+1 read it.")
    end: int | None = Field(
        default=None,
        ge=0,
        description="Last index fixed (inclusive). From end+1 the target's own rule applies again.",
    )


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    initial: dict[str, bool | Literal["unknown"]] = Field(
        description="Every internal component at state 0: true, false or 'unknown'."
    )
    inputs: dict[str, list[Segment]] = Field(default_factory=dict)
    clamps: list[Clamp] = Field(default_factory=list)


class ReadoutMapping(BaseModel):
    """How one model state is read by one measurement. Its basis is the caller's, not checked."""

    model_config = ConfigDict(extra="forbid")

    readout: str = Field(
        description="The readout's id. Unique within `readouts`: a repeated id is refused."
    )
    state: str = Field(description="The component the readout reads.")
    mapping: str = Field(
        default="identity",
        description="Only 'identity' in v0: active reads as present, inactive as absent.",
    )
    basis: str
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("mapping")
    @classmethod
    def _identity_only(cls, v: str) -> str:
        if v != "identity":
            raise ValueError(f"mapping {v!r} is not supported; v0 has 'identity' only")
        return v


# --- results ----------------------------------------------------------------------------- #


class StepSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    component: str
    t: int
    status: Literal[
        "same_in_all_explored",
        "differs_by_case",
        "not_computed",
        "partly_not_computed",
        "exploration_incomplete",
    ]
    value: bool | None = Field(default=None, description="Set only for same_in_all_explored.")
    cases_by_value: dict[str, int] = Field(
        default_factory=dict,
        description="How many logical cases gave each value. A count, not a probability.",
    )


class Repetition(BaseModel):
    model_config = ConfigDict(frozen=True)

    case: str
    constant_from: int | None = Field(
        description=(
            "Index from which the declared inputs and clamps no longer change, even if it lies "
            "after the last computed step; null if an input may change at every index without end."
        )
    )
    status: Literal["fixed_point", "cycle", "no_repeat_within_steps", "not_assessed"]
    from_step: int | None = None
    period: int | None = None
    reason: str | None = Field(
        default=None, description="Why repetition was not assessed, when it was not."
    )


class CaseRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    case: str
    assignment: dict[str, bool] = Field(default_factory=dict)
    path: list[dict[str, bool | None]]


class TraceEntry(BaseModel):
    """How one value in one case was obtained. A computation record, nothing more."""

    model_config = ConfigDict(frozen=True)

    case: str
    t: int
    component: str
    source: str
    read: dict[str, bool | None] = Field(default_factory=dict)
    value: bool | None


class RuleUse(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str
    target: str
    stated_by: str
    evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    validated: Literal[False] = False
    sides: list[str] = Field(
        default_factory=list,
        description="In a relative dependency: which runs used the rule (scenario, baseline).",
    )


class Dependency(BaseModel):
    """What a final value was computed from, across the explored cases. Not a cause."""

    model_config = ConfigDict(frozen=True)

    component: str
    t: int
    computed_from: list[str]
    rules: list[RuleUse] = Field(default_factory=list)


class RelativeDependency(BaseModel):
    """What a readout's comparison with the baseline was computed from, on both sides.

    The scenario's value and the baseline's value are each traced on their own, so a rule the
    baseline used is listed even when the scenario clamped its target and used none. Not a
    cause, an only cause or a minimal cause.
    """

    model_config = ConfigDict(frozen=True)

    readout: str
    state: str
    t: int
    scenario_computed_from: list[str]
    baseline_computed_from: list[str]
    rules: list[RuleUse] = Field(default_factory=list)


class Difference(BaseModel):
    model_config = ConfigDict(frozen=True)

    component: str
    t: int
    status: Literal["same", "differs", "undetermined"]
    scenario: bool | None = None
    baseline: bool | None = None


class PairedDifference(BaseModel):
    model_config = ConfigDict(frozen=True)

    case: str
    component: str
    t: int
    scenario: bool | None
    baseline: bool | None


class ReadoutState(BaseModel):
    model_config = ConfigDict(frozen=True)

    readout: str
    t: int
    state: Literal["present", "absent", "undetermined", "not_computed", "not_derivable"]
    versus_baseline: (
        Literal["increase", "decrease", "no_change", "undetermined", "no_baseline"] | None
    ) = None
    paired: dict[str, str] = Field(
        default_factory=dict, description="Per case, when the baseline has the same unknowns."
    )


class WindowRequest(BaseModel):
    """Which logical steps and which components or readouts a window summary reads."""

    model_config = ConfigDict(extra="forbid")

    first: int = Field(ge=0, description="First state index read (inclusive).")
    last: int = Field(
        ge=0, description="Last state index read (inclusive); at most `steps`. first <= last."
    )
    targets: list[str] = Field(
        min_length=1,
        description=(
            "Component ids or readout ids (from `readouts`). A name that is neither, a name "
            "that is both, or a repeated name is refused."
        ),
    )


class WindowGroup(BaseModel):
    """Cases whose window falls in one class, with the same known values and gaps."""

    model_config = ConfigDict(frozen=True)

    window_class: Literal[
        "all_active", "all_inactive", "both_values", "partly_not_computed", "not_computed"
    ]
    known_values: list[bool] = Field(description="The computed values seen in the window.")
    not_computed_steps: list[int] = Field(
        default_factory=list, description="State indices in the window with no computed value."
    )
    cases: list[int] = Field(
        description=(
            "Positions in `window.cases` (or, for an unpaired baseline, `window.baseline_cases`). "
            "How many there are counts combinations; it is not a weight."
        )
    )


class WindowSide(BaseModel):
    model_config = ConfigDict(frozen=True)

    groups: list[WindowGroup] = Field(
        description="Split on class, known values and not-computed steps, so two groups can "
        "share a class."
    )
    across_cases: Literal["same_class", "differs_by_case"] = Field(
        description="Whether every explored case has the same window_class. Groups and "
        "identical_paths carry the finer detail."
    )
    identical_paths: bool = Field(
        description="Every explored case has the same value sequence in the window. Same class "
        "is not same path: 0101 and 1010 are both both_values."
    )
    applies_to: Literal["all_cases", "explored_cases_only"]


class DirectionGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    directions: list[str] = Field(
        description="The directions the case gives over the window's steps, all of them."
    )
    cases: list[int] = Field(description="Positions in `window.cases`.")


class WindowPaired(BaseModel):
    """Per-case, per-step directions against the baseline, gathered over the window."""

    model_config = ConfigDict(frozen=True)

    groups: list[DirectionGroup]
    directions: list[str] = Field(description="Every direction seen in the explored cases.")
    applies_to: Literal["all_cases", "explored_cases_only"]


class WindowPairing(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["paired", "not_paired", "no_baseline"]
    basis: str


class WindowTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    target: str
    kind: Literal["component", "readout"]
    state: str = Field(description="The component read; a readout reads its state (identity).")
    scenario: WindowSide
    baseline: WindowSide | None = None
    paired: WindowPaired | None = None


class WindowRun(BaseModel):
    """A summary of the run's own case paths over a window. Not a measurement model."""

    model_config = ConfigDict(frozen=True)

    request: WindowRequest
    request_sha256: str = Field(description="Of the run hash and this request (targets sorted).")
    run_sha256: str
    constant_from: int | None = Field(
        description="The scenario's index after which declared inputs and clamps stop changing."
    )
    baseline_constant_from: int | None = None
    declared_change_after_window: bool = Field(
        description="Either side declares a change after `last`; a constant window then says "
        "nothing about what follows."
    )
    pairing: WindowPairing
    cases: list[str] = Field(
        description="The scenario's explored case labels, in the engine's order. A paired "
        "baseline has the same labels."
    )
    baseline_cases: list[str] | None = Field(
        default=None, description="The baseline's explored case labels, when they differ."
    )
    targets: list[WindowTarget]
    final_step_only: list[str] = Field(
        default_factory=list,
        description="Fields of this response that describe the last step, not the window.",
    )
    limits: list[str] = Field(default_factory=list)


WINDOW_LIMITS: tuple[str, ...] = (
    "A window class summarises the run's own computed values. It is not a measured level: "
    "both_values is not an intermediate level and not a cycle, and a constant window is not a "
    "fixed point (a one-step window is constant by definition).",
    "Steps are logical updates, not time; the share of steps a state is active is not a share "
    "of time, a concentration or a probability.",
    "Groups list case labels. Their sizes count logical combinations, not cells, weights or "
    "probabilities.",
    "Directions are paired per case and per step from the same case labels; two classes are "
    "never compared to make a direction. With exploration incomplete, they describe the "
    "explored cases only.",
    "Two equal Boolean states give no_change. That is not a computed equality of measured levels.",
)


class LogicRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim: str = (
        "If this candidate model and these conditions held, this is what the rules compute. It "
        "does not say the model is true of any cell."
    )
    model_id: str
    model_version: str
    model_sha256: str
    run_sha256: str
    update: Literal["synchronous"] = "synchronous"
    steps: int
    step_meaning: str = "A logical update. Not a unit of time; no duration is computed."
    scenario: Scenario
    baseline: Scenario | None = None
    unknowns: list[str] = Field(default_factory=list)
    cases_total: int
    cases_explored: int
    exploration_complete: bool
    summary: list[StepSummary] | None = Field(
        description="Every component at every step. null in the window view (not sent)."
    )
    final: list[StepSummary]
    repetition: list[Repetition]
    differences: list[Difference] | None = Field(default_factory=list)
    paired_differences: list[PairedDifference] | None = Field(default_factory=list)
    dependencies: list[Dependency] = Field(
        default_factory=list,
        description="What the scenario's own final values were computed from.",
    )
    baseline_dependencies: list[Dependency] = Field(
        default_factory=list,
        description="What the baseline's final values were computed from. Empty without one.",
    )
    relative_dependencies: list[RelativeDependency] = Field(
        default_factory=list,
        description="Per readout, both sides of the comparison. Empty without a baseline.",
    )
    readouts: list[ReadoutState] | None = Field(default_factory=list)
    readouts_not_derivable: list[str] = Field(default_factory=list)
    prediction_drafts: list[dict[str, Any]] = Field(default_factory=list)
    not_computed: list[str] = Field(default_factory=list)
    limits_reached: list[str] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)
    view: Literal["summary", "full", "window"] = "summary"
    window: WindowRun | None = None
    cases: list[CaseRun] | None = None
    baseline_cases: list[CaseRun] | None = None
    trace: list[TraceEntry] | None = None
    omitted: list[str] = Field(default_factory=list)


LIMITS: tuple[str, ...] = (
    "Everything here follows from the rules as stated. The rules are candidates; their evidence "
    "ids and assumptions are carried, not checked.",
    "A step is a logical update. Nothing here is a time, a rate, a half-life or a dose.",
    "Active and inactive are the model's abstract states. They are not concentrations, "
    "detections or expression levels unless a readout mapping says how one is read.",
    "A clamp is an ideal intervention. That a wash or an inhibitor achieved it is not shown.",
    "Counts of cases are counts of logical combinations, not probabilities.",
    "'Computed from' lists what a value was computed from in the unrolled steps. It is not a "
    "claim that any one rule is the cause, the only cause or the minimal cause.",
)


# --- running ------------------------------------------------------------------------------ #


def _sha(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _canonical_scenario(s: Scenario) -> dict[str, Any]:
    d = s.model_dump(mode="json")
    d["inputs"] = {
        k: sorted(v, key=lambda g: (g["start"], -1 if g["end"] is None else g["end"]))
        for k, v in sorted(d["inputs"].items())
    }
    d["clamps"] = sorted(d["clamps"], key=lambda c: (c["target"], c["start"], str(c["end"])))
    return d


def _covers(start: int, end: int | None, t: int) -> bool:
    return start <= t and (end is None or t <= end)


def _check_scenario(model: LogicModel, s: Scenario, steps: int) -> None:
    internals = sorted(c.id for c in model.components if c.kind == "internal")
    inputs = sorted(c.id for c in model.components if c.kind == "input")
    missing = [c for c in internals if c not in s.initial]
    if missing:
        raise LogicModelError(
            f"scenario {s.name!r}: no initial value for {missing}; give true, false or 'unknown' "
            "(nothing is assumed inactive)"
        )
    extra = sorted(set(s.initial) - set(internals))
    if extra:
        raise LogicModelError(
            f"scenario {s.name!r}: initial values for {extra}, which are not internal components "
            "(inputs come from `inputs`)"
        )
    bad_inputs = sorted(set(s.inputs) - set(inputs))
    if bad_inputs:
        raise LogicModelError(f"scenario {s.name!r}: {bad_inputs} are not declared inputs")
    for name, segments in s.inputs.items():
        for a, b in product(segments, segments):
            if a is b:
                continue
            lo, hi = (
                max(a.start, b.start),
                min(a.end if a.end is not None else steps, b.end if b.end is not None else steps),
            )
            if lo <= hi:
                raise LogicModelError(
                    f"scenario {s.name!r}: input {name!r} has overlapping segments; give one value "
                    "per index"
                )
    declared = {c.id for c in model.components}
    for c in s.clamps:
        if c.target not in declared:
            raise LogicModelError(f"scenario {s.name!r}: clamp on undeclared {c.target!r}")
        if c.end is not None and c.end < c.start:
            raise LogicModelError(
                f"scenario {s.name!r}: clamp on {c.target!r} ends before it starts"
            )
    for a, b in product(s.clamps, s.clamps):
        if a is b or a.target != b.target or a.value == b.value:
            continue
        lo = max(a.start, b.start)
        hi = min(a.end if a.end is not None else steps, b.end if b.end is not None else steps)
        if lo <= hi:
            raise LogicModelError(
                f"scenario {s.name!r}: conflicting clamps on {a.target!r} over indices {lo}-{hi} "
                "(true and false); neither is chosen by order"
            )


def _unknown_labels(s: Scenario, steps: int) -> list[str]:
    labels = [f"{c}" for c, v in s.initial.items() if v == "unknown"]
    for name, segments in s.inputs.items():
        for g in segments:
            end = "end" if g.end is None else str(g.end)
            if g.value == "unknown":
                labels.append(f"{name}[{g.start}:{end}]")
            elif g.value == "unknown_each_step":
                last = steps if g.end is None else min(g.end, steps)
                labels.extend(f"{name}@{t}" for t in range(g.start, last + 1))
    return sorted(labels)


def _constant_from(s: Scenario) -> int | None:
    """The index after which the declared inputs and clamps no longer change.

    Change points after the last computed step are kept: a change the scenario declares at
    index 11 still matters to a run of 3 steps, which just cannot see it. (An earlier version
    dropped them, and a 3-step run reported a fixed point the scenario itself ends at 11.)
    An input that may change at every index never becomes constant while it lasts; a bounded
    one becomes constant after its end, like any other segment boundary.
    """
    if any(
        g.value == "unknown_each_step" and g.end is None for gs in s.inputs.values() for g in gs
    ):
        return None
    points = [0]
    for gs in s.inputs.values():
        for g in gs:
            points.append(g.start)
            if g.end is not None:
                points.append(g.end + 1)
    for c in s.clamps:
        points.append(c.start)
        if c.end is not None:
            points.append(c.end + 1)
    return max(points)


class _Case:
    def __init__(self, label: str, assignment: dict[str, bool]) -> None:
        self.label = label
        self.assignment = assignment
        self.path: list[dict[str, Value]] = []
        self.source: dict[tuple[str, int], tuple[str, dict[str, Value]]] = {}


def _input_value(s: Scenario, name: str, t: int, assignment: dict[str, bool]) -> tuple[Value, str]:
    for g in s.inputs.get(name, []):
        if _covers(g.start, g.end, t):
            end = "end" if g.end is None else str(g.end)
            if g.value == "unknown":
                return assignment[f"{name}[{g.start}:{end}]"], f"input:{name}[{g.start}:{end}]"
            if g.value == "unknown_each_step":
                return assignment[f"{name}@{t}"], f"input:{name}@{t}"
            return g.value, f"input:{name}[{g.start}:{end}]"
    return None, f"input:{name}@{t}:missing"


def _clamp_at(s: Scenario, name: str, t: int) -> Clamp | None:
    return next((c for c in s.clamps if c.target == name and _covers(c.start, c.end, t)), None)


def _simulate(model: LogicModel, s: Scenario, steps: int, case: _Case) -> None:
    ids = sorted(c.id for c in model.components)
    for t in range(steps + 1):
        state: dict[str, Value] = {}
        for cid in ids:
            clamp = _clamp_at(s, cid, t)
            if clamp is not None:
                end = "end" if clamp.end is None else str(clamp.end)
                state[cid] = clamp.value
                case.source[(cid, t)] = (f"clamp:{cid}[{clamp.start}:{end}]", {})
            elif model.kind(cid) == "input":
                value, src = _input_value(s, cid, t, case.assignment)
                state[cid] = value
                case.source[(cid, t)] = (src, {})
            elif t == 0:
                v = s.initial[cid]
                state[cid] = case.assignment[cid] if v == "unknown" else v
                case.source[(cid, t)] = (f"initial:{cid}", {})
            else:
                rule = model.rule_for(cid)
                previous = case.path[t - 1]
                if rule is None:
                    state[cid] = None
                    case.source[(cid, t)] = (f"no_rule:{cid}", {})
                else:
                    read = {v: previous[v] for v in sorted(rule.expr.variables())}
                    state[cid] = rule.expr.evaluate(previous)
                    case.source[(cid, t)] = (f"rule:{rule.id}", read)
        case.path.append(state)


def _computed_from(model: LogicModel, case: _Case, cid: str, t: int, seen: set) -> set[str]:
    if (cid, t) in seen:
        return set()
    seen.add((cid, t))
    source, read = case.source[(cid, t)]
    out = {source}
    if source.startswith("rule:"):
        for v in read:
            out |= _computed_from(model, case, v, t - 1, seen)
    return out


def _summaries(
    model: LogicModel, cases: list[_Case], steps: int, complete: bool
) -> list[StepSummary]:
    out = []
    for cid in sorted(c.id for c in model.components):
        for t in range(steps + 1):
            values = [c.path[t][cid] for c in cases]
            counts: dict[str, int] = {}
            for v in values:
                key = "not_computed" if v is None else str(v).lower()
                counts[key] = counts.get(key, 0) + 1
            distinct = set(values)
            if not complete:
                status, value = "exploration_incomplete", None
            elif distinct == {None}:
                status, value = "not_computed", None
            elif None in distinct:
                status, value = "partly_not_computed", None
            elif len(distinct) == 1:
                status, value = "same_in_all_explored", values[0]
            else:
                status, value = "differs_by_case", None
            out.append(
                StepSummary(component=cid, t=t, status=status, value=value, cases_by_value=counts)
            )
    return out


def _repetition(s: Scenario, steps: int, case: _Case) -> Repetition:
    """A repeat of a fully computed state, inside a range where nothing declared changes.

    Not computed (None) marks a value that could not be computed, so a state holding one is
    not a known state: two of them comparing equal is not a Boolean fixed point or cycle. Only
    states with every component computed are compared, and a repeat is looked for only from
    the index after which the declared inputs and clamps stop changing. When that index lies
    after the last computed step, nothing is assessed: the computed path is kept as it is.
    """
    k = _constant_from(s)
    if k is None:
        return Repetition(
            case=case.label,
            constant_from=None,
            status="not_assessed",
            reason="an input may change at every index without end",
        )
    if k > steps:
        return Repetition(
            case=case.label,
            constant_from=k,
            status="not_assessed",
            reason=(
                f"the scenario declares a change at index {k}, after the last computed step "
                f"{steps}; a repeat inside the computed range says nothing about the scenario"
            ),
        )
    path = case.path
    complete = [None not in state.values() for state in path]
    for start in range(k, steps + 1):
        if not complete[start]:
            continue
        for period in range(1, steps - start + 1):
            if path[start] == path[start + period]:
                if period == 1:
                    return Repetition(
                        case=case.label, constant_from=k, status="fixed_point", from_step=start
                    )
                return Repetition(
                    case=case.label,
                    constant_from=k,
                    status="cycle",
                    from_step=start,
                    period=period,
                )
    if not all(complete[k:]):
        return Repetition(
            case=case.label,
            constant_from=k,
            status="not_assessed",
            reason=(
                "states after the inputs stop changing contain not-computed values; a repeat "
                "among them is not a known fixed point or cycle"
            ),
        )
    return Repetition(case=case.label, constant_from=k, status="no_repeat_within_steps")


def _run_cases(
    model: LogicModel, s: Scenario, steps: int, max_cases: int
) -> tuple[list[_Case], list[str], int]:
    labels = _unknown_labels(s, steps)
    total = 2 ** len(labels)
    cases: list[_Case] = []
    for values in product((False, True), repeat=len(labels)):
        if len(cases) >= max_cases:
            break
        assignment = dict(zip(labels, values, strict=True))
        label = ",".join(f"{k}={int(v)}" for k, v in assignment.items()) or "all"
        case = _Case(label, assignment)
        _simulate(model, s, steps, case)
        cases.append(case)
    return cases, labels, total


def _readout(value: bool | None) -> str:
    return "not_computed" if value is None else ("present" if value else "absent")


def _direction(scenario: bool | None, baseline: bool | None) -> str:
    if scenario is None or baseline is None:
        return "undetermined"
    if scenario == baseline:
        return "no_change"
    return "increase" if scenario else "decrease"


def run_logic(
    model: LogicModel,
    scenario: Scenario,
    steps: int,
    *,
    baseline: Scenario | None = None,
    readouts: list[ReadoutMapping] | None = None,
    readouts_requested: list[str] | None = None,
    hypothesis_id: str | None = None,
    max_cases: int = DEFAULT_MAX_CASES,
    view: Literal["summary", "full", "window"] = "summary",
    window: WindowRequest | None = None,
) -> LogicRun:
    """Run `scenario` (and `baseline`, if given) on `model`. Neither is modified."""
    if not 1 <= steps <= MAX_STEPS:
        raise LogicModelError(f"steps must be between 1 and {MAX_STEPS} (an operational limit)")
    if not 1 <= max_cases <= MAX_CASES:
        raise LogicModelError(f"max_cases must be between 1 and {MAX_CASES}")
    readouts = list(readouts or [])
    declared = {c.id for c in model.components}
    _unique_readouts(readouts)
    targets = _window_targets(window, view, steps, declared, readouts)
    for m in readouts:
        if m.state not in declared:
            raise LogicModelError(f"readout {m.readout!r} reads undeclared {m.state!r}")
    _check_scenario(model, scenario, steps)
    if baseline is not None:
        _check_scenario(model, baseline, steps)
        if baseline.initial != scenario.initial:
            raise LogicModelError(
                "the baseline must start from the same initial state as the scenario; a "
                "difference would then not be the intervention's"
            )

    cases, labels, total = _run_cases(model, scenario, steps, max_cases)
    complete = len(cases) == total
    summary = _summaries(model, cases, steps, complete)
    limits_reached = []
    if not complete:
        limits_reached.append(
            f"{total} cases from {len(labels)} unknowns; {len(cases)} explored (max_cases). "
            "Nothing is reported as the same in all cases."
        )

    base_cases: list[_Case] = []
    base_summary: list[StepSummary] = []
    differences: list[Difference] = []
    paired: list[PairedDifference] = []
    base_complete = True
    if baseline is not None:
        base_cases, base_labels, base_total = _run_cases(model, baseline, steps, max_cases)
        base_complete = len(base_cases) == base_total
        if not base_complete:
            limits_reached.append(f"baseline: {len(base_cases)} of {base_total} cases explored.")
        base_summary = _summaries(model, base_cases, steps, base_complete)
        by_key = {(b.component, b.t): b for b in base_summary}
        for a in summary:
            b = by_key[(a.component, a.t)]
            if a.status == b.status == "same_in_all_explored":
                differences.append(
                    Difference(
                        component=a.component,
                        t=a.t,
                        status="same" if a.value == b.value else "differs",
                        scenario=a.value,
                        baseline=b.value,
                    )
                )
            else:
                differences.append(Difference(component=a.component, t=a.t, status="undetermined"))
        if base_labels == labels and complete and base_complete:
            for ca, cb in zip(cases, base_cases, strict=True):
                for cid in sorted(declared):
                    for t in range(steps + 1):
                        if ca.path[t][cid] != cb.path[t][cid]:
                            paired.append(
                                PairedDifference(
                                    case=ca.label,
                                    component=cid,
                                    t=t,
                                    scenario=ca.path[t][cid],
                                    baseline=cb.path[t][cid],
                                )
                            )

    dependencies = _dependencies(model, cases, steps)
    baseline_dependencies = _dependencies(model, base_cases, steps) if baseline else []

    readout_states: list[ReadoutState] = []
    by_summary = {(s.component, s.t): s for s in summary}
    by_base = {(s.component, s.t): s for s in base_summary}
    for m in sorted(readouts, key=lambda r: r.readout):
        for t in range(steps + 1):
            a = by_summary[(m.state, t)]
            if a.status == "same_in_all_explored":
                state = _readout(a.value)
            elif a.status == "not_computed":
                state = "not_computed"
            else:
                state = "undetermined"
            versus = "no_baseline"
            per_case: dict[str, str] = {}
            if baseline is not None:
                b = by_base[(m.state, t)]
                both = a.status == b.status == "same_in_all_explored"
                versus = _direction(a.value, b.value) if both else "undetermined"
                if base_cases and [c.label for c in base_cases] == [c.label for c in cases]:
                    for ca, cb in zip(cases, base_cases, strict=True):
                        per_case[ca.label] = _direction(ca.path[t][m.state], cb.path[t][m.state])
            readout_states.append(
                ReadoutState(
                    readout=m.readout, t=t, state=state, versus_baseline=versus, paired=per_case
                )
            )

    not_computed = sorted(
        {
            f"{cid}: no rule"
            for cid in declared
            if model.kind(cid) == "internal" and model.rule_for(cid) is None
        }
        | {
            f"{src.split(':', 1)[1].rsplit(':', 1)[0]}: no input value"
            for case in cases
            for (_, _), (src, _) in case.source.items()
            if src.endswith(":missing")
        }
    )

    model_hash = model.content_hash()
    run_hash = _sha(
        {
            "model": model_hash,
            "scenario": _canonical_scenario(scenario),
            "baseline": _canonical_scenario(baseline) if baseline else None,
            "steps": steps,
            "readouts": sorted(
                (m.model_dump(mode="json") for m in readouts), key=lambda r: r["readout"]
            ),
            "max_cases": max_cases,
        }
    )
    relative = (
        _relative(model, readouts, dependencies, baseline_dependencies, steps) if baseline else []
    )
    drafts = (
        _drafts(
            model,
            model_hash,
            scenario,
            baseline,
            steps,
            readouts,
            readout_states,
            hypothesis_id,
            dependencies,
            relative,
        )
        if hypothesis_id
        else []
    )
    full = view == "full"
    window_run = None
    if window is not None:
        window_run = _window(
            window,
            targets,
            run_hash,
            scenario,
            baseline,
            cases,
            base_cases,
            complete,
            base_complete,
        )
    windowed = window_run is not None
    window_states = {state for _, _, state in targets} if windowed else None
    window_readouts = {name for name, kind, _ in targets if kind == "readout"} if windowed else None
    return LogicRun(
        model_id=model.id,
        model_version=model.version,
        model_sha256=model_hash,
        run_sha256=run_hash,
        steps=steps,
        scenario=scenario,
        baseline=baseline,
        unknowns=labels,
        cases_total=total,
        cases_explored=len(cases),
        exploration_complete=complete,
        summary=None if windowed else summary,
        final=[s for s in summary if s.t == steps],
        repetition=[_repetition(scenario, steps, c) for c in cases],
        differences=None if windowed else differences,
        paired_differences=None if windowed else paired,
        dependencies=_only(dependencies, window_states, "component"),
        baseline_dependencies=_only(baseline_dependencies, window_states, "component"),
        relative_dependencies=_only(relative, window_readouts, "readout"),
        readouts=None if windowed else readout_states,
        readouts_not_derivable=sorted(
            set(readouts_requested or []) - {m.readout for m in readouts}
        ),
        prediction_drafts=drafts,
        not_computed=not_computed,
        limits_reached=limits_reached,
        limits=list(LIMITS),
        view=view,
        window=window_run,
        cases=[_case_run(c) for c in cases] if full else None,
        baseline_cases=[_case_run(c) for c in base_cases] if full and baseline else None,
        trace=_trace(cases) if full else None,
        omitted=[]
        if full
        else list(WINDOW_OMITTED)
        if windowed
        else [
            "cases: each case's state path. Call again with view='full'.",
            "baseline_cases and trace: the rule applied, the values it read and its result, per "
            "case, step and component. Call again with view='full'.",
        ],
    )


def _only(items: list, keep: set[str] | None, field: str) -> list:
    """In the window view, the final-step traces of the window's targets only."""
    return items if keep is None else [i for i in items if getattr(i, field) in keep]


WINDOW_OMITTED: tuple[str, ...] = (
    "summary, differences, paired_differences and readouts (every component or readout at "
    "every step, with per-case directions): null here. Call again with view='summary'.",
    "cases, baseline_cases and trace (every case path and the rule-application trace): call "
    "again with view='full'.",
    "dependencies, baseline_dependencies and relative_dependencies of components and readouts "
    "outside the window's targets: call again with view='summary'.",
)


def _unique_readouts(readouts: list[ReadoutMapping]) -> None:
    """Refuse a readout id declared twice; nothing is renamed and no declaration is chosen."""
    seen: dict[str, int] = {}
    for position, m in enumerate(readouts):
        if m.readout in seen:
            raise LogicModelError(
                f"readout id {m.readout!r} is declared at positions {seen[m.readout]} and "
                f"{position} of `readouts` (counting from 0); readout ids must be unique. Rename "
                "or remove one; neither is chosen"
            )
        seen[m.readout] = position


def _window_targets(
    window: WindowRequest | None,
    view: str,
    steps: int,
    declared: set[str],
    readouts: list[ReadoutMapping],
) -> list[tuple[str, str, str]]:
    """Check a window request against the run; refuse what it cannot read, never adjust it."""
    if view == "window" and window is None:
        raise LogicModelError("view 'window' needs a `window` {first, last, targets}")
    if window is None:
        return []
    if view != "window":
        raise LogicModelError(
            "a `window` is read only with view 'window', so that a summary is never mistaken "
            "for a full result"
        )
    if window.first > window.last:
        raise LogicModelError(f"window first {window.first} is after last {window.last}")
    if window.last > steps:
        raise LogicModelError(f"window last {window.last} is after the last step {steps}")
    by_readout = {m.readout: m.state for m in readouts}
    out = []
    for name in window.targets:
        if window.targets.count(name) > 1:
            raise LogicModelError(f"window target {name!r} is repeated")
        if name in declared and name in by_readout:
            raise LogicModelError(
                f"window target {name!r} is both a component and a readout; rename the readout"
            )
        if name in declared:
            out.append((name, "component", name))
        elif name in by_readout:
            out.append((name, "readout", by_readout[name]))
        else:
            raise LogicModelError(
                f"window target {name!r} is neither a declared component nor a readout"
            )
    return sorted(out)


def _window_class(values: list[Value]) -> tuple[str, list[bool], list[int]]:
    known = sorted({v for v in values if v is not None})
    gaps = [i for i, v in enumerate(values) if v is None]
    if len(gaps) == len(values):
        return "not_computed", known, gaps
    if gaps:
        return "partly_not_computed", known, gaps
    if known == [True]:
        return "all_active", known, gaps
    if known == [False]:
        return "all_inactive", known, gaps
    return "both_values", known, gaps


def _window_side(
    cases: list[_Case], state: str, first: int, last: int, complete: bool
) -> WindowSide:
    """Group cases by window class; a group names its cases by position, so no label is lost."""
    groups: dict[tuple, list[str]] = {}
    sequences = set()
    for index, case in enumerate(cases):
        values = [case.path[t][state] for t in range(first, last + 1)]
        sequences.add(tuple(values))
        cls, known, gaps = _window_class(values)
        key = (cls, tuple(known), tuple(first + i for i in gaps))
        groups.setdefault(key, []).append(index)
    return WindowSide(
        groups=[
            WindowGroup(
                window_class=cls,
                known_values=list(known),
                not_computed_steps=list(gaps),
                cases=labels,
            )
            for (cls, known, gaps), labels in groups.items()
        ],
        # The class alone decides: groups also split on known values and gaps, which is detail.
        across_cases="same_class" if len({key[0] for key in groups}) == 1 else "differs_by_case",
        identical_paths=len(sequences) == 1,
        applies_to="all_cases" if complete else "explored_cases_only",
    )


def _window(
    window: WindowRequest,
    targets: list[tuple[str, str, str]],
    run_hash: str,
    scenario: Scenario,
    baseline: Scenario | None,
    cases: list[_Case],
    base_cases: list[_Case],
    complete: bool,
    base_complete: bool,
) -> WindowRun:
    request = WindowRequest(
        first=window.first, last=window.last, targets=[name for name, _, _ in targets]
    )
    first, last = request.first, request.last
    if baseline is None:
        pairing = WindowPairing(status="no_baseline", basis="no baseline was given")
    elif [c.label for c in base_cases] == [c.label for c in cases]:
        pairing = WindowPairing(
            status="paired",
            basis=(
                "scenario and baseline expanded the same unknowns, so each explored case is "
                "paired with the baseline case of the same label (as for per-case readout "
                "directions)"
            ),
        )
    else:
        pairing = WindowPairing(
            status="not_paired",
            basis=(
                "the explored cases of scenario and baseline do not carry the same labels (the "
                "unknowns differ), so no case is paired; no direction is given"
            ),
        )
    both_complete = complete and (baseline is None or base_complete)
    out = []
    for name, kind, state in targets:
        paired = None
        if pairing.status == "paired":
            groups: dict[tuple[str, ...], list[str]] = {}
            for index, (ca, cb) in enumerate(zip(cases, base_cases, strict=True)):
                found = tuple(
                    sorted(
                        {
                            _direction(ca.path[t][state], cb.path[t][state])
                            for t in range(first, last + 1)
                        }
                    )
                )
                groups.setdefault(found, []).append(index)
            paired = WindowPaired(
                groups=[DirectionGroup(directions=list(d), cases=c) for d, c in groups.items()],
                directions=sorted({d for found in groups for d in found}),
                applies_to="all_cases" if both_complete else "explored_cases_only",
            )
        out.append(
            WindowTarget(
                target=name,
                kind=kind,
                state=state,
                scenario=_window_side(cases, state, first, last, complete),
                baseline=_window_side(base_cases, state, first, last, base_complete)
                if baseline is not None
                else None,
                paired=paired,
            )
        )
    constant = _constant_from(scenario)
    base_constant = _constant_from(baseline) if baseline is not None else None
    sides = [constant] + ([base_constant] if baseline is not None else [])
    return WindowRun(
        request=request,
        request_sha256=_sha({"run": run_hash, "window": request.model_dump(mode="json")}),
        run_sha256=run_hash,
        constant_from=constant,
        baseline_constant_from=base_constant,
        declared_change_after_window=any(k is None or k > last for k in sides),
        pairing=pairing,
        cases=[c.label for c in cases],
        baseline_cases=[c.label for c in base_cases]
        if baseline is not None and pairing.status != "paired"
        else None,
        targets=out,
        final_step_only=[
            "final",
            "dependencies",
            "baseline_dependencies",
            "relative_dependencies",
            "prediction_drafts",
        ],
        limits=list(WINDOW_LIMITS),
    )


def _rule_use(rule: Rule, sides: list[str] | None = None) -> RuleUse:
    return RuleUse(
        rule_id=rule.id,
        target=rule.target,
        stated_by=rule.stated_by,
        evidence_ids=list(rule.evidence_ids),
        assumptions=list(rule.assumptions),
        sides=sides or [],
    )


def _dependencies(model: LogicModel, cases: list[_Case], steps: int) -> list[Dependency]:
    rules_by_id = {r.id: r for r in model.rules}
    out = []
    for cid in sorted(c.id for c in model.components):
        sources: set[str] = set()
        for case in cases:
            sources |= _computed_from(model, case, cid, steps, set())
        used = sorted(s.split(":", 1)[1] for s in sources if s.startswith("rule:"))
        out.append(
            Dependency(
                component=cid,
                t=steps,
                computed_from=sorted(sources),
                rules=[_rule_use(rules_by_id[rid]) for rid in used],
            )
        )
    return out


def _relative(model, readouts, deps, base_deps, steps) -> list[RelativeDependency]:
    rules_by_id = {r.id: r for r in model.rules}
    mine = {d.component: d for d in deps}
    theirs = {d.component: d for d in base_deps}
    out = []
    for m in sorted(readouts, key=lambda r: r.readout):
        a, b = mine[m.state], theirs[m.state]
        sides: dict[str, list[str]] = {}
        for side, dep in (("scenario", a), ("baseline", b)):
            for u in dep.rules:
                sides.setdefault(u.rule_id, []).append(side)
        out.append(
            RelativeDependency(
                readout=m.readout,
                state=m.state,
                t=steps,
                scenario_computed_from=list(a.computed_from),
                baseline_computed_from=list(b.computed_from),
                rules=[_rule_use(rules_by_id[rid], sides[rid]) for rid in sorted(sides)],
            )
        )
    return out


def _case_run(case: _Case) -> CaseRun:
    return CaseRun(case=case.label, assignment=case.assignment, path=case.path)


def _trace(cases: list[_Case]) -> list[TraceEntry]:
    out = []
    for case in cases:
        for (cid, t), (source, read) in sorted(
            case.source.items(), key=lambda kv: (kv[0][1], kv[0][0])
        ):
            out.append(
                TraceEntry(
                    case=case.label,
                    t=t,
                    component=cid,
                    source=source,
                    read=read,
                    value=case.path[t][cid],
                )
            )
    return out


def _drafts(
    model, model_hash, scenario, baseline, steps, readouts, states, hypothesis_id, deps, relative
):
    """Prediction drafts for the final step. Basis `assumption`; never observed evidence.

    Against a baseline, the draft rests on both sides: the rules, evidence ids and assumptions
    behind the scenario's value and behind the baseline's value. A rule only the baseline used
    (its target clamped in the scenario, say) is still a rule the comparison rests on.
    """
    out = []
    final = {(r.readout, r.t): r for r in states}
    by_dep = {d.component: d for d in deps}
    by_rel = {d.readout: d for d in relative}
    for m in sorted(readouts, key=lambda r: r.readout):
        r = final[(m.readout, steps)]
        if baseline is None:
            rules = by_dep[m.state].rules
            computed = (
                f"Computed by logic model {model.id} {model.version} (sha256 "
                f"{model_hash[:12]}), synchronous update, logical step {steps}, from rules "
                f"{[u.rule_id for u in rules]} stated by "
                f"{sorted({u.stated_by for u in rules}) or ['nobody']}; not observed."
            )
        else:
            rules = by_rel[m.readout].rules
            side = {
                name: [u.rule_id for u in rules if name in u.sides]
                for name in ("scenario", "baseline")
            }
            computed = (
                f"Computed by logic model {model.id} {model.version} (sha256 "
                f"{model_hash[:12]}), synchronous update, logical step {steps}: scenario "
                f"{scenario.name!r} from rules {side['scenario']}, baseline {baseline.name!r} "
                f"from rules {side['baseline']}, stated by "
                f"{sorted({u.stated_by for u in rules}) or ['nobody']}; not observed."
            )
        assumptions = [computed, *m.assumptions]
        for u in rules:
            assumptions.extend(a for a in u.assumptions if a not in assumptions)
        if baseline is not None:
            expected = (
                r.versus_baseline
                if r.versus_baseline in ("increase", "decrease", "no_change")
                else "not_predicted"
            )
            versus = f"scenario {baseline.name!r} at logical step {steps}"
        else:
            expected = r.state if r.state in ("present", "absent") else "not_predicted"
            versus = None
        draft = {
            "hypothesis_id": hypothesis_id,
            "readout": m.readout,
            "expected": expected,
            "condition": f"scenario {scenario.name!r}, logical step {steps}",
            "basis": "assumption",
            "evidence_ids": sorted({e for u in rules for e in u.evidence_ids}),
            "assumptions": assumptions,
            "note": f"Computed from a candidate model, not observed. Readout basis: {m.basis}",
        }
        if versus is not None:
            draft["versus"] = versus
        if expected == "not_predicted":
            draft["unresolved"] = (
                "The model gives different values across cases or could not compute this; "
                "see the run's summary."
            )
        out.append(draft)
    return out


Expr.model_rebuild()
