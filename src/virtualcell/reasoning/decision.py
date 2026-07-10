"""The DecisionReport output contract.

The structured answer an assessment agent returns: a conclusion, the supporting
and contradicting evidence (as evidence-tiered :class:`Claim`s), the mechanistic
chain (reusing :class:`~virtualcell.reasoning.explain.MechanisticLink` from
`explain`), and — crucial for this domain — the overinterpretation risks and the
next experiments. It is deliberately shaped so every ``required_output`` in the
immortalization benchmark (``tests/benchmarks/immortalization_v0.md``) is
representable without overcalling.

Layering note: this lives in ``reasoning`` (not ``core.contracts`` as the plan
sketched) because it reuses ``MechanisticLink`` from ``reasoning.explain`` and
``core`` must not depend on ``reasoning``. Flagged for review.

``cell_type_relevance`` / ``species_relevance`` / ``actionability`` are *experimental*
internal scores, not (yet) axes on the core :class:`Claim` — they graduate to core
only once a benchmark failure proves the need (see roadmap Phase 3).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from virtualcell.core.evidence import Claim
from virtualcell.reasoning.explain import Explanation, MechanisticLink


class CandidateStatus(StrEnum):
    """The v0 three-status vocabulary (deliberately coarse to avoid overcalling).

    Lives here (not in the agent) so both the deterministic baseline and the
    :class:`DecisionReport` contract share one validated vocabulary.
    """

    POSSIBLE_CANDIDATE = "possible_candidate"
    SENESCENCE_OR_STRESS_PRONE = "senescence_or_stress_prone"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AssessmentFlag(StrEnum):
    """Orthogonal flags reported alongside (not instead of) the status."""

    FUNCTIONALITY_COMPROMISED = "functionality_compromised"
    TREND_NEEDED = "trend_needed"


class DecisionReport(BaseModel):
    """Structured, evidence-graded assessment output.

    ``candidate_status`` / ``flags`` are enum-validated so a typo cannot slip
    through; they are ``None`` / empty for pure mechanism questions.
    """

    conclusion: str
    candidate_status: CandidateStatus | None = None
    flags: list[AssessmentFlag] = Field(default_factory=list)

    supporting_evidence: list[Claim] = Field(default_factory=list)
    contradicting_evidence: list[Claim] = Field(default_factory=list)
    mechanistic_chain: list[MechanisticLink] = Field(default_factory=list)

    uncertainty: list[str] = Field(default_factory=list)
    missing_axes: list[str] = Field(default_factory=list)
    conflict_explanation: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    overinterpretation_risk: list[str] = Field(default_factory=list)
    # `recommended_validation` = what to verify (the axis/goal);
    # `next_experiment` = the concrete assay(s) to run.
    recommended_validation: list[str] = Field(default_factory=list)
    next_experiment: list[str] = Field(default_factory=list)

    # Experimental internal relevance scores (not core Claim axes yet); left None
    # until a scoring formula exists — do not fabricate them.
    cell_type_relevance: float | None = Field(default=None, ge=0.0, le=1.0)
    species_relevance: float | None = Field(default=None, ge=0.0, le=1.0)
    actionability: float | None = Field(default=None, ge=0.0, le=1.0)

    @classmethod
    def scaffold(
        cls,
        conclusion: str,
        explanation: Explanation | None = None,
        **fields: object,
    ) -> DecisionReport:
        """Start a report, seeding ``mechanistic_chain`` from an `explain` result.

        The agent (PR5) fills in status, supporting/contradicting evidence, risks
        and next experiments; this just wires the mechanistic chain so the two
        reasoning primitives compose.
        """
        chain = list(explanation.links) if explanation is not None else []
        return cls(conclusion=conclusion, mechanistic_chain=chain, **fields)
