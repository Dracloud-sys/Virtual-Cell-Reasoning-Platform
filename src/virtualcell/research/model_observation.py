"""Compare one claim a model run computes with one claim observations measure, under a link.

The model claim is read from a `run_logic_model` window result, as computed; the model is never
re-run. The observation claim is read by :func:`virtualcell.research.observe.read_mapping`, the
same reader `compare_observations` uses; nothing about measurement quality, units, arms, pairs,
references or decision rules is restated here. What this module adds is the link between the
two, in a fixed order (`docs/research_sessions/model_observation_link_v0/SPEC.md`):

1. **integrity** — the link must select exactly one model claim of the result it is given
   (identity, scenario, baseline, window, target) and declare a well-formed table; otherwise it
   is refused, never resolved by taking a first or last candidate;
2. **meaning and scope before values** — a magnitude question is outside a Boolean model's
   representation; differing claim forms, an unstated window or baseline correspondence, a held
   reference and a model value with no table entry leave the correspondence unresolved; an
   observation not classified or a model value not computed is insufficient. Nothing is
   compared first and qualified afterwards;
3. **comparison only through the table** — model values are translated by the declared table
   and set against the observed class. No word is read as the same claim because it is spelled
   the same, and below detection is never read as biological absence or as an inactive state
   unless a table entry says so. A set of model values that only partly contains the observed
   class is undecided, never consistent.

The result is conditional on the link. It is not a scientific validation, and it changes no
model, plan, run, mapping or decision.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from virtualcell.core.experiment import ExperimentRun
from virtualcell.research.contracts import ObservationMapping, ReadoutSpec
from virtualcell.research.observe import ReadoutComparison, read_mapping
from virtualcell.research.plan import PlanFinding
from virtualcell.simulation.logic import LogicRun, WindowRun

STATE_MODEL_VALUES = frozenset({"active", "inactive"})
CHANGE_VALUES = frozenset({"increase", "decrease", "no_change"})
STATE_OBSERVED_VALUES = frozenset({"present", "absent"})

Comparability = Literal[
    "comparable", "correspondence_unresolved", "outside_model_representation", "insufficient"
]
Need = Literal["check_record", "state_or_review_correspondence", "richer_model", "more_measurement"]
Relation = Literal["single_match", "outside", "partial", "between_bands"]
Result = Literal["consistent", "inconsistent", "undecided"]


class LinkRefused(ValueError):
    """The link does not select exactly one well-formed claim. The message names the field."""


# --- inputs --------------------------------------------------------------------------------- #


class ModelWindowResult(BaseModel):
    """The identifying part of a `run_logic_model` window response, copied field for field."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    model_sha256: str
    run_sha256: str
    scenario: str = Field(description="The scenario's name (`scenario.name` in the response).")
    baseline: str | None = Field(
        default=None, description="The baseline's name (`baseline.name`), or null."
    )
    cases_explored: int
    cases_total: int
    exploration_complete: bool
    window: WindowRun

    @classmethod
    def from_run(cls, run: LogicRun) -> ModelWindowResult:
        if run.window is None:
            raise LinkRefused("model_result: the run has no window; call with view='window'")
        return cls(
            model_id=run.model_id,
            model_sha256=run.model_sha256,
            run_sha256=run.run_sha256,
            scenario=run.scenario.name,
            baseline=run.baseline.name if run.baseline is not None else None,
            cases_explored=run.cases_explored,
            cases_total=run.cases_total,
            exploration_complete=run.exploration_complete,
            window=run.window,
        )


class WindowSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first: int = Field(ge=0)
    last: int = Field(ge=0)


class ModelSelection(BaseModel):
    """Exactly one model claim: which result, which target, which window, state or change."""

    model_config = ConfigDict(extra="forbid")

    run_sha256: str
    model_sha256: str
    scenario: str
    baseline: str | None = None
    window: WindowSelection
    target: str = Field(description="One of the window's targets (a component or readout id).")
    claim: Literal["state", "change"] = Field(
        description=(
            "state: the scenario's window class per case. change: the per-case, per-step "
            "paired directions against the baseline."
        )
    )


class TableEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_value: str = Field(
        description="active / inactive (state) or increase / decrease / no_change (change)."
    )
    observed_value: str = Field(
        description=(
            "present / absent (state: analytical detection as recorded) or increase / decrease "
            "/ no_change (change: classified under the mapping's DecisionRule)."
        )
    )


class LinkCorrespondence(BaseModel):
    """How the model claim is read as the observation claim. A statement, not a validation."""

    model_config = ConfigDict(extra="forbid")

    table: list[TableEntry] = Field(
        default_factory=list,
        description=(
            "Explicit model value -> observed value entries. A value maps to the same-named "
            "value only if an entry says so."
        ),
    )
    asks: Literal["category", "magnitude"] = Field(
        default="category",
        description="magnitude asks how much; a Boolean model does not compute that.",
    )
    window_correspondence: str | None = Field(
        default=None,
        description=(
            "Why the model window may be read as the observation's time point and conditions. "
            "Without it the claim is not compared."
        ),
    )
    baseline_stands_for: str | None = Field(
        default=None,
        description=(
            "For a change claim: the plan reference the model baseline stands for, compared as "
            "written with the mapping's `versus`."
        ),
    )
    applies_to_experiment_ids: list[str] = Field(default_factory=list)
    basis: str
    evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    stated_by: Literal["host", "researcher"]
    accepted_by: Literal["researcher"] | None = None


class ModelObservationLink(BaseModel):
    """One model claim, one observation mapping, and the correspondence between them."""

    model_config = ConfigDict(extra="forbid")

    id: str
    model: ModelSelection
    observation: ObservationMapping
    readout_spec: ReadoutSpec | None = Field(
        default=None, description="The readout's assay and unit, as a plan's readout spec gives."
    )
    correspondence: LinkCorrespondence
    hypothesis_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _table_well_formed(self) -> ModelObservationLink:
        claim = self.model.claim
        model_vocab = STATE_MODEL_VALUES if claim == "state" else CHANGE_VALUES
        observed_vocab = STATE_OBSERVED_VALUES if claim == "state" else CHANGE_VALUES
        seen: dict[str, str] = {}
        for i, e in enumerate(self.correspondence.table):
            if e.model_value not in model_vocab:
                raise ValueError(
                    f"correspondence.table[{i}].model_value {e.model_value!r} is not a {claim} "
                    f"model value ({sorted(model_vocab)})"
                )
            if e.observed_value not in observed_vocab:
                raise ValueError(
                    f"correspondence.table[{i}].observed_value {e.observed_value!r} is not a "
                    f"{claim} observed value ({sorted(observed_vocab)})"
                )
            if e.model_value in seen and seen[e.model_value] != e.observed_value:
                raise ValueError(
                    f"correspondence.table maps {e.model_value!r} to both "
                    f"{seen[e.model_value]!r} and {e.observed_value!r}; neither is chosen"
                )
            seen[e.model_value] = e.observed_value
        return self


# --- result ----------------------------------------------------------------------------------- #


class ModelValueGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_values: list[str]
    observed_values: list[str] | None = Field(
        default=None, description="The table's translation; null where a value has no entry."
    )
    cases: list[int] = Field(description="Positions in `model_claim.case_labels`.")


class ModelClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    form: Literal["state", "change"]
    meaning: str
    target: str
    window: WindowSelection
    groups: list[ModelValueGroup]
    model_values: list[str] = Field(description="Every model value seen, over cases and steps.")
    case_labels: list[str]
    cases_explored: int
    cases_total: int
    applies_to: Literal["all_cases", "explored_cases_only"]
    not_computed: bool = False


