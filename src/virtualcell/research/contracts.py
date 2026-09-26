"""Contracts for the open-ended research path.

`ReasoningQuery` requires a `domain` and a `task`, and `ReasoningService.query` resolves a
`DomainPack` before anything else happens. That is correct for what it does — a verified
verdict from a validated vocabulary — and it is exactly why a new research question cannot
use it: there is no pack, so there is no answer, and the platform is less useful than the
bare model until someone writes one.

This is the other entry point. It takes a question and whatever evidence the caller already
has, and returns a research design. It never resolves a domain, and a field of study is
context a reader may find useful, never a key in a dispatch table.

**Nothing here grades biology.** The strict path's `EvidenceTier` means something that was
argued for; a hypothesis proposed in an exploratory session does not get one by arriving in
the same process. What this module does instead is keep five things that are easy to
conflate separately labelled, so a reader can always tell which they are looking at:

* an observation the **user reported**, with how it was measured;
* a span **actually read** from a source, anchored by a locator;
* an inference **derived from** listed evidence;
* a candidate the **model proposed from its own priors**, which is a search target and not
  a finding;
* a **predicted outcome** of an experiment that has not been run.

Those five are one enum rather than five parallel field sets, because the distinction is
what matters and the field count is not.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from virtualcell.literature.contracts import SourceLocator, VerificationStatus, hash_source_text


class EvidenceKind(StrEnum):
    """What a piece of evidence *is*, which is not the same as how strong it is."""

    USER_OBSERVATION = "user_observation"
    """Reported by the caller from their own work. Carries its measurement context."""

    RETRIEVED_SOURCE = "retrieved_source"
    """A span actually read from a document, anchored by a `SourceLocator`."""

    DERIVED_INFERENCE = "derived_inference"
    """Reasoned from other evidence in this session. Names what it was derived from."""

    MODEL_PRIOR = "model_prior"
    """Proposed from the model's own knowledge with nothing retrieved behind it.

    A search target, not a finding. It never carries a locator, and a hypothesis resting
    only on these is reported as unverified rather than supported.
    """

    PREDICTED_OUTCOME = "predicted_outcome"
    """What an experiment is expected to show. A prediction, never an observation."""


#: Kinds that assert something was *observed or read*, as opposed to proposed or predicted.
GROUNDED_KINDS = frozenset({EvidenceKind.USER_OBSERVATION, EvidenceKind.RETRIEVED_SOURCE})


class EvidenceItem(BaseModel):
    """One labelled piece of evidence a research session may reason from."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: EvidenceKind
    statement: str
    #: Required for `retrieved_source` and forbidden for everything else: a locator asserts
    #: that a specific span of a specific document was read, and nothing else here has one.
    locator: SourceLocator | None = None
    #: How a user observation was produced — assay, replicates, timepoint, whether it was
    #: verified. Free text because it belongs to the caller's experiment, not to this
    #: contract.
    measurement_context: str | None = None
    verification: VerificationStatus | None = None
    #: For `derived_inference`: the ids this was reasoned from.
    derived_from: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    #: SHA-256 over what this item asserts, filled automatically. Ids are stable across
    #: sessions on purpose — that is what makes them citable — and the same stability makes
    #: a silent edit invisible: `obs-1` saying "two-fold" and `obs-1` saying "ten-fold"
    #: would otherwise compare equal. Mirrors `SourceLocator.source_text_hash`, including
    #: rejecting a supplied hash that disagrees, because a stale digest travelling with
    #: changed text is worse than none.
    content_hash: str | None = None

    @field_validator("id", "statement")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id and statement must not be blank")
        return v.strip()

    @model_validator(mode="after")
    def _kind_constraints(self) -> EvidenceItem:
        if self.kind is EvidenceKind.RETRIEVED_SOURCE and self.locator is None:
            raise ValueError(
                f"evidence {self.id!r} is a retrieved_source but carries no locator; a "
                "retrieved span must say which document and where, or it is a model prior"
            )
        if self.kind is not EvidenceKind.RETRIEVED_SOURCE and self.locator is not None:
            raise ValueError(
                f"evidence {self.id!r} is {self.kind.value!r} but carries a source locator; "
                "only a span actually read from a document may claim one"
            )
        if self.kind is EvidenceKind.DERIVED_INFERENCE and not self.derived_from:
            raise ValueError(
                f"evidence {self.id!r} is a derived_inference but names nothing it was derived from"
            )
        expected = self._digest()
        if self.content_hash is None:
            self.content_hash = expected
        elif self.content_hash != expected:
            raise ValueError(
                f"evidence {self.id!r} carries a content_hash that does not match its "
                "content; the text was edited after the digest was taken"
            )
        return self

    def _digest(self) -> str:
        """Everything this item asserts, serialised unambiguously, hashed.

        Two properties this has to have, and an earlier version had neither.

        **The whole locator counts.** A digest taken over the span's text alone made the
        *same sentence* read from two different papers hash identically, and the same
        sentence read from the Results and from the Discussion of one paper likewise. The
        source is part of what a retrieved item asserts: "this was published in X" and
        "this was published in Y" are different claims, and a digest that cannot tell them
        apart cannot detect the edit that swaps one for the other. So the locator goes in
        whole — article identifiers, section, table and figure ids, exact cell
        coordinates, the span and its hash — via the model's own JSON dump.

        **The serialisation has to be injective.** Joining lists on a separator made
        ``["a|b"]`` and ``["a", "b"]`` the same bytes, so a digest could be preserved
        across a change in what an inference was derived from. JSON with sorted keys
        encodes list structure, which a join discards; it is the same construction
        :func:`literature.contracts._deterministic_candidate_id` already uses.

        ``id`` is excluded, so two items asserting the same thing under different ids
        agree — that is the comparison this digest is for. Everything else is included,
        which means adding a field to this model changes every digest: correct, because
        the new field is new content, and the alternative is a hash that silently stops
        covering part of the item.
        """
        payload = self.model_dump(mode="json", exclude={"id", "content_hash"})
        return hash_source_text(json.dumps(payload, sort_keys=True))


