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
    proliferation signal) wins; then a strong proliferation signal with at least
    one measured senescence axis is a ``possible_candidate``; otherwise there is
    not enough to judge.
    """
    flags: list[AssessmentFlag] = []
    measured_senescence = [a for a in _SENESCENCE_AXES if markers.get(a) not in _UNKNOWN]

    # Functional stress holds even without molecular markers: a worsening doubling
    # time or a plateaued PDL is itself a stress signal.
    functional_stress = (
        markers.get("PDL_trend") == "plateau" or markers.get("DT_trend") == "worsening"
    )
    molecular_senescence = any(
        markers.get(axis) == "high" for axis in ("gammaH2AX", "SA_b_gal", "p16", "p21")
    )
    senescence_signal = functional_stress or molecular_senescence

    # Proliferation signal is a strong triple condition.
    proliferation_signal = (
        markers.get("PDL_trend") == "increasing"
        and markers.get("gammaH2AX") == "low"
        and markers.get("DT_trend") in ("stable", "improved")
    )

    # Orthogonal flags.
    if markers.get("adipogenic_retention") == "lost":
        flags.append(AssessmentFlag.FUNCTIONALITY_COMPROMISED)
    if markers.get("DT_trend") == "worsening" and markers.get("PDL_trend") == "increasing":
        flags.append(AssessmentFlag.TREND_NEEDED)

    if senescence_signal and not proliferation_signal:
        return CandidateStatus.SENESCENCE_OR_STRESS_PRONE, flags
    if proliferation_signal and len(measured_senescence) >= 1:
        return CandidateStatus.POSSIBLE_CANDIDATE, flags
    return CandidateStatus.INSUFFICIENT_EVIDENCE, flags
