"""Tests for the scenario -> input adapter (PR5c-3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.models import ConstructType, MarkerValue


def test_construct_key_is_renamed_to_construct_type() -> None:
    inp = input_from_scenario(
        "mechanism_explanation", {"construct": "TERT_only", "cell_type": "p16_competent_primary"}
    )
    assert inp.construct_type is ConstructType.TERT_ONLY
    assert inp.cell_type == "p16_competent_primary"


def test_tert_plus_cdk4_construct() -> None:
    inp = input_from_scenario("mechanism_explanation", {"construct": "TERT_plus_CDK4"})
    assert inp.construct_type is ConstructType.TERT_PLUS_CDK4


def test_unmodeled_data_is_preserved_in_measurements() -> None:
    scenario = {
        "PDL_trend": "increasing",
        "DT_series": {"P25": 42, "P30": 58},
        "PPARG": "down",
        "CEBPA": "down",
        "FABP4": "down",
        "OilRedO": "weak",
    }
    inp = input_from_scenario("immortalization_assessment", scenario)
    assert inp.PDL_trend is MarkerValue.INCREASING
    assert inp.measurements["DT_series"]["P25"] == 42
    for key in ("PPARG", "CEBPA", "FABP4", "OilRedO"):
        assert inp.measurements[key] == scenario[key]


def test_invalid_marker_value_raises() -> None:
    with pytest.raises(ValidationError):
        input_from_scenario("immortalization_assessment", {"PDL_trend": "skyrocketing"})


def test_scenario_dict_is_not_mutated() -> None:
    scenario = {"construct": "TERT_only", "PDL_trend": "increasing", "DT_series": {"P25": 42}}
    snapshot = {"construct": "TERT_only", "PDL_trend": "increasing", "DT_series": {"P25": 42}}
    input_from_scenario("mechanism_explanation", scenario)
    assert scenario == snapshot
