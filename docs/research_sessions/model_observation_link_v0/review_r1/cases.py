"""Review r1 of the model-observation link: internal consistency, reference conflict, categories.

Every input is built from the original builders in `../cases.py`, which this file imports and
does not change. Every call is `compare_model_observation` (or `run_logic_model`) on
`build_server()`. A/B are synthetic category names for contract tests; they stand for nothing.

    python cases.py        # writes results.json and run.json here
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from virtualcell.mcp.server import build_server

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def _original():
    spec = importlib.util.spec_from_file_location(
        "model_observation_link_cases", HERE.parent / "cases.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode, before = True, sys.dont_write_bytecode
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


base = _original()


def attempt(server, args: dict) -> dict:
    """The comparison, or the refusal it gave: {"refused": detail}."""
    try:
        return asyncio.run(server.call_tool("compare_model_observation", args)).structured_content
    except Exception as exc:  # the SDK raises ToolError for a refusal
        return {"refused": json.loads(str(exc).split(": ", 1)[1])["detail"]}


# --- R1: a model result that contradicts itself ------------------------------------------- #


def _paired(args: dict) -> dict:
    return args["model_result"]["window"]["targets"][0]["paired"]


def contradictions(cases: dict) -> dict[str, dict]:
    """Variants of a real engine result, each edited so two of its fields disagree."""

    def edit(name, change):
        args = copy.deepcopy(cases[name])
        change(args)
        return args

    w = lambda a: a["model_result"]["window"]  # noqa: E731
    t = lambda a: w(a)["targets"][0]  # noqa: E731
    return {
        # The four named in the review.
        "R1a_paired_group_dropped": edit(
            "T3_partial",
            lambda a: _paired(a).update(
                groups=[g for g in _paired(a)["groups"] if "no_change" not in g["directions"]]
            ),
        ),
        "R1b_paired_groups_empty": edit("T3_partial", lambda a: _paired(a).update(groups=[])),
        "R1c_case_index_out_of_range": edit(
            "T3_partial", lambda a: _paired(a)["groups"][0].update(cases=[99])
        ),
        "R1d_partial_run_claims_all_cases": edit(
            "T7c_partial_exploration", lambda a: _paired(a).update(applies_to="all_cases")
        ),
        # The rest of the minimal checks.
        "R1e_duplicate_case_label": edit("T3_partial", lambda a: w(a).update(cases=["X=0", "X=0"])),
        "R1f_cases_explored_differs": edit(
            "T3_partial", lambda a: a["model_result"].update(cases_explored=3, cases_total=3)
        ),
        "R1g_complete_flag_contradicts_counts": edit(
            "T7c_partial_exploration", lambda a: a["model_result"].update(exploration_complete=True)
        ),
        "R1h_case_in_two_groups": edit(
            "T3_partial", lambda a: _paired(a)["groups"][1].update(cases=[0, 1])
        ),
        "R1i_directions_differ_from_groups": edit(
            "T3_partial", lambda a: _paired(a).update(directions=["increase"])
        ),
        "R1j_scenario_case_missing": edit(
            "T3_partial", lambda a: t(a)["scenario"]["groups"][0].update(cases=[0])
        ),
        "R1k_paired_without_pairing": edit(
            "T3_partial", lambda a: w(a)["pairing"].update(status="not_paired")
        ),
        "R1l_no_baseline_status_with_baseline": edit(
            "T1_consistent", lambda a: w(a)["pairing"].update(status="no_baseline")
        ),
        "R1m_baseline_side_without_baseline": edit(
            "T5_detection", lambda a: t(a).update(baseline=t(a)["scenario"])
        ),
    }


# --- R2: the readout spec's reference against the mapping's -------------------------------- #


def reference_conflict(cases: dict) -> dict[str, dict]:
    def spec(name, readout_spec, **corr):
        args = copy.deepcopy(cases[name])
        args["link"]["readout_spec"] = readout_spec
        args["link"]["correspondence"].update(corr)
        return args

    return {
        "R2_spec_reference_differs": spec(
            "T1_consistent", {"name": "signal", "reference": "untreated"}
        ),
        # Acceptance of the correspondence by the researcher does not settle the conflict.
        "R2b_differs_even_when_accepted": spec(
            "T1_consistent", {"name": "signal", "reference": "untreated"}, accepted_by="researcher"
        ),
        # The same reference, written with other case and spacing, is not a conflict.
        "R2c_spec_reference_agrees": spec("T1_consistent", {"name": "signal", "reference": " b "}),
    }


# --- R3: recorded categorical values ------------------------------------------------------- #

VOCAB = ["A", "B"]
TABLE = [
    {"model_value": "active", "observed_value": "A"},
    {"model_value": "inactive", "observed_value": "B"},
]


def category_record(readings: list, *, run_id: str = "synthetic:cat") -> dict:
    """One ExperimentRun, arm T. A str is a valid category; (quality, value) is not valid."""
    observations = []
    for j, r in enumerate(readings):
        quality, value = ("valid", r) if not isinstance(r, tuple) else r
        m = {"name": "signal", "value": value, "quality": quality}
        if isinstance(value, str):
            m["value_type"] = "categorical"
        else:
            m["unit"] = "ratio"
        observations.append(
            {
                "observation_id": f"c{j}",
                "time_point": {"kind": "elapsed_time", "value": 1.0, "unit": "day"},
                "conditions": {"arm": "T"},
                "measurements": [m],
            }
        )
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "provenance": {
            "origin_kind": "experiment",
            "acquisition_mode": "manual",
            "method": "synthetic",
            "recorded_at": "2026-10-08T00:00:00Z",
        },
        "observations": observations,
    }


def state_results(server) -> dict[str, dict]:
    """Window results for state claims, from run_logic_model on the original models."""

    def run(model, scenario):
        return base.call(
            server,
            "run_logic_model",
            {
                "model": base.MODELS[model],
                "scenario": scenario,
                "steps": 4,
                "view": "window",
                "window": {"first": 2, "last": 4, "targets": ["X"]},
            },
        )

    x0 = {"X": False}
    return {
        # X follows U, U on: X all_active.
        "on": run("follow", base._sc("T", x0, {"U": base._on(True), "V": base._on(True)})),
        # X holds an unknown start: X=0 all_inactive, X=1 all_active, kept as two case groups.
        "either": run("hold", base._sc("T", {"X": "unknown", "Q": False})),
    }


def categorical_cases(server) -> dict[str, dict]:
    r = state_results(server)
    off = base.model_results(server)["off"]

    def case(result, readings, *, vocabulary=VOCAB, table=TABLE):
        corr = {"table": table}
        if vocabulary is not None:
            corr["observed_vocabulary"] = vocabulary
        return {
            "model_result": result,
            "runs": [category_record(readings)],
            "link": base.link(
                result,
                claim="state",
                observation=base.mapping(reference=None, versus=None, rule=None, unit=None),
                correspondence=corr,
            ),
        }

    return {
        "C1_A_vs_A": case(r["on"], ["A", "A"]),
        "C2_A_vs_B": case(off, ["A", "A"]),
        "C3_AB_vs_A": case(r["either"], ["A"]),
        "C4_category_outside_vocabulary": case(r["on"], ["C"]),
        "C5_left_out_readings": case(
            r["on"], ["A", ("excluded", "B"), ("missing", None), ("below_detection", None)]
        ),
        "C6_replicates_disagree": case(r["on"], ["A", "B"]),
        "C7_numbers_are_not_categories": case(r["on"], [2.0, 2.2]),
        "C8_no_vocabulary_declared": case(r["on"], ["A"], vocabulary=None),
        "C9_table_value_outside_vocabulary": case(
            r["on"], ["A"], table=[*TABLE[:1], {"model_value": "inactive", "observed_value": "C"}]
        ),
        "C10_vocabulary_on_a_change_claim": {
            **(t1 := copy.deepcopy(base.synthetic_cases(server)["T1_consistent"])),
            "link": {
                **t1["link"],
                "correspondence": {**t1["link"]["correspondence"], "observed_vocabulary": VOCAB},
            },
        },
    }


# --- order: positions move, labels stay with their cases ------------------------------------ #


def permuted(args: dict, order: list[int]) -> dict:
    """The same result with its cases listed in another order and every index remapped."""
    out = copy.deepcopy(args)
    w = out["model_result"]["window"]
    if w.get("baseline_cases") is not None:
        raise ValueError("only results whose sides index the same case list")
    new_pos = {old: new for new, old in enumerate(order)}
    w["cases"] = [w["cases"][i] for i in order]
    for target in w["targets"]:
        for side in ("scenario", "baseline", "paired"):
            part = target.get(side)
            if part:
                groups = list(reversed(part["groups"]))
                for g in groups:
                    g["cases"] = sorted(new_pos[i] for i in g["cases"])
                part["groups"] = groups
    out["link"]["correspondence"]["table"].reverse()
    for run in out["runs"]:
        run["observations"].reverse()
    return out


def by_label(out: dict) -> list:
    """The model claim's groups, with positions replaced by the labels they stand for."""
    labels = out["model_claim"]["case_labels"]
    return sorted(
        (g["model_values"], g["observed_values"], sorted(labels[i] for i in g["cases"]))
        for g in out["model_claim"]["groups"]
    )


