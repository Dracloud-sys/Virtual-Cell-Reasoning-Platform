"""Domain-neutral query and reasoning contracts (PR11).

VCRP is a general biological experiment reasoning platform; immortalization is its first
validated vertical, not its subject. These contracts are the boundary that makes that
true in code: :class:`ReasoningQuery` names a *domain* and a *task* rather than a
hardcoded vertical, and :class:`ReasoningResponse` is an envelope every domain fills with
the same platform-level meaning (observations, evidence, decision support, provenance).

Two deliberate design rules:

* **No scientific meaning is invented here.** The envelope carries what a domain produced;
  it never derives, upgrades, or summarises a claim. Evidence stays as
  :class:`~virtualcell.core.evidence.Claim` objects with their tiers and citations intact,
  and mechanistic links stay as :class:`~virtualcell.reasoning.explain.MechanisticLink`.
* **Nothing is flattened.** A domain's native report is preserved verbatim in
  ``domain_details`` alongside the normalised envelope fields, so traceability survives
  the generic boundary and a caller can always recover the full domain report.

Scope note: PR11 accepts a *normalised* ``experiment`` payload (the shape existing agents
already consume). Structured raw-assay ingestion (CSV/XLSX, qPCR, FCS, imaging, omics) is
PR13 work and is explicitly **not** claimed here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from virtualcell.core.evidence import Claim
from virtualcell.reasoning.explain import MechanisticLink


class ExplanationLevel(StrEnum):
    """Audience the explanation is pitched at.

    Validated and carried end to end, but PR11 does **not** yet let it change the
    scientific content of a response: re-pitching an evidence-graded report for a
    non-expert requires a knowledge-learning layer that can do so without softening
    claims, which is a later platform layer. Until then the level is preserved as request
    provenance so callers and future layers can rely on it, and no explanation is
    fabricated to fill the schema.
    """

    NOVICE = "novice"
    PRACTITIONER = "practitioner"
    EXPERT = "expert"


class LiteratureStatus(StrEnum):
    """Outcome of the optional literature step — distinguishable by construction.

    A failure state is never silently equivalent to "no evidence found": callers can tell
    a provider outage from a genuine zero-result search, which is the difference between
    "we could not look" and "we looked and found nothing".
    """

    NOT_REQUESTED = "not_requested"
    UNAVAILABLE = "unavailable"  # requested, but no provider is wired
    SUCCESS = "success"
    ZERO_RESULTS = "zero_results"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"


class ReasoningQuery(BaseModel):
    """A domain-neutral request for reasoning over experimental evidence."""

    domain: str
    task: str
    question: str | None = None
    # The normalised, domain-specific input an existing agent already understands.
    # Preserved without reinterpretation so no semantic content is lost at this boundary.
    experiment: dict[str, Any] = Field(default_factory=dict)
    explanation_level: ExplanationLevel = ExplanationLevel.PRACTITIONER
    allow_literature: bool = False
    target_measurements: list[str] = Field(default_factory=list)

    @field_validator("domain", "task")
    @classmethod
    def _identifier_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("domain and task must be non-empty identifiers")
        return v.strip()

    @field_validator("question")
    @classmethod
    def _question_blank_is_none(cls, v: str | None) -> str | None:
        # ``question`` is optional when the task is self-describing; a whitespace-only
        # string is treated as absent rather than as an empty question.
        return v if v is None or v.strip() else None

    @field_validator("target_measurements")
    @classmethod
    def _clean_targets(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in v:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("target_measurements entries must be non-empty strings")
            token = item.strip()
            if token not in cleaned:  # order-preserving de-duplication
                cleaned.append(token)
        return cleaned


class DecisionSupport(BaseModel):
    """A domain's decision-facing outcome, kept deliberately coarse and non-committal.

    ``status`` is the domain's own vocabulary (e.g. immortalization's three-value
    candidate status); the platform neither interprets nor ranks it.
    """

    status: str | None = None
    flags: list[str] = Field(default_factory=list)
    # Surfaced explicitly because "this needs a trend, not a snapshot" is a decision the
    # caller must act on, and it would otherwise be buried in a flag list.
    trend_required: bool = False


class LiteratureOutcome(BaseModel):
    """What the optional literature step did, and what (if anything) it produced.

    ``evidence`` is **always empty unless** ``status`` is ``SUCCESS``: a provider failure
    can never arrive as scientific support. Anything present here is weak,
    pending-review evidence carrying its own citations and tier — it is reported
    separately from the domain's evidence and is never merged into it.
    """

    status: LiteratureStatus = LiteratureStatus.NOT_REQUESTED
    provider: str | None = None
    detail: str | None = None
    evidence: list[Claim] = Field(default_factory=list)


class QueryProvenance(BaseModel):
    """How the answer was produced — auditable, and never evidence in itself."""

    domain: str
    task: str
    pack: str
    engine: str
    explanation_level: ExplanationLevel
    literature_requested: bool = False
    deterministic: bool = True


class ReasoningResponse(BaseModel):
    """The platform-level answer envelope. Domain-neutral, lossless, traceable."""

    domain: str
    task: str
    summary: str

    observations: list[str] = Field(default_factory=list)
    quality_findings: list[str] = Field(default_factory=list)
    interpretations: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)

    supporting_evidence: list[Claim] = Field(default_factory=list)
    contradicting_evidence: list[Claim] = Field(default_factory=list)
    mechanistic_links: list[MechanisticLink] = Field(default_factory=list)

    missing_information: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    overinterpretation_risks: list[str] = Field(default_factory=list)

    decision_support: DecisionSupport = Field(default_factory=DecisionSupport)
    recommended_validation: list[str] = Field(default_factory=list)
    recommended_next_experiments: list[str] = Field(default_factory=list)

    literature: LiteratureOutcome = Field(default_factory=LiteratureOutcome)
    provenance: QueryProvenance

    # The domain's native report, preserved verbatim. The envelope normalises; this
    # guarantees nothing is lost to normalisation and keeps the full report traceable.
    domain_details: dict[str, Any] = Field(default_factory=dict)