class ModelObservationComparison(BaseModel):
    """A link's comparison: comparability first, then a result only where comparable."""

    comparison_id: str
    link_id: str
    link_sha256: str
    observations_sha256: str
    model_id: str
    model_sha256: str
    run_sha256: str
    window_request_sha256: str
    model_claim: ModelClaim
    observation: ReadoutComparison
    observation_meaning: Literal["analytical_detection", "quantitative_change", "not_classified"]
    observation_findings: list[PlanFinding] = Field(default_factory=list)
    runs_used: list[str] = Field(default_factory=list)
    comparability: Comparability
    reasons: list[str] = Field(default_factory=list)
    needs: list[Need] = Field(default_factory=list)
    relation: Relation | None = None
    result: Result | None = None
    explored_result: Result | None = Field(
        default=None,
        description="The result on the explored cases; `result` is undecided when exploration "
        "is incomplete.",
    )
    if_accepted: Result | None = Field(
        default=None,
        description=(
            "Only when the observation's reference correspondence is host-proposed (held): the "
            "result if a researcher accepted it. Not a result; counted nowhere."
        ),
    )
    correspondence: LinkCorrespondence
    correspondence_accepted: bool
    scientific_validity_checked: Literal[False] = False
    hypothesis_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)


LIMITS: tuple[str, ...] = (
    "Every result holds under the link's correspondence, as stated by whoever stated it. It is "
    "not a scientific validation, and accepting a correspondence accepts an analysis "
    "assumption, nothing more.",
    "'consistent' means every model value, translated by the table, is the observed class. "
    "'inconsistent' means the observed class is none of them; it is not a refutation of a "
    "hypothesis. 'undecided' with relation 'partial' means the model allows the observed class "
    "among others; no single prediction was made.",
    "Model values are Boolean states or per-step paired directions over logical steps. Case "
    "counts, step counts and arm combinations are not replicates or probabilities.",
    "Observed 'present'/'absent' is analytical: a valid non-zero reading, or one recorded below "
    "the producer's detection limit. It is not biological presence or absence, and it is not "
    "a Boolean model state unless the table says so.",
    "A quantitative change is classified only by the mapping's declared rule; no threshold, "
    "mean, test, background correction or renormalisation is computed here.",
    "The model result is read as given and identified by its hashes; a hash is an identity "
    "check, not proof of where the result came from.",
    "Nothing is modified. Keep, revise and hold remain the host's proposals and the "
    "researcher's decision.",
)

_OBSERVATION_NEEDS: dict[str, Need] = {
    "no_decision_rule": "state_or_review_correspondence",
    "rule_declares_no_band": "state_or_review_correspondence",
    "replicates_disagree": "more_measurement",
    "combinations_disagree": "more_measurement",
    "pairs_disagree": "more_measurement",
    "no_usable_readings": "more_measurement",
    "no_usable_pairs": "more_measurement",
}


