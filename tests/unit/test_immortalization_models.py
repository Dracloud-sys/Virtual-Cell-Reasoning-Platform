"""Tests for the normalized immortalization assessment input model (PR5a)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from virtualcell.agents.immortalization.models import (
    ImmortalizationAssessmentInput,
    MarkerValue,
    RetentionValue,
)


def test_marker_values_coerce_from_strings_and_default_unknown() -> None:
    inp = ImmortalizationAssessmentInput(
        intent="immortalization_assessment", PDL_trend="increasing", gammaH2AX="low"
    )
    assert inp.PDL_trend is MarkerValue.INCREASING
    assert inp.gammaH2AX is MarkerValue.LOW
    assert inp.SA_b_gal is MarkerValue.UNKNOWN  # unspecified -> unknown


def test_invalid_marker_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ImmortalizationAssessmentInput(
            intent="immortalization_assessment", PDL_trend="skyrocketing"
        )


def test_retention_uses_its_own_vocabulary() -> None:
    inp = ImmortalizationAssessmentInput(
        intent="immortalization_vs_functionality", adipogenic_retention="lost"
    )
    assert inp.adipogenic_retention is RetentionValue.LOST
    # A trend/level value is not valid for retention.
    with pytest.raises(ValidationError):
        ImmortalizationAssessmentInput(
            intent="immortalization_assessment", adipogenic_retention="high"
        )


def test_measurements_preserve_unmodeled_data() -> None:
    inp = ImmortalizationAssessmentInput(
        intent="immortalization_assessment",
        measurements={"DT_series": {"P25": 42}, "PPARG": "down"},
    )
    assert inp.measurements["DT_series"]["P25"] == 42
    assert inp.measurements["PPARG"] == "down"


def test_marker_dict_maps_baseline_keys() -> None:
    inp = ImmortalizationAssessmentInput(intent="immortalization_assessment", gammaH2AX="high")
    d = inp.marker_dict()
    assert d["gammaH2AX"] == "high"
    assert d["p16"] == "unknown"
