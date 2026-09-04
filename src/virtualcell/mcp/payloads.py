"""What the MCP tools return, and the order they say it in.

This module is deliberately free of the MCP SDK: it turns platform objects into
plain Pydantic results, so the shape of an answer can be tested without a
protocol, a transport or a client. ``server.py`` is the only module that knows
MCP exists.

**Field order is the safety mechanism.** Every boundary this platform has built
lives *inside* the report as text — limitations, overinterpretation risks,
unmeasured axes, a refusal to conclude — and nothing forces a summarising model
to relay any of it. Hand a model a raw response dump and the failure is obvious
in hindsight::

    platform:  insufficient_evidence - the assay cannot read an allele
    model:     "The edit looks confirmed."

So the verdict, what was ignored, what is missing, what this does not establish
and what must not be concluded are declared *before* the summary. The SDK
derives the output schema and the serialized object from the declaration order
below, so the ordering is structural rather than a convention a caller has to
honour.

Nothing here decides anything. Every value is copied from a
:class:`~virtualcell.platform.contracts.ReasoningResponse` or a
:class:`~virtualcell.platform.description.DomainDescription`; if this module ever
needs to compute a scientific value, the boundary has leaked.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from virtualcell.core.consumption import ConsumptionStatus
from virtualcell.platform.contracts import ReasoningResponse
from virtualcell.platform.description import DomainDescription
from virtualcell.platform.domains import DomainRegistry

# The one sentence a caller must read before treating a null status as anything.
NO_STATUS_REASON = (
    "This response carries no status: the domain pack returned none for this task. "
    "Do not supply one, and do not read the summary as a verdict."
)


class ToolRefusal(BaseModel):
    """A refusal a caller can act on, rather than a stack trace.

    ``error`` is stable and machine-readable; ``remedy`` names the tool that fixes it.
    It travels as the *message* of the SDK's tool-error channel rather than as a return
    value, because a tool whose return type is a union of "answer or refusal" gets its
    payload wrapped by the SDK - and that wrapper would flatten the field ordering
    :class:`ReasonResult` relies on. The ordering protects every successful answer; the
    refusal path can afford a string.
    """

    model_config = ConfigDict(frozen=True)

    error: str = Field(description="Stable machine-readable failure kind.")
    detail: str = Field(description="What was wrong, in one sentence.")
    remedy: str = Field(description="What to call or change next.")

    def message(self) -> str:
        """The refusal as compact JSON, so a caller can parse it or read it."""
        return self.model_dump_json()

    @classmethod
    def parse(cls, message: str) -> ToolRefusal:
        """Recover a refusal from a tool-error message, whatever prefix wraps it."""
        start = message.find("{")
        if start < 0:
            raise ValueError(f"no refusal payload in {message!r}")
        return cls.model_validate_json(message[start:])


# --------------------------------------------------------------------------- #
# list_domains
# --------------------------------------------------------------------------- #


class DomainSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    domain: str
    summary: str
    tasks: list[str]


class ListDomainsResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    domains: list[DomainSummary]


def list_domains(registry: DomainRegistry) -> ListDomainsResult:
    """Every registered domain, its one-line purpose and its task names."""
    summaries = []
    for name in registry.domains():
        described = registry.get(name).describe()
        summaries.append(
            DomainSummary(
                domain=described.domain,
                summary=described.summary,
                tasks=[task.name for task in described.tasks],
            )
        )
    return ListDomainsResult(domains=summaries)


# --------------------------------------------------------------------------- #
# describe_domain
# --------------------------------------------------------------------------- #


class AxisInfo(BaseModel):
    """One thing a caller may measure and send, described well enough to send it."""

    model_config = ConfigDict(frozen=True)

    send_as: str = Field(description="The exact key to use in the experiment payload.")
    description: str
    value_type: str
    kind: str = Field(
        description=(
            "status: can move the verdict. guidance: refines flags, safety and next "
            "steps only. context: recorded, reads nothing."
        )
    )
    required: bool
    vocabulary: list[str] | None = Field(
        default=None, description="If present, the only accepted values."
    )
    minimum: float | None = None
    maximum: float | None = None
    unmeasured_value: str | None = Field(
        default=None,
        description=(
            "How to spell 'no reading was taken'. Sending it is not supplying the "
            "measurement - it restates that nobody looked."
        ),
    )
    used_for: list[str] = Field(default_factory=list)


class TaskInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    purpose: str
    required_axes: list[str]
    reads_axes: list[str]
    example: dict[str, Any] | None = None


class DescribeDomainResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    domain: str
    summary: str
    status_vocabulary: list[str]
    flags: list[str]
    unsupported_policy: str
    tasks: list[TaskInfo]
    axes: list[AxisInfo]


def _axis_info(axis: Any) -> AxisInfo:
    return AxisInfo(
        send_as=axis.name,
        description=axis.description,
        value_type=axis.value_type.value,
        kind=axis.kind.value,
        required=axis.required,
        vocabulary=list(axis.vocabulary) if axis.vocabulary else None,
        minimum=axis.minimum,
        maximum=axis.maximum,
        unmeasured_value=axis.unmeasured_value,
        used_for=list(axis.used_for),
    )


def describe_domain(description: DomainDescription) -> DescribeDomainResult:
    """A pack's own declaration, rendered for a caller assembling a payload."""
    return DescribeDomainResult(
        domain=description.domain,
        summary=description.summary,
        status_vocabulary=list(description.status_vocabulary),
        flags=list(description.flags),
        unsupported_policy=description.unsupported_policy,
        tasks=[
            TaskInfo(
                name=task.name,
                purpose=task.purpose,
                required_axes=list(task.required_axes),
                reads_axes=list(task.reads_axes),
                example=dict(task.example) if task.example else None,
            )
            for task in description.tasks
        ],
        axes=[_axis_info(axis) for axis in description.axes],
    )


