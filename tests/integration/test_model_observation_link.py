"""The model-observation link (docs/research_sessions/model_observation_link_v0/).

Every call is `compare_model_observation` on `build_server()`, with model results from
`run_logic_model` (or, for ERK, the stored window record). The expected meanings are those of
`expected.md`, written before the code. These are synthetic contract cases; they show no
biological performance.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from virtualcell.mcp.payloads import ToolRefusal
from virtualcell.mcp.server import build_server

sdk_errors = pytest.importorskip("mcp.server.mcpserver.exceptions")
CASE = (
    Path(__file__).resolve().parents[2] / "docs" / "research_sessions" / "model_observation_link_v0"
)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("model_observation_link_cases", CASE / "cases.py")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode, before = True, sys.dont_write_bytecode
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


@pytest.fixture(scope="module")
def server():
    return build_server()


@pytest.fixture(scope="module")
def cases(mod, server):
    return mod.synthetic_cases(server) | mod.erk_cases()


def _compare(server, args):
    result = asyncio.run(server.call_tool("compare_model_observation", args))
    assert not result.is_error, result.content
    return result.structured_content


def _refused(server, args) -> ToolRefusal:
    with pytest.raises(sdk_errors.ToolError) as caught:
        asyncio.run(server.call_tool("compare_model_observation", args))
    return ToolRefusal.parse(str(caught.value))


# --- comparable inputs give real results ------------------------------------------------------ #


def test_t1_a_stated_correspondence_gives_a_conditional_match(server, cases):
    out = _compare(server, cases["T1_consistent"])
    assert out["comparability"] == "comparable"
    assert (out["relation"], out["result"]) == ("single_match", "consistent")
    assert out["scientific_validity_checked"] is False
    assert out["correspondence"]["stated_by"] == "researcher"
    assert out["observation_meaning"] == "quantitative_change"
    assert out["hypothesis_ids"] == ["H1"]


def test_t2_the_same_correspondence_gives_a_conditional_mismatch(server, cases):
    out = _compare(server, cases["T2_inconsistent"])
    assert (out["comparability"], out["relation"], out["result"]) == (
        "comparable",
        "outside",
        "inconsistent",
    )
    assert "refut" not in json.dumps(out["reasons"])


def test_t3_several_model_values_are_not_a_single_prediction(server, cases):
    out = _compare(server, cases["T3_partial"])
    assert out["comparability"] == "comparable"
    assert (out["relation"], out["result"]) == ("partial", "undecided")
    assert out["model_claim"]["model_values"] == ["increase", "no_change"]
    # The cases are kept apart, not merged into one value.
    assert len(out["model_claim"]["groups"]) == 2


# --- inputs that are not compared, and why -------------------------------------------------- #


def test_t4_same_word_is_not_a_correspondence_and_the_observation_is_kept(server, cases):
    out = _compare(server, cases["T4_meaning"])
    assert out["comparability"] == "correspondence_unresolved"
    assert "model_value_without_correspondence" in out["reasons"]
    assert out["result"] is None and out["relation"] is None
    assert out["observation"]["observed"] == "increase"
    assert out["observation"]["treatment_values"] == [2.0, 2.2]
    assert out["model_claim"]["model_values"] == ["no_change"]


def test_t4b_a_magnitude_question_is_outside_a_boolean_model(server, cases):
    out = _compare(server, cases["T4b_magnitude"])
    assert out["comparability"] == "outside_model_representation"
    assert "richer_model" in out["needs"]
    # The data were complete; more of them would not change this.
    assert out["observation"]["status"] == "compared"
    assert "more_measurement" not in out["needs"]


def test_t5_below_detection_is_not_absence_or_a_model_error(server, cases):
    out = _compare(server, cases["T5_detection"])
    assert out["comparability"] == "correspondence_unresolved"
    assert out["reasons"] == ["model_value_without_correspondence"]
    assert out["observation_meaning"] == "analytical_detection"
    assert out["observation"]["observed"] == "absent"
    assert out["result"] is None
    text = json.dumps({k: out[k] for k in ("reasons", "needs", "relation", "result")})
    assert "biolog" not in text and "error" not in text


# --- references, conditions and time points -------------------------------------------------- #


def test_t6_normalisation_reference_and_comparison_arm_stay_apart(server, cases):
    out = _compare(server, cases["T6_reference_roles"])
    obs = out["observation"]
    # U0126 at day 1 against DMSO at day 1; PBS and the day-2 reading are not read.
    assert obs["treatment_values"] == [2.0] and obs["reference_values"] == [1.0]
    assert obs["treatment_summary"]["recorded"] == 1 and obs["reference_summary"]["recorded"] == 1
    assert obs["reference_link"] == "structural"
    assert out["result"] == "consistent"


def test_t6b_a_host_proposed_reference_is_held(server, cases):
    out = _compare(server, cases["T6b_host_proposed_reference"])
    assert out["comparability"] == "correspondence_unresolved"
    assert out["reasons"] == ["observation_reference_host_proposed"]
    assert out["result"] is None and out["explored_result"] is None
    assert out["if_accepted"] == "consistent"


def test_t6c_a_baseline_standing_for_another_reference_is_not_compared(server, cases):
    out = _compare(server, cases["T6c_baseline_differs"])
    assert out["comparability"] == "correspondence_unresolved"
    assert "baseline_correspondence_differs_from_mapping_versus" in out["reasons"]


# --- quality and computation limits ---------------------------------------------------------- #


def test_t7_left_out_readings_are_counted_and_the_rest_compared(server, cases):
    out = _compare(server, cases["T7_left_out"])
    assert out["observation"]["left_out"] == {"excluded": 1, "missing": 1}
    assert out["observation"]["treatment_values"] == [2.0]
    assert out["result"] == "consistent"


def test_t7b_no_rule_is_insufficient_and_keeps_the_observation(server, cases):
    out = _compare(server, cases["T7b_no_rule"])
    assert out["comparability"] == "insufficient"
    assert "observation_not_classified" in out["reasons"]
    assert "no_decision_rule" in out["observation"]["reasons"]
    assert out["needs"] == ["state_or_review_correspondence"]
    assert out["observation"]["treatment_values"] == [2.0, 2.2]


def test_t7c_incomplete_exploration_compares_only_what_was_explored(server, cases):
    out = _compare(server, cases["T7c_partial_exploration"])
    assert out["comparability"] == "comparable"
    assert out["explored_result"] == "consistent"
    assert out["result"] == "undecided"
    assert out["model_claim"]["applies_to"] == "explored_cases_only"
    assert "model_exploration_incomplete" in out["reasons"] and "check_record" in out["needs"]


def test_t7d_model_values_not_computed_are_insufficient(server, cases):
    out = _compare(server, cases["T7d_not_computed"])
    assert out["comparability"] == "insufficient"
    assert "model_values_not_computed" in out["reasons"]
    assert out["result"] is None


# --- selection and reproducibility ----------------------------------------------------------- #


@pytest.mark.parametrize(
    ("change", "field"),
    [
        (lambda a: a["link"]["model"].update(target="Nope"), "target"),
        (lambda a: a["link"]["model"].update(run_sha256="0" * 64), "run_sha256"),
        (lambda a: a["link"]["model"].update(window={"first": 0, "last": 4}), "window"),
        (lambda a: a["link"]["model"].update(baseline="other"), "baseline"),
        (
            lambda a: a["link"]["correspondence"]["table"].append(
                {"model_value": "increase", "observed_value": "decrease"}
            ),
            "both",
        ),
        (
            lambda a: a["link"]["correspondence"]["table"].append(
                {"model_value": "active", "observed_value": "present"}
            ),
            "model_value",
        ),
    ],
)
def test_t8_selections_that_are_not_exactly_one_are_refused(server, cases, change, field):
    args = copy.deepcopy(cases["T1_consistent"])
    change(args)
    refusal = _refused(server, args)
    assert refusal.error == "malformed_model_observation_link"
    assert field in refusal.detail


def test_t8_order_and_repetition_change_nothing_and_inputs_are_untouched(server, cases):
    args = copy.deepcopy(cases["T3_partial"])
    before = copy.deepcopy(args)
    a = _compare(server, args)
    assert args == before
    flipped = copy.deepcopy(args)
    flipped["link"]["correspondence"]["table"].reverse()
    b = _compare(server, flipped)
    for key in ("comparability", "relation", "result", "reasons", "needs", "model_claim"):
        assert a[key] == b[key], key
    again = _compare(server, args)
    assert again == a


def test_a_full_window_response_and_its_subset_give_the_same_comparison(server, cases):
    args = cases["T1_consistent"]
    full = _compare(server, args)
    r = args["model_result"]
    subset = {
        "model_id": r["model_id"],
        "model_sha256": r["model_sha256"],
        "run_sha256": r["run_sha256"],
        "scenario": r["scenario"]["name"],
        "baseline": r["baseline"]["name"],
        "cases_explored": r["cases_explored"],
        "cases_total": r["cases_total"],
        "exploration_complete": r["exploration_complete"],
        "window": r["window"],
    }
    assert _compare(server, {**args, "model_result": subset}) == full


# --- the ERK regression ---------------------------------------------------------------------- #


def test_erk_magnitude_is_outside_the_model_and_the_values_are_kept(server, cases):
    out = _compare(server, cases["E1_magnitude"])
    assert out["comparability"] == "outside_model_representation"
    obs = out["observation"]
    # PBS-relative, as the authors give them; PBS is not read as an arm.
    assert obs["treatment_values"] == [6.00862069] and obs["reference_values"] == [1.109195402]
    assert obs["treatment_summary"]["recorded"] == 1 and obs["reference_summary"]["recorded"] == 1
    assert out["model_claim"]["model_values"] == ["no_change"]
    assert out["model_claim"]["cases_explored"] == 32
    assert out["result"] is None


def test_erk_category_is_not_turned_into_agreement_or_disagreement(server, cases):
    out = _compare(server, cases["E2_category"])
    assert out["comparability"] == "correspondence_unresolved"
    assert "model_value_without_correspondence" in out["reasons"]
    assert "observation_not_classified" in out["reasons"]
    assert out["result"] is None and out["if_accepted"] is None


def test_erk_inputs_are_the_stored_records_unchanged():
    docs = CASE.parent
    for folder in ("logic_biology_v1", "logic_window_v0", "erk_pmek_measurement_v0"):
        for line in (docs / folder / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split()
            assert hashlib.sha256((docs / folder / name).read_bytes()).hexdigest() == digest


def test_the_recorded_results_rebuild(mod, server, cases):
    recorded = json.loads((CASE / "results.json").read_text())
    for name, args in cases.items():
        assert mod.summary(_compare(server, args)) == recorded[name], name
