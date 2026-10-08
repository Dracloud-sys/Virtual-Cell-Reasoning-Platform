"""Review r1 of the model-observation link (model_observation_link_v0/review_r1/).

Internal consistency of the model result, a readout reference that conflicts with the mapping's,
and recorded categorical values. Every call is on `build_server()`; the inputs are built in
`review_r1/cases.py` from the original builders. A/B are synthetic categories.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from virtualcell.mcp.payloads import ToolRefusal
from virtualcell.mcp.server import build_server

sdk_errors = pytest.importorskip("mcp.server.mcpserver.exceptions")
CASE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research_sessions"
    / "model_observation_link_v0"
    / "review_r1"
)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("model_observation_review_r1", CASE / "cases.py")
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
def original(mod, server):
    return mod.base.synthetic_cases(server) | mod.base.erk_cases()


@pytest.fixture(scope="module")
def categorical(mod, server):
    return mod.categorical_cases(server)


def _compare(server, args):
    result = asyncio.run(server.call_tool("compare_model_observation", args))
    assert not result.is_error, result.content
    return result.structured_content


def _refused(server, args) -> ToolRefusal:
    with pytest.raises(sdk_errors.ToolError) as caught:
        asyncio.run(server.call_tool("compare_model_observation", args))
    refusal = ToolRefusal.parse(str(caught.value))
    assert refusal.error == "malformed_model_observation_link"
    return refusal


# --- R1: a result that contradicts itself is refused, naming the field ----------------------- #


@pytest.mark.parametrize(
    ("name", "field"),
    [
        ("R1a_paired_group_dropped", "paired.groups"),
        ("R1b_paired_groups_empty", "paired.groups"),
        ("R1c_case_index_out_of_range", "paired.groups"),
        ("R1d_partial_run_claims_all_cases", "paired.applies_to"),
        ("R1e_duplicate_case_label", "window.cases"),
        ("R1f_cases_explored_differs", "cases_explored"),
        ("R1g_complete_flag_contradicts_counts", "exploration_complete"),
        ("R1h_case_in_two_groups", "paired.groups"),
        ("R1i_directions_differ_from_groups", "paired.directions"),
        ("R1j_scenario_case_missing", "scenario.groups"),
        ("R1k_paired_without_pairing", "pairing.status"),
        ("R1l_no_baseline_status_with_baseline", "pairing.status"),
        ("R1m_baseline_side_without_baseline", "baseline side"),
    ],
)
def test_r1_contradictory_model_results_are_refused(mod, server, original, name, field):
    args = mod.contradictions(original)[name]
    assert field in _refused(server, args).detail


def test_r1_every_engine_result_already_used_is_still_accepted(server, original):
    # paired, no_baseline, incomplete exploration, not computed, and the stored ERK record.
    for name, args in original.items():
        assert _compare(server, args)["comparison_id"], name


def test_r1_a_not_paired_engine_result_is_accepted(mod, server):
    # The scenario's input is unknown and the baseline's is not: the engine does not pair them,
    # and the baseline's groups index its own single case.
    b = mod.base
    result = b.call(
        server,
        "run_logic_model",
        {
            "model": b.MODELS["follow"],
            "scenario": b._sc("T", {"X": False}, {"U": b._on("unknown"), "V": b._on(True)}),
            "baseline": b._sc("B", {"X": False}, {"U": b._on(False), "V": b._on(True)}),
            "steps": 4,
            "view": "window",
            "window": {"first": 2, "last": 4, "targets": ["X"]},
        },
    )
    assert result["window"]["pairing"]["status"] == "not_paired"
    assert result["window"]["baseline_cases"] == ["all"]
    table = [
        {"model_value": "active", "observed_value": "present"},
        {"model_value": "inactive", "observed_value": "absent"},
    ]
    args = {
        "model_result": result,
        "runs": [b.run_record([({"arm": "T"}, [2.0])])],
        "link": b.link(
            result,
            claim="state",
            table=table,
            observation=b.mapping(reference=None, versus=None, rule=None),
        ),
    }
    out = _compare(server, args)
    assert out["model_claim"]["model_values"] == ["active", "inactive"]


def test_r1_an_empty_prediction_set_is_not_a_contradiction(server, original):
    # Model values not computed in the window: a valid result, reported as insufficient.
    out = _compare(server, original["T7d_not_computed"])
    assert out["comparability"] == "insufficient"


# --- R2: a readout reference that conflicts with the mapping's ------------------------------- #


def test_r2_a_conflicting_reference_is_unresolved_and_names_both(mod, server, original):
    args = mod.reference_conflict(original)["R2_spec_reference_differs"]
    out = _compare(server, args)
    assert out["comparability"] == "correspondence_unresolved"
    (reason,) = [r for r in out["reasons"] if r.startswith("readout_spec_reference")]
    assert "readout_spec.reference='untreated'" in reason and "mapping.versus='B'" in reason
    assert out["result"] is None and out["explored_result"] is None and out["relation"] is None
    assert out["if_accepted"] is None
    # The observation and its finding are kept.
    assert out["observation"]["observed"] == "increase"
    assert out["observation"]["treatment_values"] == [2.0, 2.2]
    codes = [f["code"] for f in out["observation_findings"]]
    assert "mapping_reference_differs_from_readout_spec" in codes
    assert "state_or_review_correspondence" in out["needs"]


def test_r2_acceptance_does_not_override_the_conflict(mod, server, original):
    out = _compare(server, mod.reference_conflict(original)["R2b_differs_even_when_accepted"])
    assert out["correspondence_accepted"] is True
    assert out["comparability"] == "correspondence_unresolved" and out["result"] is None


def test_r2_the_same_reference_compares(mod, server, original):
    out = _compare(server, mod.reference_conflict(original)["R2c_spec_reference_agrees"])
    assert (out["comparability"], out["result"]) == ("comparable", "consistent")


# --- R3: recorded categorical values, through an explicit vocabulary and table --------------- #


def test_r3_same_category_is_a_conditional_match(server, categorical):
    out = _compare(server, categorical["C1_A_vs_A"])
    assert (out["comparability"], out["relation"], out["result"]) == (
        "comparable",
        "single_match",
        "consistent",
    )
    assert out["observation_meaning"] == "declared_category"
    assert out["observed_categories"] == ["A", "A"]
    assert out["observation"]["treatment_values"] == []
    assert out["scientific_validity_checked"] is False


def test_r3_other_category_is_a_conditional_mismatch(server, categorical):
    out = _compare(server, categorical["C2_A_vs_B"])
    assert out["model_claim"]["groups"][0]["observed_values"] == ["B"]
    assert (out["relation"], out["result"]) == ("outside", "inconsistent")


def test_r3_two_model_categories_are_not_a_single_prediction(server, categorical):
    out = _compare(server, categorical["C3_AB_vs_A"])
    assert out["model_claim"]["model_values"] == ["active", "inactive"]
    assert len(out["model_claim"]["groups"]) == 2
    assert (out["relation"], out["result"]) == ("partial", "undecided")


@pytest.mark.parametrize(
    ("name", "reason", "left_out"),
    [
        ("C4_category_outside_vocabulary", "category_outside_declared_vocabulary", {}),
        ("C6_replicates_disagree", "replicates_disagree", {}),
        ("C7_numbers_are_not_categories", "no_usable_readings", {"not_categorical": 2}),
    ],
)
def test_r3_unreadable_categories_are_insufficient_not_guessed(
    server, categorical, name, reason, left_out
):
    out = _compare(server, categorical[name])
    assert out["comparability"] == "insufficient"
    assert out["observation"]["status"] == "insufficient"
    assert reason in out["observation"]["reasons"]
    assert out["observation"]["left_out"] == left_out
    assert out["result"] is None and out["observation"]["observed"] is None


def test_r3_left_out_readings_are_not_used(server, categorical):
    out = _compare(server, categorical["C5_left_out_readings"])
    assert out["observation"]["left_out"] == {"below_detection": 1, "excluded": 1, "missing": 1}
    # The excluded reading said B; it is counted, not read.
    assert out["observed_categories"] == ["A"]
    assert out["result"] == "consistent"


@pytest.mark.parametrize(
    ("name", "field"),
    [
        ("C8_no_vocabulary_declared", "observed_vocabulary"),
        ("C9_table_value_outside_vocabulary", "observed_value 'C'"),
        ("C10_vocabulary_on_a_change_claim", "observed_vocabulary"),
    ],
)
def test_r3_an_undeclared_or_misused_vocabulary_is_refused(server, categorical, name, field):
    assert field in _refused(server, categorical[name]).detail


# --- order: positions move with their labels ------------------------------------------------- #


@pytest.mark.parametrize("name", ["T3_partial", "C3_AB_vs_A"])
def test_reordering_cases_keeps_each_label_with_its_values(
    mod, server, original, categorical, name
):
    args = (original | categorical)[name]
    a = _compare(server, args)
    b = _compare(server, mod.permuted(args, [1, 0]))
    for key in ("comparability", "relation", "result", "reasons", "needs"):
        assert a[key] == b[key], key
    assert b["model_claim"]["case_labels"] == list(reversed(a["model_claim"]["case_labels"]))
    assert mod.by_label(a) == mod.by_label(b)


def test_inputs_are_untouched(server, categorical):
    args = copy.deepcopy(categorical["C3_AB_vs_A"])
    before = copy.deepcopy(args)
    _compare(server, args)
    assert args == before


# --- records --------------------------------------------------------------------------------- #


def test_the_review_results_rebuild(mod, server):
    recorded = json.loads((CASE / "results.json").read_text())
    for name, args in mod.all_cases(server).items():
        got = mod.summary(mod.attempt(server, args))
        assert _unversioned(got) == _unversioned(recorded[name]), name


def _unversioned(value):
    # A refusal relayed from pydantic ends with its docs URL, which names the installed
    # version (errors.pydantic.dev/2.13/...). Only that version is ignored; the rest is compared.
    text = re.sub(r"errors\.pydantic\.dev/[0-9.]+/", "errors.pydantic.dev/", json.dumps(value))
    return json.loads(text)


def test_the_original_records_are_unchanged():
    for folder in (CASE.parent, CASE):
        for line in (folder / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split()
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name