# --------------------------------------------------------------------------- #
# reason
# --------------------------------------------------------------------------- #


class MissingInputInfo(BaseModel):
    """A gap a caller can close by measuring it and sending it back."""

    model_config = ConfigDict(frozen=True)

    id: str
    send_as: str = Field(description="The canonical key to use when resubmitting.")
    label: str = Field(description="The human name for the same axis, for prose only.")
    why: str
    task: str
    value_type: str
    vocabulary: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    unmeasured_value: str | None = None


class ConsumptionInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    submitted_as: str
    canonical_name: str | None = None
    status: str
    used_for: list[str] = Field(default_factory=list)
    reason: str | None = None


class ClaimInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    statement: str
    tier: str
    confidence: float | None = None
    citations: list[str] = Field(default_factory=list)


class MechanismInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    tier: str
    path: list[str]


class ReasonResult(BaseModel):
    """The reasoning answer, ordered so the refusals are read before the summary.

    The first six blocks are what a caller must relay. ``summary`` is deliberately
    seventh: a summary placed first gets copied and the caveats under it dropped.
    """

    model_config = ConfigDict(frozen=True)

    domain: str
    task: str

    # 1. the verdict, and an explicit reason when there is none
    status: str | None = Field(description="The pack's own status, or null. Never invent one.")
    status_reason: str
    flags: list[str] = Field(default_factory=list)
    trend_required: bool = False

    # 2. what the answer was computed WITHOUT
    unsupported_measurements: list[str] = Field(
        default_factory=list,
        description=(
            "Keys the domain did not recognise. A non-empty list means the answer "
            "was computed without them: correct the spelling and re-send rather "
            "than reporting this answer."
        ),
    )
    quality_excluded_measurements: list[str] = Field(default_factory=list)

    # 3. what to measure next, under a name the platform will accept back
    missing_inputs: list[MissingInputInfo] = Field(default_factory=list)

    # 4. what this answer does not establish
    limitations: list[str] = Field(default_factory=list)

    # 5. what must not be concluded from it
    overinterpretation_risks: list[str] = Field(default_factory=list)

    # 6. lab work to do - never experiment keys
    recommended_validation: list[str] = Field(
        default_factory=list,
        description=(
            "Things for a person to verify. Relay them; never synthesise a value "
            "for one and never use one as an experiment key."
        ),
    )
    recommended_next_experiments: list[str] = Field(default_factory=list)

    # 7. only now, the prose
    summary: str

    # 8. evidence and mechanism
    observations: list[str] = Field(default_factory=list)
    interpretations: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    quality_findings: list[str] = Field(default_factory=list)
    supporting_evidence: list[ClaimInfo] = Field(default_factory=list)
    contradicting_evidence: list[ClaimInfo] = Field(default_factory=list)
    mechanistic_links: list[MechanismInfo] = Field(default_factory=list)

    # 9. the human-readable twin of missing_inputs, kept distinct on purpose
    missing_information: list[str] = Field(
        default_factory=list,
        description=(
            "Prose for a person. It may spell an axis differently from the key. "
            "Never use one of these strings as an experiment key - use "
            "missing_inputs[].send_as."
        ),
    )

    # 10. provenance and full ledger
    measurement_consumption: list[ConsumptionInfo] = Field(default_factory=list)
    literature_status: str
    provenance: dict[str, Any] = Field(default_factory=dict)