class ResearchBudget(BaseModel):
    """What one investigation is allowed to spend.

    Only what is actually enforced. A ``max_model_calls`` field was declared here, and read
    by nothing: P1 makes exactly one call, so the ceiling could neither be exceeded nor
    checked, which makes it a claim rather than a control. The loop that will genuinely
    need one is P3's, and it can add it then with the code that spends it.

    ``max_output_tokens`` stays because the provider enforces it, and because running past
    it is a real failure the backend has to name.
    """

    model_config = ConfigDict(extra="forbid")

    max_output_tokens: int = Field(default=4096, ge=256, le=32768)


class ResearchRequest(BaseModel):
    """A research question, with whatever the caller already has.

    ``field_of_study`` is deliberately free text and deliberately optional. It is printed
    for a reader; nothing in the service branches on it. That is the difference between
    this path and the strict one, and a test asserts it stays true.
    """

    model_config = ConfigDict(extra="forbid")

    question: str
    goal: str | None = None
    field_of_study: str | None = None
    #: Species, cell type, model system, materials — whatever frames the question. Open by
    #: design: its keys belong to the caller's problem, not to this contract.
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    budget: ResearchBudget = Field(default_factory=ResearchBudget)

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank")
        return v.strip()

    @model_validator(mode="after")
    def _evidence_ids_unique(self) -> ResearchRequest:
        seen: set[str] = set()
        for item in self.evidence:
            if item.id in seen:
                raise ValueError(f"duplicate evidence id {item.id!r}")
            seen.add(item.id)
        return self

    def evidence_ids(self) -> set[str]:
        return {item.id for item in self.evidence}


class HypothesisSupport(StrEnum):
    """How a hypothesis stands relative to the evidence in this session."""

    EVIDENCE_LINKED = "evidence_linked"
    """At least one grounded item — a user observation or a read span — supports it."""

    UNVERIFIED_CANDIDATE = "unverified_candidate"
    """Proposed, with nothing grounded behind it yet. A search target."""


