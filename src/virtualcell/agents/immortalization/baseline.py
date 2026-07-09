"""Deterministic rule-based baseline for immortalization candidate status.

This is the *lower bound* the benchmark scores the LLM against: when the LLM's
`candidate_status` disagrees with this baseline, the answer loses points and is
reviewed by a human. Keeping it deterministic (no graph, no model) makes it a
stable CI regression anchor. See ``tests/benchmarks/immortalization_v0.md``.

Marker values are normalized labels: ``high | low | increasing | plateau |
stable | worsening | improved | normal | unknown`` (or absent / ``None``).
"""

from __future__ import annotations

from enum import StrEnum

# Orthogonal flags reported alongside (not instead of) the status.
FLAG_FUNCTIONALITY_COMPROMISED = "functionality_compromised"
FLAG_TREND_NEEDED = "trend_needed"

_UNKNOWN = (None, "unknown")
_SENESCENCE_AXES = ("gammaH2AX", "SA_b_gal", "p16", "p21")


class CandidateStatus(StrEnum):
    """The v0 three-status vocabulary (deliberately coarse to avoid overcalling)."""

    POSSIBLE_CANDIDATE = "possible_candidate"
    SENESCENCE_OR_STRESS_PRONE = "senescence_or_stress_prone"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


def baseline_status(markers: dict) -> tuple[CandidateStatus, list[str]]:
    """Return the deterministic ``(status, flags)`` for a marker dict.

    Priority: a senescence/stress signal (that is not overridden by a strong
    proliferation signal) wins; then a strong proliferation signal with at least
    one measured senescence axis is a ``possible_candidate``; otherwise there is
    not enough to judge.
    """
    flags: list[str] = []
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
        flags.append(FLAG_FUNCTIONALITY_COMPROMISED)
    if markers.get("DT_trend") == "worsening" and markers.get("PDL_trend") == "increasing":
        flags.append(FLAG_TREND_NEEDED)

    if senescence_signal and not proliferation_signal:
        return CandidateStatus.SENESCENCE_OR_STRESS_PRONE, flags
    if proliferation_signal and len(measured_senescence) >= 1:
        return CandidateStatus.POSSIBLE_CANDIDATE, flags
    return CandidateStatus.INSUFFICIENT_EVIDENCE, flags
