"""Review r2 of the model-observation link (model_observation_link_v0/review_r2/).

Groups of cases that carry no model value, and a declared category whose name happens to be
the rule's "indeterminate". Every call is on `build_server()`; the inputs are built in
`review_r2/cases.py` from the original and review r1 builders. Expected values follow from what
each input means, not from what the function returned.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from virtualcell.mcp.payloads import ToolRefusal
from virtualcell.mcp.server import build_server
from virtualcell.research.model_observation import ModelClaim, ModelValueGroup, _relate

sdk_errors = pytest.importorskip("mcp.server.mcpserver.exceptions")
FOLDER = (
    Path(__file__).resolve().parents[2] / "docs" / "research_sessions" / "model_observation_link_v0"
)
CASE = FOLDER / "review_r2"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("model_observation_review_r2", CASE / "cases.py")
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
    return mod.all_cases(server)


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


# --- groups without values ------------------------------------------------------------------- #


def test_the_unedited_t3_is_still_partial(mod, server):
    out = _compare(server, mod.base.synthetic_cases(server)["T3_partial"])
    assert out["model_claim"]["model_values"] == ["increase", "no_change"]
    assert (out["relation"], out["result"]) == ("partial", "undecided")


def test_a_group_without_directions_is_refused_not_dropped(server, cases):
    # Case 1 is still a case of the model; reading the rest alone would claim a single match.
    detail = _refused(server, cases["B1_one_group_without_directions"]).detail
    assert "paired.groups[1].directions is empty" in detail and "[1]" in detail


def test_no_group_with_directions_is_refused_not_a_mismatch(server, cases):
    # No prediction at all is not a prediction the observation contradicts.
    detail = _refused(server, cases["B2_no_group_with_directions"]).detail
    assert "paired.groups[0].directions is empty" in detail


def test_an_engine_undetermined_result_is_accepted_and_insufficient(server, cases):
    args = cases["U1_engine_undetermined"]
    assert args["model_result"]["window"]["targets"][0]["paired"]["directions"] == ["undetermined"]
    out = _compare(server, args)
    assert out["comparability"] == "insufficient"
    assert "model_values_not_computed" in out["reasons"]
    assert out["relation"] is None and out["result"] is None and out["explored_result"] is None
    assert out["model_claim"]["not_computed"] is True
    # The observation is kept.
    assert out["observation"]["observed"] == "increase"


def test_relating_without_a_prediction_never_says_inconsistent():
    claim = ModelClaim(
        form="change",
        meaning="m",
        target="X",
        window={"first": 2, "last": 4},
        groups=[ModelValueGroup(model_values=[], observed_values=None, cases=[0])],
        model_values=[],
        case_labels=["all"],
        cases_explored=1,
        cases_total=1,
        applies_to="all_cases",
        not_computed=False,
    )
    with pytest.raises(ValueError, match="no model prediction"):
        _relate(claim, "increase", False)
    with pytest.raises(ValueError, match="no model prediction"):
        _relate(claim.model_copy(update={"groups": []}), "increase", False)


# --- category names and the rule's classes --------------------------------------------------- #


@pytest.mark.parametrize(
    ("name", "relation", "result"),
    [
        # indeterminate vs indeterminate: the same declared category.
        ("I1_C1_A_vs_A_renamed", "single_match", "consistent"),
        # model inactive -> B, observed indeterminate: another declared category.
        ("I2_C2_A_vs_B_renamed", "outside", "inconsistent"),
        # model {active, inactive} -> {indeterminate, B}, observed indeterminate.
        ("I3_C3_AB_vs_A_renamed", "partial", "undecided"),
    ],
)
def test_a_category_named_indeterminate_keeps_its_meaning(server, cases, name, relation, result):
    out = _compare(server, cases[name])
    assert out["comparability"] == "comparable"
    assert out["observation_meaning"] == "declared_category"
    assert out["observation"]["observed"] == "indeterminate"
    assert (out["relation"], out["result"]) == (relation, result)


def test_renaming_a_category_changes_no_outcome(mod, server, cases):
    categorical = mod.r1.categorical_cases(server)
    for new, old in (
        ("I1_C1_A_vs_A_renamed", "C1_A_vs_A"),
        ("I2_C2_A_vs_B_renamed", "C2_A_vs_B"),
        ("I3_C3_AB_vs_A_renamed", "C3_AB_vs_A"),
    ):
        a, b = _compare(server, categorical[old]), _compare(server, cases[new])
        for key in ("comparability", "relation", "result", "explored_result", "reasons", "needs"):
            assert a[key] == b[key], (new, key)


def test_a_ratio_between_the_rule_bands_is_still_between_bands(server, cases):
    # 1.3 lies between no_change (0.9-1.1) and increase (>= 1.5).
    out = _compare(server, cases["N1_between_bands"])
    assert out["observation_meaning"] == "quantitative_change"
    assert out["observation"]["observed"] == "indeterminate"
    assert (out["relation"], out["result"]) == ("between_bands", "undecided")


def test_if_accepted_reads_the_classes_as_the_comparison_does(server, cases):
    held = _compare(server, cases["N2_between_bands_held"])
    stated = _compare(server, cases["N3_between_bands_stated"])
    assert held["comparability"] == "correspondence_unresolved" and held["result"] is None
    assert stated["comparability"] == "comparable"
    assert held["if_accepted"] == stated["result"] == "undecided"


# --- records --------------------------------------------------------------------------------- #


def test_the_review_results_rebuild(mod, server, cases):
    recorded = json.loads((CASE / "results.json").read_text())
    assert set(recorded) == set(cases)
    for name, args in cases.items():
        assert mod.summary(mod.attempt(server, args)) == recorded[name], name


def test_earlier_records_are_unchanged():
    for folder in (FOLDER, FOLDER / "review_r1", CASE):
        for line in (folder / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split()
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name