def _sha(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def parse_model_result(payload: dict[str, Any]) -> ModelWindowResult:
    """A window response or its identifying subset; refused with the parse error otherwise."""
    try:
        return ModelWindowResult.model_validate(payload)
    except ValidationError as subset_error:
        if "view" not in payload:
            raise LinkRefused(f"model_result: {subset_error}") from subset_error
    try:
        return ModelWindowResult.from_run(LogicRun.model_validate(payload))
    except ValidationError as exc:
        raise LinkRefused(f"model_result: {exc}") from exc


# --- the comparison ------------------------------------------------------------------------- #


def compare_model_observation(
    model_result: ModelWindowResult,
    runs: list[ExperimentRun],
    link: ModelObservationLink,
) -> ModelObservationComparison:
    target = _select(model_result, link)
    claim = _model_claim(model_result, link, target)
    row, findings, runs_used = read_mapping(runs, link.observation, link.readout_spec)

    reasons: list[str] = []
    needs: list[Need] = []
    c = link.correspondence
    status: Comparability = "comparable"

    if c.asks == "magnitude":
        status = "outside_model_representation"
        reasons.append("magnitude_not_computed_by_a_boolean_model")
        needs.append("richer_model")

    unresolved = _unresolved(link, row, claim)
    if unresolved:
        reasons += unresolved
        needs.append("state_or_review_correspondence")
        if status == "comparable":
            status = "correspondence_unresolved"

    insufficient = []
    if row.status != "compared":
        insufficient.append("observation_not_classified")
        for r in row.reasons:
            need = _OBSERVATION_NEEDS.get(r, "check_record")
            if need not in needs:
                needs.append(need)
    if claim.not_computed:
        insufficient.append("model_values_not_computed")
        if "richer_model" not in needs:
            needs.append("richer_model")
    if link.model.claim == "change" and model_result.window.pairing.status != "paired":
        insufficient.append("model_not_paired")
        if "check_record" not in needs:
            needs.append("check_record")
    if insufficient:
        reasons += insufficient
        if status == "comparable":
            status = "insufficient"
    if claim.applies_to != "all_cases":
        # Not a comparability failure: the explored part is compared, the whole stays undecided.
        reasons.append("model_exploration_incomplete")
        if "check_record" not in needs:
            needs.append("check_record")

    relation = result = explored = if_accepted = None
    if status == "comparable":
        relation, explored = _relate(claim, row.observed)
        result = explored if claim.applies_to == "all_cases" else "undecided"
    elif (
        set(reasons) - {"model_exploration_incomplete"} == {"observation_reference_host_proposed"}
        and row.status == "compared"
        and not claim.not_computed
    ):
        _, would = _relate(claim, row.observed)
        if_accepted = would if claim.applies_to == "all_cases" else "undecided"

    link_sha = _sha(link.model_dump(mode="json"))
    observations_sha = _sha(
        {
            "runs": [r.model_dump(mode="json") for r in runs],
            "mapping": link.observation.model_dump(mode="json"),
        }
    )
    model_sha = _sha(model_result.model_dump(mode="json"))
    return ModelObservationComparison(
        comparison_id="mo-" + _sha([link_sha, observations_sha, model_sha])[:16],
        link_id=link.id,
        link_sha256=link_sha,
        observations_sha256=observations_sha,
        model_id=model_result.model_id,
        model_sha256=model_result.model_sha256,
        run_sha256=model_result.run_sha256,
        window_request_sha256=model_result.window.request_sha256,
        model_claim=claim,
        observation=row,
        observation_meaning=(
            "not_classified"
            if row.status != "compared"
            else ("analytical_detection" if row.kind == "state" else "quantitative_change")
        ),
        observation_findings=findings,
        runs_used=runs_used,
        comparability=status,
        reasons=reasons,
        needs=needs,
        relation=relation,
        result=result,
        explored_result=explored,
        if_accepted=if_accepted,
        correspondence=c,
        correspondence_accepted=c.stated_by == "researcher" or c.accepted_by == "researcher",
        hypothesis_ids=list(link.hypothesis_ids),
        experiment_ids=list(link.experiment_ids),
        decision_ids=list(link.decision_ids),
        limits=list(LIMITS),
    )


def _select(r: ModelWindowResult, link: ModelObservationLink) -> Any:
    sel = link.model
    w = r.window
    for field, given, have in (
        ("run_sha256", sel.run_sha256, r.run_sha256),
        ("model_sha256", sel.model_sha256, r.model_sha256),
        ("scenario", sel.scenario, r.scenario),
        ("baseline", sel.baseline, r.baseline),
    ):
        if given != have:
            raise LinkRefused(f"link.model.{field} is {given!r}; the model result has {have!r}")
    if w.run_sha256 != r.run_sha256:
        raise LinkRefused("model_result.window.run_sha256 differs from model_result.run_sha256")
    if (sel.window.first, sel.window.last) != (w.request.first, w.request.last):
        raise LinkRefused(
            f"link.model.window is {sel.window.first}-{sel.window.last}; the result's window is "
            f"{w.request.first}-{w.request.last}"
        )
    matches = [t for t in w.targets if t.target == sel.target]
    if len(matches) != 1:
        raise LinkRefused(
            f"link.model.target {sel.target!r} matches {len(matches)} window targets "
            f"({[t.target for t in w.targets]}); exactly one is needed"
        )
    if sel.claim == "change" and r.baseline is None:
        raise LinkRefused("link.model.claim is 'change' but the model result has no baseline")
    return matches[0]


def _model_claim(r: ModelWindowResult, link: ModelObservationLink, target: Any) -> ModelClaim:
    form = link.model.claim
    table = {e.model_value: e.observed_value for e in link.correspondence.table}
    groups: list[ModelValueGroup] = []
    not_computed = False
    if form == "state":
        meaning = "Boolean model state of the scenario over the window, per case"
        by_class = {"all_active": ["active"], "all_inactive": ["inactive"]}
        for g in target.scenario.groups:
            if g.window_class == "both_values":
                values = ["active", "inactive"]
            elif g.window_class in by_class:
                values = by_class[g.window_class]
            else:
                not_computed = True
                values = []
            groups.append(_group(values, table, g.cases))
    else:
        meaning = "per-step paired Boolean direction against the baseline, per case"
        paired = target.paired
        for g in paired.groups if paired is not None else []:
            if "undetermined" in g.directions:
                not_computed = True
            values = [d for d in g.directions if d != "undetermined"]
            groups.append(_group(values, table, g.cases))
    if form == "state":
        complete = target.scenario.applies_to == "all_cases"
    else:
        complete = target.paired is not None and target.paired.applies_to == "all_cases"
    return ModelClaim(
        form=form,
        meaning=meaning,
        target=link.model.target,
        window=link.model.window,
        groups=groups,
        model_values=sorted({v for g in groups for v in g.model_values}),
        case_labels=list(r.window.cases),
        cases_explored=r.cases_explored,
        cases_total=r.cases_total,
        applies_to="all_cases" if complete else "explored_cases_only",
        not_computed=not_computed,
    )


def _group(values: list[str], table: dict[str, str], cases: list[int]) -> ModelValueGroup:
    translated = None
    if values and all(v in table for v in values):
        translated = sorted({table[v] for v in values})
    return ModelValueGroup(model_values=sorted(values), observed_values=translated, cases=cases)


def _unresolved(link: ModelObservationLink, row: ReadoutComparison, claim: ModelClaim) -> list[str]:
    c = link.correspondence
    m = link.observation
    out: list[str] = []
    if row.kind is not None and row.kind != claim.form:
        out.append("claim_forms_differ")
    if m.experiment_id not in c.applies_to_experiment_ids:
        out.append("correspondence_not_stated_for_this_experiment")
    if not c.window_correspondence:
        out.append("window_correspondence_unstated")
    if claim.form == "change":
        if not c.baseline_stands_for:
            out.append("baseline_correspondence_unstated")
        elif m.versus is None or _norm(c.baseline_stands_for) != _norm(m.versus):
            out.append("baseline_correspondence_differs_from_mapping_versus")
        link_kind = row.reference_link
        if link_kind == "host_proposed":
            out.append("observation_reference_host_proposed")
        elif link_kind in ("declared_only", "conflicting"):
            out.append(f"observation_reference_{link_kind}")
    if any(g.observed_values is None and g.model_values for g in claim.groups):
        out.append("model_value_without_correspondence")
    return out


def _relate(claim: ModelClaim, observed: str | None) -> tuple[Relation, Result]:
    if observed == "indeterminate":
        return "between_bands", "undecided"
    translated = {v for g in claim.groups for v in (g.observed_values or [])}
    if translated == {observed}:
        return "single_match", "consistent"
    if observed not in translated:
        return "outside", "inconsistent"
    return "partial", "undecided"
