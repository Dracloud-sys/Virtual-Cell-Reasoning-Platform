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
from typing import Any

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
