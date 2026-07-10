"""Deterministic DecisionReport builder for immortalization assessment (PR5a).

Status and flags are decided **only** by ``baseline_status`` (the deterministic
anchor). This builder assembles the rest of the report — both-sided evidence,
missing axes, conflict explanation, overinterpretation risk, and the split between
validation axes and concrete next experiments. No LLM, no graph, no limitation
catalog (those are PR5b/PR5c). Claims over synthetic benchmark data carry no
fabricated citations.
"""

from __future__ import annotations

from virtualcell.agents.immortalization.baseline import baseline_status
from virtualcell.agents.immortalization.models import (
    ASSESSMENT_INTENTS,
    AssessmentIntent,
    ImmortalizationAssessmentInput,
    MarkerValue,
    RetentionValue,
)
from virtualcell.core.evidence import Claim, EvidenceTier
from virtualcell.reasoning.decision import AssessmentFlag, CandidateStatus, DecisionReport

_SENESCENCE_AXES = ("gammaH2AX", "SA_b_gal", "p16", "p21")
_AXIS_LABEL = {"gammaH2AX": "gammaH2AX", "SA_b_gal": "SA-b-Gal", "p16": "p16", "p21": "p21"}
_AXIS_ASSAY = {
    "gammaH2AX": "gammaH2AX immunofluorescence",
    "SA_b_gal": "SA-b-Gal assay",
    "p16": "p16/p21 qPCR",
    "p21": "p16/p21 qPCR",
}

_CONCLUSIONS = {
    CandidateStatus.POSSIBLE_CANDIDATE: (
        "Possible immortalization candidate: proliferation continues with a low "
        "senescence signal, but this is not confirmed immortalization and key axes "
        "remain unverified."
    ),
    CandidateStatus.SENESCENCE_OR_STRESS_PRONE: (
        "Senescence/stress signal predominates; not an immortalization candidate on "
        "current evidence."
    ),
    CandidateStatus.INSUFFICIENT_EVIDENCE: (
        "Insufficient evidence to judge: core senescence axes are unmeasured."
    ),
}


class UnsupportedIntentError(ValueError):
    """Raised when the PR5a builder is asked to handle a non-assessment intent."""


def _measurement(statement: str) -> Claim:
    return Claim(
        statement=statement,
        tier=EvidenceTier.ESTABLISHED,
        confidence=0.9,
        assumptions=["Input measurements are valid and quality-controlled."],
    )


def _interpretation(statement: str, confidence: float = 0.7) -> Claim:
    return Claim(statement=statement, tier=EvidenceTier.HYPOTHESIS, confidence=confidence)


def _missing_axes(data: ImmortalizationAssessmentInput) -> list[str]:
    values = {
        "gammaH2AX": data.gammaH2AX,
        "SA_b_gal": data.SA_b_gal,
        "p16": data.p16,
        "p21": data.p21,
    }
    return [axis for axis in _SENESCENCE_AXES if values[axis] == MarkerValue.UNKNOWN]


def _supporting(data: ImmortalizationAssessmentInput, status: CandidateStatus) -> list[Claim]:
    claims: list[Claim] = []
    if data.PDL_trend == MarkerValue.INCREASING:
        claims.append(_measurement("Population doublings continue to increase."))
    if data.DT_trend in (MarkerValue.STABLE, MarkerValue.IMPROVED):
        claims.append(_measurement("Doubling time is stable or improving."))
    if data.gammaH2AX == MarkerValue.LOW:
        claims.append(_measurement("gammaH2AX is low, indicating low DNA damage."))
    if data.SA_b_gal == MarkerValue.LOW:
        claims.append(_measurement("SA-b-Gal staining is low."))
    if data.p16 == MarkerValue.NORMAL:
        claims.append(_measurement("p16 is at a normal level."))
    if status == CandidateStatus.POSSIBLE_CANDIDATE:
        claims.append(
            _interpretation(
                "Sustained proliferation with a low DNA-damage signal is consistent with "
                "a possible immortalization candidate - not confirmed immortalization."
            )
        )
    return claims


