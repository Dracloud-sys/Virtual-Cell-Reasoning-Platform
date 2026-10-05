"""`run_logic_model` window summary (docs/research_sessions/logic_window_v0/).

Expected values come from `hand_cases.json`, traced by hand from the rules before the code was
written, and from an independent recomputation over the full view's case paths. None is copied
from the window output.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from virtualcell.mcp.payloads import ToolRefusal
from virtualcell.mcp.server import build_server

sdk_errors = pytest.importorskip("mcp.server.mcpserver.exceptions")

CASE = Path(__file__).resolve().parents[2] / "docs" / "research_sessions" / "logic_window_v0"
HAND = json.loads((CASE / "hand_cases.json").read_text(encoding="utf-8"))
ERK = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research_sessions"
    / "logic_biology_v1"
    / "prereg"
    / "case.json"
)


@pytest.fixture(scope="module")
def server():
    return build_server()


def _call(server, args: dict) -> dict:
    result = asyncio.run(server.call_tool("run_logic_model", args))
    if result.is_error:
        raise RuntimeError(" ".join(getattr(c, "text", "") for c in result.content))
    return result.structured_content


def _args(case: dict, **override) -> dict:
    args = {
        "model": HAND["models"][case["model"]],
        "scenario": case.get("scenario") or {"name": "s", "initial": {"X": False}},
        "steps": case["steps"],
        "view": case.get("view", "window"),
        "window": case["window"],
    }
    for key in ("baseline", "readouts", "max_cases"):
        if key in case:
            args[key] = case[key]
    args.update(override)
    return args


def _labels(window: dict, side: str) -> list[str]:
    if side == "baseline" and window["baseline_cases"] is not None:
        return window["baseline_cases"]
    return window["cases"]


def _groups(window: dict, target: dict, side: str) -> list | None:
    if target[side] is None:
        return None
    labels = _labels(window, side)
    return [
        [
            g["window_class"],
            g["known_values"],
            g["not_computed_steps"],
            [labels[i] for i in g["cases"]],
        ]
        for g in target[side]["groups"]
    ]


def _paired(window: dict, p: dict | None) -> dict | None:
    if p is None:
        return None
    return {
        "groups": [
            [g["directions"], [window["cases"][i] for i in g["cases"]]] for g in p["groups"]
        ],
        "directions": p["directions"],
        "applies_to": p["applies_to"],
    }


# --- the hand cases ----------------------------------------------------------------------- #


@pytest.mark.parametrize("case", HAND["cases"], ids=[c["id"] for c in HAND["cases"]])
def test_window_matches_the_hand_trace(server, case):
    out = _call(server, _args(case))
    w = out["window"]
    exp = case["expected"]
    if "pairing_status" in exp:
        assert w["pairing"]["status"] == exp["pairing_status"]
    for key in ("constant_from", "baseline_constant_from", "declared_change_after_window"):
        if key in exp:
            assert w[key] == exp[key], key
    for key in ("cases_explored", "cases_total"):
        if key in exp:
            assert out[key] == exp[key]
    if "repetition_status" in exp:
        assert {r["status"] for r in out["repetition"]} == {exp["repetition_status"]}
    got = {t["target"]: t for t in w["targets"]}
    assert sorted(got) == sorted(exp["targets"]) == w["request"]["targets"]
    for name, e in exp["targets"].items():
        t = got[name]
        for key in ("kind", "state"):
            if key in e:
                assert t[key] == e[key]
        assert _groups(w, t, "scenario") == e["scenario_groups"]
        if "baseline_groups" in e:
            assert _groups(w, t, "baseline") == e["baseline_groups"]
        for key in ("across_cases", "identical_paths", "applies_to"):
            if key in e:
                assert t["scenario"][key] == e[key], key
        if "paired" in e:
            assert _paired(w, t["paired"]) == e["paired"]


def test_a_wholly_not_computed_window(server):
    case = next(c for c in HAND["cases"] if c["id"] == "H5b_not_computed_and_paired_undetermined")
    w = _call(server, _args(case, window=case["also"]["window"]))["window"]
    t = w["targets"][0]
    assert _groups(w, t, "scenario") == case["also"]["scenario_groups"]
    assert t["paired"]["directions"] == case["also"]["paired_directions"]


def test_same_class_is_not_same_path(server):
    """0101 against 1010 and 0101 against 0101 share every class; only pairing tells them apart."""
    by_id = {c["id"]: c for c in HAND["cases"]}
    wa = _call(server, _args(by_id["H4a_paired_out_of_phase"]))["window"]
    wb = _call(server, _args(by_id["H4b_paired_in_phase"]))["window"]
    a, b = wa["targets"][0], wb["targets"][0]
    for side in ("scenario", "baseline"):
        assert _groups(wa, a, side) == _groups(wb, b, side)
    assert a["paired"]["directions"] != b["paired"]["directions"]


@pytest.mark.parametrize("case", HAND["refused"], ids=[c["id"] for c in HAND["refused"]])
def test_bad_window_requests_are_refused(server, case):
    args = _args(case)
    if args["window"] is None:
        del args["window"]
    with pytest.raises(sdk_errors.ToolError) as caught:
        asyncio.run(server.call_tool("run_logic_model", args))
    refusal = ToolRefusal.parse(str(caught.value))
    assert refusal.error == "malformed_logic_model"
    assert "nothing was run" in refusal.remedy


# --- the window view's shape and identity -------------------------------------------------- #


def test_window_view_drops_per_step_fields_and_says_how_to_get_them(server):
    case = next(c for c in HAND["cases"] if c["id"] == "H4a_paired_out_of_phase")
    out = _call(server, _args(case))
    for key in ("summary", "differences", "paired_differences", "readouts", "cases", "trace"):
        assert out[key] is None, key
    assert any("view='summary'" in o for o in out["omitted"])
    assert any("view='full'" in o for o in out["omitted"])
    assert out["final"] and out["repetition"]
    assert "dependencies" in out["window"]["final_step_only"]
    assert out["window"]["limits"]


def test_run_identity_is_shared_and_window_identity_is_not(server):
    case = next(c for c in HAND["cases"] if c["id"] == "H4a_paired_out_of_phase")
    full = _call(server, _args(case, view="full", window=None))
    one = _call(server, _args(case))["window"]
    other = _call(server, _args(case, window={"first": 2, "last": 3, "targets": ["X"]}))["window"]
    assert full["run_sha256"] == one["run_sha256"] == other["run_sha256"]
    assert one["request_sha256"] != other["request_sha256"]


def test_calls_without_a_window_are_unchanged(server):
    """The summary view still sends every per-step field and no window."""
    case = next(c for c in HAND["cases"] if c["id"] == "H4a_paired_out_of_phase")
    out = _call(server, _args(case, view="summary", window=None))
    assert out["window"] is None
    assert len(out["summary"]) == 5 and len(out["readouts"]) == 0
    assert out["differences"] and out["paired_differences"]


def test_listing_order_changes_nothing(server):
    case = next(c for c in HAND["cases"] if c["id"] == "H6_exploration_limit")
    model = HAND["models"]["HOLD2"]
    flipped = {**model, "components": model["components"][::-1], "rules": model["rules"][::-1]}
    a = _call(server, _args(case, window={"first": 0, "last": 2, "targets": ["Y", "Q"]}))
    b = _call(
        server,
        _args(case, model=flipped, window={"first": 0, "last": 2, "targets": ["Q", "Y"]}),
    )
    assert a["window"] == b["window"]


# --- the ERK case: the window against an independent reading of the full paths ------------ #


def _reference(full: dict, state: str, first: int, last: int) -> dict:
    """Recompute the window's answers from the full view's case paths, without the window code."""

    def cls(values):
        if all(v is None for v in values):
            return "not_computed"
        if any(v is None for v in values):
            return "partly_not_computed"
        return {(True,): "all_active", (False,): "all_inactive"}.get(
            tuple(sorted(set(values))), "both_values"
        )

    def side(cases):
        out: dict = {}
        for c in cases:
            out.setdefault(cls([c["path"][t][state] for t in range(first, last + 1)]), []).append(
                c["case"]
            )
        return out

    def direction(a, b):
        if a is None or b is None:
            return "undetermined"
        return "no_change" if a == b else ("increase" if a else "decrease")

    base = {c["case"]: c for c in full["baseline_cases"]}
    per_case = {
        c["case"]: sorted(
            {
                direction(c["path"][t][state], base[c["case"]]["path"][t][state])
                for t in range(first, last + 1)
            }
        )
        for c in full["cases"]
    }
    return {
        "scenario": side(full["cases"]),
        "baseline": side(full["baseline_cases"]),
        "per_case": per_case,
    }


@pytest.mark.parametrize("model_index", [0, 1])
@pytest.mark.parametrize("group", ["KRAS", "BRAF"])
def test_erk_window_agrees_with_the_full_paths(server, model_index, group):
    case = json.loads(ERK.read_text(encoding="utf-8"))
    pair = case["comparisons"][group]

    def sc(name):
        return {"name": name, "initial": case["initial"], **case["scenarios"][name]}

    base = {
        "model": case["models"][model_index],
        "scenario": sc(pair["scenario"]),
        "baseline": sc(pair["baseline"]),
        "steps": case["steps"],
        "readouts": case["readouts"],
        "max_cases": case["max_cases"],
    }
    full = _call(server, {**base, "view": "full"})
    names = sorted(r["readout"] for r in case["readouts"])
    w = _call(
        server,
        {
            **base,
            "view": "window",
            "window": {"first": 18, "last": 24, "targets": names},
        },
    )
    assert w["run_sha256"] == full["run_sha256"]
    states = {r["readout"]: r["state"] for r in case["readouts"]}
    window = w["window"]
    assert window["pairing"]["status"] == "paired" and window["baseline_cases"] is None
    labels = window["cases"]
    assert (
        labels == [c["case"] for c in full["cases"]] == [c["case"] for c in full["baseline_cases"]]
    )
    for t in window["targets"]:
        ref = _reference(full, states[t["target"]], 18, 24)
        for side in ("scenario", "baseline"):
            got = {g["window_class"]: [labels[i] for i in g["cases"]] for g in t[side]["groups"]}
            assert got == ref[side]
        got = {labels[i]: g["directions"] for g in t["paired"]["groups"] for i in g["cases"]}
        assert got == ref["per_case"]
        assert t["paired"]["directions"] == sorted({d for v in ref["per_case"].values() for d in v})


def test_window_traces_only_its_targets_and_still_at_the_final_step(server):
    case = json.loads(ERK.read_text(encoding="utf-8"))
    pair = case["comparisons"]["KRAS"]

    def sc(name):
        return {"name": name, "initial": case["initial"], **case["scenarios"][name]}

    base = {
        "model": case["models"][0],
        "scenario": sc(pair["scenario"]),
        "baseline": sc(pair["baseline"]),
        "steps": case["steps"],
        "readouts": case["readouts"],
    }
    summary = _call(server, base)
    w = _call(
        server,
        {
            **base,
            "view": "window",
            "window": {"first": 18, "last": 24, "targets": ["pMEK", "pERK1_2_T202_Y204_WB"]},
        },
    )
    keep = {"pMEK", "pERK"}
    for key in ("dependencies", "baseline_dependencies"):
        assert w[key] == [d for d in summary[key] if d["component"] in keep]
        assert all(d["t"] == case["steps"] for d in w[key])
    assert w["relative_dependencies"] == [
        d for d in summary["relative_dependencies"] if d["readout"] == "pERK1_2_T202_Y204_WB"
    ]
    assert w["final"] == summary["final"] and w["repetition"] == summary["repetition"]


def test_drafts_are_the_same_with_or_without_a_window(server):
    case = next(c for c in HAND["cases"] if c["id"] == "H4a_paired_out_of_phase")
    readouts = [{"readout": "R_X", "state": "X", "basis": "test"}]
    plain = _call(
        server, _args(case, view="summary", window=None, readouts=readouts, hypothesis_id="H")
    )
    windowed = _call(server, _args(case, readouts=readouts, hypothesis_id="H"))
    assert (
        plain["prediction_drafts"] and windowed["prediction_drafts"] == plain["prediction_drafts"]
    )
    assert windowed["run_sha256"] == plain["run_sha256"]


# --- PR #39 review r1: class vs detailed group; unique readout ids ------------------------- #
#
# Reproduced on the product path at a7fd559: across_cases said differs_by_case for two cases of
# one class split only by not-computed steps (R1), and a repeated readout id read the state of
# its last declaration (R2). Expected values are traced by hand from the rules below.

R1_MODEL = {
    "id": "R1",
    "components": [
        {"id": "Q", "kind": "internal"},
        {"id": "Z", "kind": "internal"},
        {"id": "P", "kind": "internal"},
    ],
    "rules": [
        {"id": "rQ", "target": "Q", "expr": {"not": {"var": "Q"}}},
        {"id": "rP", "target": "P", "expr": {"or": [{"var": "Q"}, {"var": "Z"}]}},
    ],
}


def _side(server, model, initial, steps, first, last, target, **extra):
    w = _call(
        server,
        {
            "model": model,
            "scenario": {"name": "s", "initial": initial},
            "steps": steps,
            "view": "window",
            "window": {"first": first, "last": last, "targets": [target]},
            **extra,
        },
    )["window"]
    return w, w["targets"][0]


def test_same_class_with_different_not_computed_steps(server):
    # Q=0: Q 0101, Z 1???, P 1 1 1 ?  (t3 = Q2 OR Z2 = 0 OR ? = ?)
    # Q=1: Q 1010, Z 1???, P 1 1 ? 1  (t2 = Q1 OR Z1 = 0 OR ? = ?)
    w, t = _side(server, R1_MODEL, {"Q": "unknown", "Z": True, "P": True}, 3, 0, 3, "P")
    assert _groups(w, t, "scenario") == [
        ["partly_not_computed", [True], [3], ["Q=0"]],
        ["partly_not_computed", [True], [2], ["Q=1"]],
    ]
    assert t["scenario"]["across_cases"] == "same_class"
    assert t["scenario"]["identical_paths"] is False


def test_same_class_with_different_known_values(server):
    # W has no rule: W=0 gives 0 ?, W=1 gives 1 ?.
    model = {"id": "W", "components": [{"id": "W", "kind": "internal"}], "rules": []}
    w, t = _side(server, model, {"W": "unknown"}, 1, 0, 1, "W")
    assert _groups(w, t, "scenario") == [
        ["partly_not_computed", [False], [1], ["W=0"]],
        ["partly_not_computed", [True], [1], ["W=1"]],
    ]
    assert t["scenario"]["across_cases"] == "same_class"
    assert t["scenario"]["identical_paths"] is False


def test_same_class_with_different_paths(server):
    # X=0: 0101; X=1: 1010. One group, one class, two paths.
    w, t = _side(server, HAND["models"]["FLIP"], {"X": "unknown"}, 3, 0, 3, "X")
    assert _groups(w, t, "scenario") == [["both_values", [False, True], [], ["X=0", "X=1"]]]
    assert t["scenario"]["across_cases"] == "same_class"
    assert t["scenario"]["identical_paths"] is False


def test_different_classes_still_differ(server):
    # Y holds its initial value: Y=0 gives all_inactive, Y=1 all_active.
    w, t = _side(server, HAND["models"]["HOLD"], {"Y": "unknown"}, 2, 0, 2, "Y")
    assert t["scenario"]["across_cases"] == "differs_by_case"
    # Partly not computed in one case, all active in the other: still different classes.
    model = {
        "id": "MIX",
        "components": [
            {"id": "Y", "kind": "internal"},
            {"id": "Z", "kind": "internal"},
            {"id": "P", "kind": "internal"},
        ],
        "rules": [
            {"id": "rY", "target": "Y", "expr": {"var": "Y"}},
            {"id": "rP", "target": "P", "expr": {"or": [{"var": "Y"}, {"var": "Z"}]}},
        ],
    }
    # Y=0: P 1 1 ? (t2 = 0 OR ?); Y=1: P 1 1 1.
    w, t = _side(server, model, {"Y": "unknown", "Z": True, "P": True}, 2, 0, 2, "P")
    assert _groups(w, t, "scenario") == [
        ["partly_not_computed", [True], [2], ["Y=0"]],
        ["all_active", [True], [], ["Y=1"]],
    ]
    assert t["scenario"]["across_cases"] == "differs_by_case"


R2_MODEL = {
    "id": "R2",
    "components": [{"id": "X", "kind": "internal"}, {"id": "Y", "kind": "internal"}],
    "rules": [
        {"id": "rX", "target": "X", "expr": {"const": True}},
        {"id": "rY", "target": "Y", "expr": {"const": False}},
    ],
}
R2_SCENARIO = {"name": "s", "initial": {"X": True, "Y": False}}
R2_READOUTS = [
    {"readout": "R", "state": "X", "basis": "synthetic contract test"},
    {"readout": "R", "state": "Y", "basis": "synthetic contract test"},
]


@pytest.mark.parametrize("view", ["window", "summary", "full"])
@pytest.mark.parametrize("readouts", [R2_READOUTS, R2_READOUTS[::-1], [R2_READOUTS[0]] * 2])
def test_a_repeated_readout_id_is_refused_in_any_order(server, view, readouts):
    args = {
        "model": R2_MODEL,
        "scenario": R2_SCENARIO,
        "steps": 1,
        "readouts": readouts,
        "view": view,
    }
    if view == "window":
        args["window"] = {"first": 0, "last": 1, "targets": ["R"]}
    with pytest.raises(sdk_errors.ToolError) as caught:
        asyncio.run(server.call_tool("run_logic_model", args))
    refusal = ToolRefusal.parse(str(caught.value))
    assert refusal.error == "malformed_logic_model"
    assert "'R'" in refusal.detail and "positions 0 and 1" in refusal.detail


def test_unique_readout_ids_in_any_order_mean_the_same(server):
    readouts = [
        {"readout": "RX", "state": "X", "basis": "synthetic contract test"},
        {"readout": "RY", "state": "Y", "basis": "synthetic contract test"},
    ]

    def run(order):
        return _call(
            server,
            {
                "model": R2_MODEL,
                "scenario": R2_SCENARIO,
                "steps": 1,
                "readouts": order,
                "view": "window",
                "window": {"first": 0, "last": 1, "targets": ["RY", "RX"]},
            },
        )["window"]

    a, b = run(readouts), run(readouts[::-1])
    assert a == b
    got = {
        t["target"]: (t["state"], t["scenario"]["groups"][0]["window_class"]) for t in a["targets"]
    }
    assert got == {"RX": ("X", "all_active"), "RY": ("Y", "all_inactive")}
