"""Scenario -> input adapter (PR5c-3).

The single place that maps a normalized scenario dict (benchmark shape) to the
typed :class:`ImmortalizationAssessmentInput`, including the external ``construct``
key -> internal ``construct_type`` rename. It imports no benchmark file and does
not mutate the input dict.
"""

from __future__ import annotations

from typing import Any

from virtualcell.agents.immortalization.models import (
    AssessmentIntent,
    ImmortalizationAssessmentInput,
)

_MARKER_FIELDS = (
    "PDL_trend",
    "DT_trend",
    "gammaH2AX",
    "SA_b_gal",
    "p16",
    "p21",
    "adipogenic_retention",
)
# Keys consumed as typed fields (everything else is preserved in ``measurements``).
_TOP_LEVEL = {*_MARKER_FIELDS, "species", "cell_type", "construct"}


def input_from_scenario(
    intent: str | AssessmentIntent, scenario: dict[str, Any]
) -> ImmortalizationAssessmentInput:
    """Build an assessment input from an intent and a normalized scenario dict."""
    markers = {key: scenario[key] for key in _MARKER_FIELDS if key in scenario}
    extras = {key: value for key, value in scenario.items() if key not in _TOP_LEVEL}
    return ImmortalizationAssessmentInput(
        intent=intent,
        species=scenario.get("species"),
        cell_type=scenario.get("cell_type"),
        construct_type=scenario.get("construct", "unknown"),
        measurements=extras,
        **markers,
    )