# --- the plan around the hypotheses ----------------------------------------------------- #
#
# A research question is answered for a goal. These records keep that goal, what the
# researcher has fixed, what is still open, and how each hypothesis and experiment connects
# back to it, so a design cannot quietly narrow the question it was asked. All of them are
# written by the host; code only checks the connections and computes what follows from them.


class Objective(BaseModel):
    """One thing the work is for. Kept separate from how the host restated it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    statement: str
    stated_by: Literal["user", "host"] = Field(
        description=(
            "user: the researcher's own goal. host: an objective the host added; it is "
            "reported as the host's, never as the researcher's."
        )
    )


class SubQuestion(BaseModel):
    """A question an experiment can answer, and which objectives it serves."""

    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    objective_ids: list[str] = Field(default_factory=list)


class EvidenceRole(StrEnum):
    """What the host says a span does for a claim. The host's reading, not a verified fact."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    METHOD = "method"
    """The span informs how to measure or control something, not whether a claim holds."""

    SCOPE_LIMIT = "scope_limit"
    """The span limits where a claim can apply (species, system, condition)."""


class EvidenceLink(BaseModel):
    """The host's statement that one evidence item bears on one hypothesis or mechanism link."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    target_id: str = Field(description="A hypothesis id or a mechanism link id.")
    role: EvidenceRole
    reading: str = Field(
        default="",
        description="What the host takes the span to say. Reported as the host's interpretation.",
    )


class MechanismLink(BaseModel):
    """A candidate relation for this case: source -relation-> target, with its conditions.

    Case-local. It is checked against the knowledge graph read-only and never written to it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    relation: str
    target: str
    evidence_ids: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(
        default_factory=list,
        description="Where the relation is claimed to hold: species, cell type, system, dose.",
    )
    hypothesis_ids: list[str] = Field(default_factory=list)


class Expectation(StrEnum):
    """A predicted value for one readout. Compared by value; wording is never compared.

    Two different kinds of claim share this vocabulary and are never compared with each other:
    a **state** (`present` / `absent`: the thing the readout names is, or is not, detected) and
    a **change** (`increase` / `decrease` / `no_change`: relative to the reference in
    `Prediction.versus`). `absent` is not `no_change`, and a reading of zero is not a reading
    below the detection limit. `not_predicted` means the hypothesis says nothing about it.
    """

    INCREASE = "increase"
    DECREASE = "decrease"
    NO_CHANGE = "no_change"
    PRESENT = "present"
    ABSENT = "absent"
    NOT_PREDICTED = "not_predicted"
    """The hypothesis says nothing about this readout. Not the same as no_change."""


STATE_EXPECTATIONS = frozenset({"present", "absent"})
CHANGE_EXPECTATIONS = frozenset({"increase", "decrease", "no_change"})


def expectation_kind(expected: str) -> str | None:
    """`state`, `change`, or None for `not_predicted`."""
    if expected in STATE_EXPECTATIONS:
        return "state"
    if expected in CHANGE_EXPECTATIONS:
        return "change"
    return None


class PredictionBasis(StrEnum):
    """How the host arrived at a prediction. The host's statement; code only checks it is backed."""

    EVIDENCE_OBSERVED = "evidence_observed"
    """A cited source reports this result, in some system."""

    MECHANISM_DERIVED = "mechanism_derived"
    """Derived from mechanism links (which carry their own evidence and conditions)."""

    MEASUREMENT_MODEL = "measurement_model"
    """Follows from how the assay reads its target (what it detects and what can distort it)."""

    ASSUMPTION = "assumption"
    """Not yet backed by evidence or mechanism; the listed assumptions carry it."""

    UNSTATED = "unstated"


