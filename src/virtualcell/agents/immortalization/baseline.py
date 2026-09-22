"""Deterministic rule-based baseline for immortalization candidate status.

This is the *lower bound* the benchmark scores the LLM against: when the LLM's
`candidate_status` disagrees with this baseline, the answer loses points and is
reviewed by a human. Keeping it deterministic (no graph, no model) makes it a
stable CI regression anchor. See ``tests/benchmarks/immortalization_v0.md``.

Marker values are normalized labels: ``high | low | increasing | plateau |
stable | worsening | improved | normal | unknown`` (or absent / ``None``).
"""

from __future__ import annotations

# The status/flag vocabularies live with the DecisionReport contract so the
# deterministic baseline and the report share one validated set of values.
from virtualcell.reasoning.decision import AssessmentFlag, CandidateStatus

__all__ = ["AssessmentFlag", "CandidateStatus", "baseline_status"]

_UNKNOWN = (None, "unknown")
_SENESCENCE_AXES = ("gammaH2AX", "SA_b_gal", "p16", "p21")


def baseline_status(markers: dict) -> tuple[CandidateStatus, list[AssessmentFlag]]:
    """Return the deterministic ``(status, flags)`` for a marker dict.

    Priority: a senescence/stress signal (that is not overridden by a strong
    proliferation signal) wins; then a strong proliferation signal — sustained
    doublings, no worsening doubling time, and at least one senescence axis measured
    and reading low while none reads high — is a ``possible_candidate``; otherwise
    there is not enough to judge.
    """
    flags: list[AssessmentFlag] = []

    # Functional stress holds even without molecular markers: a worsening doubling
    # time or a plateaued PDL is itself a stress signal.
    functional_stress = (
        markers.get("PDL_trend") == "plateau" or markers.get("DT_trend") == "worsening"
    )
    molecular_senescence = any(markers.get(axis) == "high" for axis in _SENESCENCE_AXES)
    senescence_signal = functional_stress or molecular_senescence

    # A candidate needs sustained proliferation, no affirmative stress, and at least one
    # senescence axis measured and reading low. **Which** axis is deliberately unspecified.
    # This condition used to name gammaH2AX, and a survey of 50 papers establishing
    # immortalized lines found gammaH2AX in zero of them (see
    # tests/benchmarks/literature/), so the positive branch could not be reached from
    # published characterization data at all. Requiring senescence evidence is right and
    # stays; requiring one particular marker the field does not run was the defect.
    #
    # "Cleared" is one axis reading low *and no axis reading high* — not merely one low
    # reading somewhere. The first cut of this change omitted the second half and benchmark
    # IMM-Q10 caught it: that question is deliberately contradictory (gammaH2AX high, p21
    # high, SA-b-gal low) and a single low marker was enough to outvote two high ones.
    # Generalizing which marker counts must not become letting one cherry-pick a clean one.
    senescence_cleared = (
        any(markers.get(axis) == "low" for axis in _SENESCENCE_AXES) and not molecular_senescence
    )
    proliferation_signal = (
        markers.get("PDL_trend") == "increasing"
        # Not `in ("stable", "improved")`: doubling time appears in 16% of surveyed
        # abstracts, and an unreported one is silence. A *worsening* one is an affirmative
        # finding and still blocks, which is also why it feeds `functional_stress` above.
        and markers.get("DT_trend") != "worsening"
        and senescence_cleared
    )

    # Orthogonal flags.
    if markers.get("adipogenic_retention") == "lost":
        flags.append(AssessmentFlag.FUNCTIONALITY_COMPROMISED)
    # Reported beside the status, never through it: instability does not stop the cells
    # proliferating, so it cannot retract a call the proliferation axes support.
    if markers.get("genomic_stability") == "abnormal":
        flags.append(AssessmentFlag.GENOMIC_INSTABILITY_DETECTED)
    if markers.get("DT_trend") == "worsening" and markers.get("PDL_trend") == "increasing":
        flags.append(AssessmentFlag.TREND_NEEDED)

    if senescence_signal and not proliferation_signal:
        return CandidateStatus.SENESCENCE_OR_STRESS_PRONE, flags
    # The "at least one axis measured" condition that used to sit here is now carried by
    # `senescence_cleared`, which is strictly stronger: measured *and* reading low.
    if proliferation_signal:
        return CandidateStatus.POSSIBLE_CANDIDATE, flags
    return CandidateStatus.INSUFFICIENT_EVIDENCE, flags
