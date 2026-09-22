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

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from virtualcell.literature.contracts import SourceLocator, VerificationStatus


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
        return self


class ResearchBudget(BaseModel):
    """What one investigation is allowed to spend.

    Small by default. A budget exists so a run fails loudly instead of looping, not so a
    caller can tune throughput, and the ceiling is raised when a real failure asks for it.
    """

    model_config = ConfigDict(extra="forbid")

    max_model_calls: int = Field(default=1, ge=1, le=8)
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


class DecisionBranch(BaseModel):
    """What a result would change. The point of running the experiment."""

    model_config = ConfigDict(extra="forbid")

    outcome: str
    implication: str


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


class IntegrityFinding(BaseModel):
    """Something checkable that is wrong or unsupported in a produced report.

    Findings do not fail the run. They travel with the report, because a report that
    validated against a schema has not thereby reasoned well, and the gap between those two
    is exactly what a reader needs to see.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    detail: str
    where: str


class ResearchProvenance(BaseModel):
    """What produced this report. Enough to tell two runs apart, and no secrets."""

    model_config = ConfigDict(extra="forbid")

    backend: str
    model: str | None = None
    prompt_version: str
    model_calls: int = Field(ge=0)
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
    integrity: list[IntegrityFinding] = Field(default_factory=list)
    provenance: ResearchProvenance