class Prediction(BaseModel):
    """What one hypothesis predicts for one readout of one experiment, if it holds."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    readout: str = Field(description="Should name one of the experiment's measurements.")
    expected: Expectation
    note: str | None = None
    versus: str | None = Field(
        default=None,
        description=(
            "For increase/decrease/no_change: the reference the change is relative to (e.g. "
            "vehicle, acellular scaffold). Two change predictions against different references "
            "are not compared."
        ),
    )
    condition: str | None = Field(
        default=None, description="The intervention or condition this prediction is for."
    )
    biological_expectation: str | None = Field(
        default=None,
        description="The biological state or process expected, before it is read by an assay.",
    )
    basis: PredictionBasis = PredictionBasis.UNSTATED
    evidence_ids: list[str] = Field(default_factory=list)
    mechanism_link_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(
        default_factory=list, description="Assumptions this prediction depends on, in words."
    )
    unresolved: str | None = Field(
        default=None, description="What cannot yet be predicted here, and what would decide it."
    )


class ReadoutSpec(BaseModel):
    """How a readout is measured: what it reads, with what, where, when, against what."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="The readout name predictions use.")
    target: str | None = Field(default=None, description="The entity or state the readout reads.")
    assay: str | None = None
    compartment: str | None = None
    timepoint: str | None = None
    reference: str | None = Field(default=None, description="The comparison baseline.")
    normalization: str | None = None
    unit: str | None = None


class ExperimentPurpose(StrEnum):
    DISCRIMINATE = "discriminate"
    METHOD_CHECK = "method_check"
    FUNCTION_CHECK = "function_check"
    BASELINE = "baseline"
    OTHER = "other"


class ObjectiveCoverage(BaseModel):
    """How directly an experiment addresses an objective. A judgement, recorded as whose."""

    model_config = ConfigDict(extra="forbid")

    objective_id: str
    level: Literal["direct", "proxy", "out_of_scope"] = Field(
        description=(
            "direct: measures the objective itself. proxy: a related indicator. out_of_scope: "
            "the objective's outcome lies beyond what this experiment can show."
        )
    )
    judged_by: Literal["host", "user"] = "host"
    note: str | None = None


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    statement: str
    support: HypothesisSupport
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    #: Where this is expected to hold, and where the evidence behind it came from instead —
    #: a different species, cell type or model system is the commonest way a mechanism is
    #: over-extended.
    applicability: str | None = None
    sub_question_ids: list[str] = Field(
        default_factory=list,
        description=(
            "The sub-questions this hypothesis answers. Hypotheses sharing a sub-question are "
            "treated as alternatives (which may coexist) and compared; hypotheses with no shared "
            "sub-question are not compared. Put competing explanations of one observation under "
            "one sub-question."
        ),
    )
    alternative_to: list[str] = Field(
        default_factory=list,
        description=(
            "Hypotheses the host states are alternative explanations of the same observation. "
            "These are compared even without a shared sub-question."
        ),
    )
    mutually_exclusive_with: list[str] = Field(
        default_factory=list,
        description=(
            "Hypotheses that cannot hold together with this one. Leave empty when both could "
            "be true at once; coexistence is the default."
        ),
    )


class DecisionBranch(BaseModel):
    """What a result would change. The point of running the experiment."""

    model_config = ConfigDict(extra="forbid")

    outcome: str
    implication: str


class AssumptionCheck(BaseModel):
    """What an experiment testing a measurement assumption expects if the assumption holds.

    Not a hypothesis prediction: a cell-free interference control tests whether an assay can be
    read, not which biological explanation holds. Inventing a hypothesis to carry it would put a
    fake alternative into every pair comparison.
    """

    model_config = ConfigDict(extra="forbid")

    assumption: str = Field(
        description="The assumption, written exactly as the predictions that rest on it state it."
    )
    readout: str = Field(description="Should name one of the experiment's measurements.")
    expected_if_holds: Expectation
    versus: str | None = Field(
        default=None, description="For a change: the reference, as in Prediction.versus."
    )


class ProposedExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    design: str
    #: Which hypotheses this would tell apart. An experiment that separates nothing is
    #: reported as such rather than dressed up.
    discriminates: list[str] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    measurements: list[str] = Field(default_factory=list)
    timepoints: list[str] = Field(default_factory=list)
    branches: list[DecisionBranch] = Field(default_factory=list)
    #: Why this one first, in words. Deliberately not a number: an invented probability or
    #: information-gain score would be a confidence nobody measured.
    priority_rationale: str | None = None
    readouts: list[ReadoutSpec] = Field(
        default_factory=list,
        description=(
            "How each readout is measured; needed to compare observations with predictions."
        ),
    )
    purposes: list[ExperimentPurpose] = Field(
        default_factory=list,
        description=(
            "Why the experiment is in the plan. An experiment that separates no hypothesis pair "
            "can still be needed for a method check, a function check or a baseline."
        ),
    )
    objective_coverage: list[ObjectiveCoverage] = Field(default_factory=list)
    predictions: list[Prediction] = Field(
        default_factory=list,
        description=(
            "What each hypothesis predicts for each readout if it holds. Discrimination is "
            "computed from these values, never from wording."
        ),
    )
    assumption_checks: list[AssumptionCheck] = Field(
        default_factory=list,
        description=(
            "Readouts that test a measurement assumption rather than a hypothesis. Observations "
            "of them are read against the assumption and marked on every prediction resting on it."
        ),
    )