def _contradicting(data: ImmortalizationAssessmentInput, status: CandidateStatus) -> list[Claim]:
    claims: list[Claim] = []
    if data.PDL_trend == MarkerValue.PLATEAU:
        claims.append(_measurement("Population doublings have plateaued."))
    if data.DT_trend == MarkerValue.WORSENING:
        claims.append(_measurement("Doubling time is worsening."))
    if data.gammaH2AX == MarkerValue.HIGH:
        claims.append(_measurement("gammaH2AX is high, indicating DNA damage."))
    if data.SA_b_gal == MarkerValue.HIGH:
        claims.append(_measurement("SA-b-Gal staining is high."))
    if data.p16 == MarkerValue.HIGH:
        claims.append(_measurement("p16 is elevated."))
    if data.p21 == MarkerValue.HIGH:
        claims.append(_measurement("p21 is elevated."))
    if data.adipogenic_retention == RetentionValue.LOST:
        claims.append(_measurement("Adipogenic differentiation capacity is lost."))
    missing = _missing_axes(data)
    if missing:
        labels = ", ".join(_AXIS_LABEL[a] for a in missing)
        claims.append(
            _interpretation(
                f"Key senescence axes are unmeasured ({labels}); candidacy cannot be confirmed."
            )
        )
    if status == CandidateStatus.SENESCENCE_OR_STRESS_PRONE:
        claims.append(
            _interpretation(
                "The combination of stress/senescence markers indicates approach to or "
                "entry into senescence."
            )
        )
    return claims


def _conflict_explanation(data: ImmortalizationAssessmentInput) -> list[str]:
    if data.intent != AssessmentIntent.CONFLICTING_EVIDENCE_ASSESSMENT:
        return []
    return [
        "Acute DNA-damage markers (e.g. gammaH2AX, p21) conflict with low chronic-senescence "
        "markers (e.g. SA-b-Gal, normal p16); distinguish acute stress from established "
        "senescence before concluding."
    ]


def _risks(
    data: ImmortalizationAssessmentInput,
    status: CandidateStatus,
    flags: list[AssessmentFlag],
) -> list[str]:
    risks = ["Single-marker or single-timepoint reads are weak; trends and corroboration matter."]
    if status == CandidateStatus.POSSIBLE_CANDIDATE:
        risks.append(
            "Do not call immortalization: sustained proliferation is necessary but not "
            "sufficient, and verification is incomplete."
        )
    if status == CandidateStatus.SENESCENCE_OR_STRESS_PRONE:
        risks.append(
            "Do not discard prematurely: some primary cells immortalize spontaneously only "
            "after prolonged culture."
        )
    if AssessmentFlag.FUNCTIONALITY_COMPROMISED in flags:
        risks.append(
            "Do not conflate immortalization with utility: lost differentiation can make the "
            "line unsuitable despite sustained proliferation."
        )
    return risks


def _validation_and_experiments(
    data: ImmortalizationAssessmentInput,
    status: CandidateStatus,
    missing: list[str],
) -> tuple[list[str], list[str]]:
    recommended: list[str] = []
    next_experiment: list[str] = []

    # Only recommend measuring axes that are actually missing (don't re-run measured ones).
    if missing:
        recommended.append("Senescence axis (gammaH2AX / SA-b-Gal / p16 / p21)")
        for axis in missing:
            assay = _AXIS_ASSAY[axis]
            if assay not in next_experiment:
                next_experiment.append(assay)

    # Telomere/TERT are never in the v0 input, so always worth verifying.
    recommended.append("Telomere-maintenance axis (telomere length, TERT activity)")
    next_experiment.extend(["Telomere-length assay", "TERT activity assay"])

    if status == CandidateStatus.POSSIBLE_CANDIDATE:
        recommended.append("Replicative-capacity trend over long-term passage")
        next_experiment.append("Long-term PDL tracking")

    # Conflicting evidence warrants re-measurement over time (explicitly allowed).
    if data.intent == AssessmentIntent.CONFLICTING_EVIDENCE_ASSESSMENT:
        recommended.append("Distinguish acute stress from established senescence")
        next_experiment.append("Time-course re-measurement of gammaH2AX and senescence markers")

    return recommended, next_experiment


def build_decision_report(data: ImmortalizationAssessmentInput) -> DecisionReport:
    """Assemble a deterministic DecisionReport for an assessment-intent input."""
    if data.intent not in ASSESSMENT_INTENTS:
        raise UnsupportedIntentError(
            f"intent {data.intent.value!r} is not handled by the deterministic assessment "
            "builder (mechanism/hypothesis intents arrive in a later PR)"
        )

    status, flags = baseline_status(data.marker_dict())
    missing = _missing_axes(data)
    recommended, next_experiment = _validation_and_experiments(data, status, missing)

    return DecisionReport(
        conclusion=_CONCLUSIONS[status],
        candidate_status=status,
        flags=flags,
        supporting_evidence=_supporting(data, status),
        contradicting_evidence=_contradicting(data, status),
        mechanistic_chain=[],  # graph grounding lands in PR5c
        missing_axes=[_AXIS_LABEL[a] for a in missing],
        conflict_explanation=_conflict_explanation(data),
        overinterpretation_risk=_risks(data, status, flags),
        recommended_validation=recommended,
        next_experiment=next_experiment,
        # relevance scores intentionally left None (no scoring formula yet).
    )
