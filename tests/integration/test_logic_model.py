"""The logic engine against its specification (docs/research_sessions/logic_model_v0/SPEC.md).

The reference values are the hand-traced tables in `expected_by_hand.json`, written before the
engine; nothing here is copied from engine output. Every call goes through the MCP tool
`run_logic_model` (`build_server()`), the same path a host uses, which calls
`virtualcell.simulation.logic.run_logic` and nothing else.

Passing these says the engine computes what the specification says. It says nothing about how
well any model predicts a cell.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest

mcp_server = pytest.importorskip(
    "virtualcell.mcp.server", reason="the MCP adapter needs the optional 'mcp' extra"
)
sdk_errors = pytest.importorskip("mcp.server.mcpserver.exceptions")

from virtualcell.mcp.payloads import ToolRefusal  # noqa: E402
from virtualcell.research.contracts import Prediction  # noqa: E402
from virtualcell.simulation import logic  # noqa: E402

CASE = Path(__file__).resolve().parents[2] / "docs" / "research_sessions" / "logic_model_v0"
SPEC = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
HAND = json.loads((CASE / "expected_by_hand.json").read_text(encoding="utf-8"))
MODELS = {m["id"]: m for m in SPEC["models"]}
STEPS = SPEC["steps"]


@pytest.fixture(scope="module")
def server():
    return mcp_server.build_server()


def _scenario(name: str) -> dict[str, Any]:
    return {"name": name, **copy.deepcopy(SPEC["scenarios"][name])}


def _run(server, model, scenario, steps=STEPS, **kwargs) -> dict[str, Any]:
    args = {"model": model, "scenario": scenario, "steps": steps, **kwargs}
    result = asyncio.run(server.call_tool("run_logic_model", args))
    assert not result.is_error, result.content
    return result.structured_content


def _refused(server, model, scenario, steps=STEPS, **kwargs) -> ToolRefusal:
    args = {"model": model, "scenario": scenario, "steps": steps, **kwargs}
    with pytest.raises(sdk_errors.ToolError) as caught:
        asyncio.run(server.call_tool("run_logic_model", args))
    return ToolRefusal.parse(str(caught.value))


def _rows(case: dict[str, Any], order: str = "USP") -> list[str]:
    return [
        "".join("?" if st[c] is None else str(int(st[c])) for c in order) for st in case["path"]
    ]


def _hand_key(label: str) -> str:
    if label == "all":
        return label
    name, value = label.split("=")
    return f"{name.split('[')[0]}={value}"


def _summary(out, component):
    return [s for s in out["summary"] if s["component"] == component]


# --- the reference case, against the hand tables --------------------------------------- #


@pytest.mark.parametrize("model_id", sorted(MODELS))
@pytest.mark.parametrize("scenario", sorted(SPEC["scenarios"]))
def test_paths_match_the_hand_trace(server, model_id, scenario):
    out = _run(server, MODELS[model_id], _scenario(scenario), view="full")
    got = {_hand_key(c["case"]): _rows(c) for c in out["cases"]}
    assert got == HAND["paths"][model_id][scenario]
    assert out["exploration_complete"] is True


@pytest.mark.parametrize("model_id", sorted(MODELS))
def test_repetition_matches_the_hand_trace(server, model_id):
    for scenario, expected in HAND["repetition"][model_id].items():
        [rep] = _run(server, MODELS[model_id], _scenario(scenario))["repetition"]
        assert (rep["constant_from"], rep["status"], rep["from_step"]) == (
            expected["constant_from"],
            "fixed_point",
            expected["fixed_point_from"],
        ), scenario


@pytest.mark.parametrize("model_id", sorted(MODELS))
def test_readout_against_baseline_matches_the_hand_trace(server, model_id):
    for scenario, base in SPEC["comparisons"]:
        out = _run(
            server,
            MODELS[model_id],
            _scenario(scenario),
            baseline=_scenario(base),
            readouts=SPEC["readouts"],
        )
        last = next(r for r in out["readouts"] if r["t"] == STEPS)
        assert (
            last["versus_baseline"] == HAND["readout_R_P_at_step_6_vs_baseline"][model_id][scenario]
        )
        if scenario.startswith("s5c"):
            paired = {_hand_key(k): v for k, v in last["paired"].items()}
            assert paired == HAND["paired_R_P_at_step_6"][model_id]


@pytest.mark.parametrize("model_id", sorted(MODELS))
def test_p_summary_matches_the_hand_trace(server, model_id):
    for scenario, expected in HAND["summary_P_by_step"][model_id].items():
        got = [
            int(s["value"]) if s["status"] == "same_in_all_explored" else "differs"
            for s in _summary(_run(server, MODELS[model_id], _scenario(scenario)), "P")
        ]
        assert got == expected, scenario


def test_model_b_keeps_p_because_of_its_own_rule_and_initial_p(server):
    out = _run(server, MODELS["B_self_maintaining"], _scenario("s2_input_off"))
    dep = next(d for d in out["dependencies"] if d["component"] == "P")
    assert [r["rule_id"] for r in dep["rules"]] == ["R1", "R2"]
    assert "initial:P" in dep["computed_from"]
    assert all(r["validated"] is False for r in dep["rules"])


# --- A. rules ------------------------------------------------------------------------- #


def _model(rules, components=None):
    return {
        "id": "m",
        "components": components
        or [
            {"id": "X", "kind": "input"},
            {"id": "Y", "kind": "internal"},
            {"id": "Z", "kind": "internal"},
        ],
        "rules": rules,
    }


def _sc(initial=None, x=True, clamps=None, name="s"):
    return {
        "name": name,
        "initial": initial if initial is not None else {"Y": False, "Z": False},
        "inputs": {"X": [{"start": 0, "end": None, "value": x}]},
        "clamps": clamps or [],
    }


@pytest.mark.parametrize(
    ("expr", "x", "y0", "expected"),
    [
        ({"and": [{"var": "X"}, {"var": "Y"}]}, True, False, False),
        ({"and": [{"var": "X"}, {"var": "Y"}]}, True, True, True),
        ({"or": [{"var": "X"}, {"var": "Y"}]}, False, True, True),
        ({"or": [{"var": "X"}, {"var": "Y"}]}, False, False, False),
        ({"not": {"var": "X"}}, True, False, False),
        ({"not": {"var": "X"}}, False, False, True),
        ({"const": True}, False, False, True),
        ({"and": [{"const": True}, {"not": {"const": False}}]}, False, False, True),
    ],
)
def test_operators(server, expr, x, y0, expected):
    model = _model(
        [
            {"id": "RY", "target": "Y", "expr": {"var": "Y"}},
            {"id": "RZ", "target": "Z", "expr": expr},
        ]
    )
    out = _run(server, model, _sc({"Y": y0, "Z": False}, x=x), steps=1, view="full")
    assert out["cases"][0]["path"][1]["Z"] is expected


@pytest.mark.parametrize(
    ("rules", "fragment"),
    [
        ([{"id": "R", "target": "Y", "expr": {"var": "Q"}}], "undeclared"),
        ([{"id": "R", "target": "Y", "expr": {"xor": [{"var": "X"}]}}], "xor"),
        ([{"id": "R", "target": "Y", "expr": {"var": "X", "const": True}}], "exactly one"),
        ([{"id": "R", "target": "Y", "expr": {"and": []}}], "at least one"),
        ([{"id": "R", "target": "X", "expr": {"const": True}}], "input"),
        (
            [
                {"id": "R1", "target": "Y", "expr": {"const": True}},
                {"id": "R2", "target": "Y", "expr": {"const": False}},
            ],
            "two rules",
        ),
        ([{"id": "R", "target": "Y", "expr": "X and Y"}], "expr"),
    ],
)
def test_malformed_rules_are_refused(server, rules, fragment):
    refusal = _refused(server, _model(rules), _sc())
    assert refusal.error == "malformed_logic_model"
    assert fragment in refusal.detail


def test_a_missing_rule_is_not_computed_never_inactive_or_held(server):
    model = _model([{"id": "RY", "target": "Y", "expr": {"var": "X"}}])
    out = _run(server, model, _sc({"Y": False, "Z": True}), steps=3)
    z = _summary(out, "Z")
    assert z[0]["status"] == "same_in_all_explored" and z[0]["value"] is True
    assert {s["status"] for s in z[1:]} == {"not_computed"}
    assert out["not_computed"] == ["Z: no rule"]


def test_not_computed_propagates_only_where_it_decides_something(server):
    model = _model(
        [
            {"id": "RY", "target": "Y", "expr": {"and": [{"var": "Z"}, {"const": False}]}},
        ]
    )
    out = _run(server, model, _sc({"Y": True, "Z": True}), steps=3)
    # From t=2, Y reads a not-computed Z, but 'and' with false is false whatever Z is.
    assert all(s["value"] is False for s in _summary(out, "Y")[1:])


def test_the_model_and_scenario_are_not_modified(server):
    model, scenario = (
        copy.deepcopy(MODELS["A_input_dependent"]),
        _scenario("s4_input_off_then_released"),
    )
    before = json.dumps([model, scenario], sort_keys=True)
    _run(server, model, scenario)
    assert json.dumps([model, scenario], sort_keys=True) == before


# --- B. update and clamps -------------------------------------------------------------- #


def test_every_rule_reads_the_previous_state():
    # A swap: synchronous update exchanges the values; sequential update would copy one.
    m = logic.LogicModel.model_validate(
        _model(
            [
                {"id": "RY", "target": "Y", "expr": {"var": "Z"}},
                {"id": "RZ", "target": "Z", "expr": {"var": "Y"}},
            ]
        )
    )
    out = logic.run_logic(
        m, logic.Scenario.model_validate(_sc({"Y": True, "Z": False})), 2, view="full"
    )
    path = out.cases[0].path
    assert [(p["Y"], p["Z"]) for p in path] == [(True, False), (False, True), (True, False)]


def test_listing_order_changes_nothing(server):
    a = MODELS["B_self_maintaining"]
    b = copy.deepcopy(a)
    b["components"].reverse()
    b["rules"].reverse()
    sa = _scenario("s4_input_off_then_released")
    sb = copy.deepcopy(sa)
    sb["clamps"] = list(reversed(sb["clamps"]))
    ra, rb = _run(server, a, sa, view="full"), _run(server, b, sb, view="full")
    assert ra["model_sha256"] == rb["model_sha256"] and ra["run_sha256"] == rb["run_sha256"]
    for key in ("summary", "cases", "dependencies", "repetition"):
        assert ra[key] == rb[key], key


def test_other_update_modes_are_refused_not_converted(server):
    model = {**MODELS["A_input_dependent"], "update": "asynchronous"}
    refusal = _refused(server, model, _scenario("s1_input_on"))
    assert "not supported" in refusal.detail


def test_clamp_start_inclusive_end_and_release(server):
    # Y follows X; X clamped false at indices 2..3 only.
    model = _model(
        [
            {"id": "RY", "target": "Y", "expr": {"var": "X"}},
            {"id": "RZ", "target": "Z", "expr": {"var": "Z"}},
        ]
    )
    scenario = _sc(
        {"Y": True, "Z": False}, clamps=[{"target": "X", "value": False, "start": 2, "end": 3}]
    )
    out = _run(server, model, scenario, steps=6, view="full")
    path = out["cases"][0]["path"]
    assert [p["X"] for p in path] == [True, True, False, False, True, True, True]
    # Y at t reads X at t-1: first affected at start+1, back one step after end+1.
    assert [p["Y"] for p in path] == [True, True, True, False, False, True, True]


def test_a_clamp_on_an_internal_component_wins_over_its_rule(server):
    out = _run(server, MODELS["A_input_dependent"], _scenario("s3_S_off"), view="full")
    sources = {(e["t"], e["component"]): e["source"] for e in out["trace"] if e["component"] == "S"}
    assert sources[(0, "S")] == "initial:S"
    assert all(sources[(t, "S")] == "clamp:S[1:end]" for t in range(1, STEPS + 1))


def test_conflicting_clamps_are_refused_in_either_order(server):
    clamps = [
        {"target": "S", "value": False, "start": 1, "end": 3},
        {"target": "S", "value": True, "start": 3, "end": 4},
    ]
    for order in (clamps, list(reversed(clamps))):
        scenario = {**_scenario("s1_input_on"), "clamps": order}
        refusal = _refused(server, MODELS["A_input_dependent"], scenario)
        assert "conflicting clamps" in refusal.detail


def test_steps_are_not_time(server):
    out = _run(server, MODELS["A_input_dependent"], _scenario("s2_input_off"))
    text = json.dumps({k: v for k, v in out.items() if k not in ("limits", "step_meaning")})
    for unit in ("hour", "minute", "second", "day", "half-life"):
        assert unit not in text
    assert "Not a unit of time" in out["step_meaning"]


# --- C. unknowns and limits ------------------------------------------------------------- #


def test_unknown_is_expanded_never_read_as_inactive(server):
    out = _run(server, MODELS["B_self_maintaining"], _scenario("s5c_S_off_from_0_P_unknown"))
    assert out["unknowns"] == ["P"] and out["cases_total"] == 2
    p6 = next(s for s in out["final"] if s["component"] == "P")
    assert p6["status"] == "differs_by_case"
    assert p6["cases_by_value"] == {"false": 1, "true": 1}


def test_an_unknown_held_over_a_segment_is_one_choice_per_case(server):
    out = _run(server, MODELS["A_input_dependent"], _scenario("s5b_U_unknown"), view="full")
    assert out["cases_total"] == 2
    for case in out["cases"]:
        assert len({p["U"] for p in case["path"]}) == 1


def test_an_unknown_each_step_is_a_separate_choice_per_index(server):
    scenario = _scenario("s1_input_on")
    scenario["inputs"]["U"] = [
        {"start": 0, "end": 2, "value": "unknown_each_step"},
        {"start": 3, "end": None, "value": True},
    ]
    out = _run(server, MODELS["A_input_dependent"], scenario)
    assert out["unknowns"] == ["U@0", "U@1", "U@2"] and out["cases_total"] == 8
    assert {r["status"] for r in out["repetition"]} == {"fixed_point"}
    every_step = _scenario("s1_input_on")
    every_step["inputs"]["U"] = [{"start": 0, "end": None, "value": "unknown_each_step"}]
    out = _run(server, MODELS["A_input_dependent"], every_step, steps=3)
    assert {r["status"] for r in out["repetition"]} == {"not_assessed"}


def test_the_case_limit_is_reported_and_no_all_case_claim_is_made(server):
    scenario = _scenario("s1_input_on")
    scenario["inputs"]["U"] = [{"start": 0, "end": None, "value": "unknown_each_step"}]
    out = _run(server, MODELS["A_input_dependent"], scenario, steps=6, max_cases=4)
    assert out["cases_total"] == 128 and out["cases_explored"] == 4
    assert out["exploration_complete"] is False and out["limits_reached"]
    assert {s["status"] for s in out["summary"]} == {"exploration_incomplete"}


def test_limits_are_enforced(server):
    refusal = _refused(server, MODELS["A_input_dependent"], _scenario("s1_input_on"), steps=0)
    assert "between 1 and" in refusal.detail
    big = _model([], components=[{"id": f"C{i}", "kind": "input"} for i in range(40)])
    refusal = _refused(server, big, {"name": "s", "initial": {}})
    assert "at most" in refusal.detail


def test_a_missing_initial_value_is_refused_not_assumed(server):
    scenario = _scenario("s1_input_on")
    del scenario["initial"]["P"]
    assert "no initial value" in _refused(server, MODELS["A_input_dependent"], scenario).detail


def test_a_missing_input_is_not_computed(server):
    scenario = _scenario("s1_input_on")
    scenario["inputs"]["U"] = [{"start": 0, "end": 2, "value": True}]
    out = _run(server, MODELS["A_input_dependent"], scenario)
    assert any("no input value" in n for n in out["not_computed"])
    u = _summary(out, "U")
    assert u[3]["status"] == "not_computed"
    p6 = next(s for s in out["final"] if s["component"] == "P")
    assert p6["status"] == "not_computed"


# --- D. connection ---------------------------------------------------------------------- #


def test_prediction_drafts_are_assumptions_never_evidence(server):
    out = _run(
        server,
        MODELS["A_input_dependent"],
        _scenario("s2_input_off"),
        baseline=_scenario("s1_input_on"),
        readouts=SPEC["readouts"],
        hypothesis_id="H_A",
    )
    [draft] = out["prediction_drafts"]
    Prediction.model_validate(draft)
    assert draft["basis"] == "assumption" and draft["expected"] == "decrease"
    assert out["model_sha256"][:12] in draft["assumptions"][0]
    assert "not observed" in draft["assumptions"][0]


def test_an_undetermined_readout_drafts_as_not_predicted(server):
    out = _run(
        server,
        MODELS["B_self_maintaining"],
        _scenario("s5c_S_off_from_0_P_unknown"),
        baseline=_scenario("s5c_base_P_unknown"),
        readouts=SPEC["readouts"],
        hypothesis_id="H_B",
    )
    [draft] = out["prediction_drafts"]
    assert draft["expected"] == "not_predicted" and draft["unresolved"]


def test_a_readout_without_a_mapping_is_not_derivable_and_the_run_completes(server):
    out = _run(
        server,
        MODELS["A_input_dependent"],
        _scenario("s2_input_off"),
        readouts=SPEC["readouts"],
        readouts_requested=["R_P", "alpha_SMA_IF"],
    )
    assert out["readouts_not_derivable"] == ["alpha_SMA_IF"]
    assert {r["readout"] for r in out["readouts"]} == {"R_P"}


def test_a_baseline_from_another_initial_state_is_refused(server):
    refusal = _refused(
        server,
        MODELS["A_input_dependent"],
        _scenario("s5c_S_off_from_0_P_unknown"),
        baseline=_scenario("s1_input_on"),
    )
    assert "same initial state" in refusal.detail


def test_the_same_input_gives_the_same_result_and_hash(server):
    a = _run(server, MODELS["B_self_maintaining"], _scenario("s4_input_off_then_released"))
    b = _run(server, MODELS["B_self_maintaining"], _scenario("s4_input_off_then_released"))
    assert a == b


def test_the_summary_view_leaves_paths_out_and_says_so(server):
    out = _run(server, MODELS["A_input_dependent"], _scenario("s1_input_on"))
    assert out["cases"] is None and out["trace"] is None and out["omitted"]


def test_renamed_circuit_gives_the_same_result(server):
    """Neutrality of the shared code, not a biological evaluation."""
    rename = {"U": "in1", "S": "mid", "P": "out"}
    text = json.dumps(MODELS["B_self_maintaining"])
    scen = json.dumps(_scenario("s4_input_off_then_released"))
    for old, new in rename.items():
        text = text.replace(f'"{old}"', f'"{new}"')
        scen = scen.replace(f'"{old}"', f'"{new}"')
    out = _run(server, json.loads(text), json.loads(scen), view="full")
    assert [_rows(c, ("in1", "mid", "out")) for c in out["cases"]] == [
        HAND["paths"]["B_self_maintaining"]["s4_input_off_then_released"]["all"]
    ]


def test_the_published_schema_states_operators_and_limits(server):
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    schema = json.dumps(tools["run_logic_model"].input_schema)
    for word in ('"const"', '"var"', '"not"', '"and"', '"or"', "synchronous", "inclusive"):
        assert word in schema, word
    assert "$ref" not in schema