class IntegrityFinding(BaseModel):
    """Something a reader must be told about a produced report before acting on it.

    Usually that is a checkable defect — a citation to an id nobody supplied, a label that
    disagrees with what it cites. Two of the codes are not defects at all: a reply that
    produced no design, and one that declined and said why, are both *reported* here so
    that a caller reading only the exit code cannot take either for an ordinary completed
    design. Withholding a design can be the right answer; reporting it as a finished one
    never is.

    Findings do not fail the run. They travel with the report, because a report that
    validated against a schema has not thereby reasoned well, and the gap between those two
    is exactly what a reader needs to see.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    detail: str
    where: str


class ResearchProvenance(BaseModel):
    """What produced this report. Enough to tell two runs apart, and no secrets.

    Nothing here is inferred. Every field is either what this code asked for or what the
    provider reported back, and a value the provider does not report stays ``None`` rather
    than being filled with a plausible number.
    """

    model_config = ConfigDict(extra="forbid")

    backend: str
    #: The model this code *asked* for.
    model: str | None = None
    #: The model the provider reported it *served*. It need not equal ``model``: an alias
    #: resolves to a dated id, and a deployment can serve something else again. A report
    #: recording only the request cannot say which weights answered it.
    model_served: str | None = None
    prompt_version: str
    #: Logical design calls — one per investigation in P1. **Not** HTTP attempts: the SDK
    #: retries inside a single call and does not report how many times, so these two
    #: numbers are different measurements and must not be read as one.
    model_calls: int = Field(ge=0)
    #: The ceiling on HTTP attempts per logical call (retries + 1) that this run was
    #: configured with. A limit, not a count — see ``model_calls``. Calling it a count
    #: would report a measurement nobody took.
    max_request_attempts: int | None = Field(default=None, ge=1)
    #: The timeout applied to **one HTTP request**, in seconds.
    #:
    #: It is not a deadline for the call, and multiplying it by ``max_request_attempts``
    #: does not produce one: the SDK sleeps between retries with backoff the timeout does
    #: not cover, and nothing here cancels an operation that runs long. These two fields
    #: record settings. ``elapsed_seconds`` records what happened.
    timeout_seconds: float | None = Field(default=None, gt=0)
    #: Wall-clock seconds the provider call actually took. The one duration here that is a
    #: measurement rather than a configured limit.
    elapsed_seconds: float | None = Field(default=None, ge=0)
    #: Verbatim from the provider: why generation stopped. ``None`` when the backend does
    #: not report one.
    stop_reason: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    evidence_offered: int = Field(ge=0)


class ResearchReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    #: The question restated so it could be answered by an experiment.
    restated_question: str
    assumptions: list[str] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    experiments: list[ProposedExperiment] = Field(default_factory=list)
    open_items: list[str] = Field(default_factory=list)
    #: Evidence ids the report actually used, as opposed to what it was offered.
    evidence_used: list[str] = Field(default_factory=list)
    #: The evidence this session was given, carried verbatim. A report that holds only ids
    #: cannot be audited on its own — a later reader sees `obs-1` and has no way to learn
    #: what it said, or whether it has since been edited. With the snapshot, every citation
    #: resolves inside the artifact and its `content_hash` says whether it is the same item
    #: an earlier report cited.
    evidence_snapshot: list[EvidenceItem] = Field(default_factory=list)
    integrity: list[IntegrityFinding] = Field(default_factory=list)
    provenance: ResearchProvenance
    objectives: list[Objective] = Field(default_factory=list)
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    #: What the researcher has fixed, and what they have explicitly left open. Kept apart from
    #: `assumptions`, which are the host's.
    confirmed_conditions: list[str] = Field(default_factory=list)
    open_conditions: list[str] = Field(default_factory=list)
    evidence_links: list[EvidenceLink] = Field(default_factory=list)
    mechanism_links: list[MechanismLink] = Field(default_factory=list)


# --- B1: comparing quantitative observations with the plan's predictions ------------------ #
#
# The observations themselves arrive as `virtualcell.core.experiment.ExperimentRun`; nothing
# here restates measurements, units, quality or conditions. What these records add is the
# mapping from a run to a predicted readout, and the decision rule someone declared for reading
# a change. Without a declared rule no change is classified: no threshold is invented.


class DecisionRule(BaseModel):
    """How to read a change between a treatment arm and its reference. Declared, never inferred."""

    model_config = ConfigDict(extra="forbid")

    comparison: Literal["ratio", "difference"]
    increase_at_or_above: float | None = None
    decrease_at_or_below: float | None = None
    no_change_between: list[float] | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        description=(
            "[low, high], inclusive. Outside every declared band the result is indeterminate."
        ),
    )
    declared_by: Literal["researcher", "host"]
    basis: str = Field(description="Why these bounds; where they come from.")


class ObservationPair(BaseModel):
    """A treatment observation and the reference observation it is paired with (e.g. one donor)."""

    model_config = ConfigDict(extra="forbid")

    treatment_observation_id: str
    reference_observation_id: str


class ObservationMapping(BaseModel):
    """Which observations stand for one predicted readout, and how to read them."""

    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    readout: str
    run_ids: list[str] = Field(
        default_factory=list, description="Runs to read; empty means every supplied run."
    )
    measurement_name: str
    unit: str | None = Field(
        default=None, description="The unit the rule assumes. A different unit is not comparable."
    )
    time_point: dict[str, Any] | None = Field(
        default=None,
        description="A time point, in the run's own time-point form, to match exactly.",
    )
    treatment: dict[str, Any] = Field(
        description="Condition values an observation must carry to count as the treatment arm."
    )
    reference: dict[str, Any] | None = Field(
        default=None,
        description="Condition values of the reference arm. Required for change predictions.",
    )
    versus: str | None = Field(
        default=None,
        description=(
            "Which plan reference the reference arm stands for, compared as written with each "
            "prediction's `versus`. Without it, or when they differ, change predictions are held."
        ),
    )
    pairs: list[ObservationPair] = Field(
        default_factory=list,
        description=(
            "Declared treatment/reference pairs by observation_id. Without them every treatment "
            "reading is set against every reference reading, and those combinations are not "
            "independent replicates."
        ),
    )
    rule: DecisionRule | None = None


class HostDecision(BaseModel):
    """What the host proposes after reading the comparison. Recorded as the host's."""

    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(description="A hypothesis, prediction's experiment, or assumption id.")
    decision: Literal["keep", "revise", "hold"]
    reason: str
    next_experiment_ids: list[str] = Field(default_factory=list)