def _claims(claims: Any) -> list[ClaimInfo]:
    return [
        ClaimInfo(
            statement=claim.statement,
            tier=claim.tier.value,
            confidence=claim.confidence,
            citations=list(claim.citations),
        )
        for claim in claims
    ]


def _names(report: Any, status: ConsumptionStatus) -> list[str]:
    return [entry.submitted_as for entry in report.by_status(status)]


def reason(response: ReasoningResponse) -> ReasonResult:
    """Reorder a :class:`ReasoningResponse`; add nothing, drop no safety field."""
    support = response.decision_support
    status = support.status
    consumption = response.measurement_consumption

    return ReasonResult(
        domain=response.domain,
        task=response.task,
        status=status,
        status_reason=(
            NO_STATUS_REASON
            if status is None
            else "The domain pack returned this status from its own vocabulary."
        ),
        flags=list(support.flags),
        trend_required=support.trend_required,
        unsupported_measurements=_names(consumption, ConsumptionStatus.UNSUPPORTED),
        quality_excluded_measurements=_names(consumption, ConsumptionStatus.QUALITY_EXCLUDED),
        missing_inputs=[
            MissingInputInfo(
                id=item.id,
                send_as=item.canonical_axis,
                label=item.label,
                why=item.why,
                task=item.task,
                value_type=item.value_type.value,
                vocabulary=list(item.vocabulary) if item.vocabulary else None,
                minimum=item.minimum,
                maximum=item.maximum,
                unmeasured_value=item.unmeasured_value,
            )
            for item in response.missing_inputs
        ],
        limitations=list(response.limitations),
        overinterpretation_risks=list(response.overinterpretation_risks),
        recommended_validation=list(response.recommended_validation),
        recommended_next_experiments=list(response.recommended_next_experiments),
        summary=response.summary,
        observations=list(response.observations),
        interpretations=list(response.interpretations),
        hypotheses=list(response.hypotheses),
        uncertainties=list(response.uncertainties),
        quality_findings=list(response.quality_findings),
        supporting_evidence=_claims(response.supporting_evidence),
        contradicting_evidence=_claims(response.contradicting_evidence),
        mechanistic_links=[
            MechanismInfo(tier=link.tier.value, path=list(link.path))
            for link in response.mechanistic_links
        ],
        missing_information=list(response.missing_information),
        measurement_consumption=[
            ConsumptionInfo(
                submitted_as=entry.submitted_as,
                canonical_name=entry.canonical_name,
                status=entry.status.value,
                used_for=list(entry.used_for),
                reason=entry.reason,
            )
            for entry in consumption.entries
        ],
        literature_status=response.literature.status.value,
        provenance=response.provenance.model_dump(mode="json"),
    )