# --- record ---------------------------------------------------------------------------------- #


def summary(out: dict) -> dict:
    if "refused" in out:
        return out
    return base.summary(out) | {"observed_categories": out["observed_categories"]}


def all_cases(server) -> dict[str, dict]:
    cases = base.synthetic_cases(server)
    return contradictions(cases) | reference_conflict(cases) | categorical_cases(server)


def main() -> None:
    server = build_server()
    results = {name: summary(attempt(server, args)) for name, args in all_cases(server).items()}
    cases = base.synthetic_cases(server)
    for name, args, order in (
        ("O1_T3_reordered", cases["T3_partial"], [1, 0]),
        ("O2_C3_reordered", categorical_cases(server)["C3_AB_vs_A"], [1, 0]),
    ):
        a, b = attempt(server, args), attempt(server, permuted(args, order))
        results[name] = {
            "same_outcome": all(a[k] == b[k] for k in ("comparability", "relation", "result")),
            "same_groups_by_label": by_label(a) == by_label(b),
            "case_labels": [a["model_claim"]["case_labels"], b["model_claim"]["case_labels"]],
        }
    (HERE / "results.json").write_text(
        json.dumps(results, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "src"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    ).stdout.strip()
    run = {
        "code": {"git_head": head, "src_uncommitted_changes": bool(dirty)},
        "results_sha256": hashlib.sha256((HERE / "results.json").read_bytes()).hexdigest(),
    }
    (HERE / "run.json").write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
