"""Review r2 of the model-observation link: groups without values, and category names.

Every input is built from the original builders (`../cases.py`) and the review r1 builders
(`../review_r1/cases.py`), which this file imports and does not change. Every call is
`compare_model_observation` (or `run_logic_model`) on `build_server()`.

    python cases.py        # writes results.json and run.json here
"""

from __future__ import annotations

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


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode, before = True, sys.dont_write_bytecode
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


r1 = _load("model_observation_review_r1", HERE.parent / "review_r1" / "cases.py")
base = r1.base
attempt = r1.attempt


# --- B: every case is in a group, but a group carries no direction ------------------------- #


def empty_directions(t3: dict) -> dict[str, dict]:
    """T3 copies; cases and counts unchanged, directions emptied, the top level kept in step."""

    def edit(empty):
        args = copy.deepcopy(t3)
        p = r1._paired(args)
        for g in p["groups"]:
            if empty(g):
                g["directions"] = []
        p["directions"] = sorted({d for g in p["groups"] for d in g["directions"]})
        return args

    return {
        "B1_one_group_without_directions": edit(lambda g: "no_change" in g["directions"]),
        "B2_no_group_with_directions": edit(lambda g: True),
    }


def undetermined(server) -> dict:
    """A real engine result whose only direction is undetermined: Z has no rule."""
    result = base.call(
        server,
        "run_logic_model",
        {
            "model": base.MODELS["norule"],
            "scenario": base._sc("T", {"Z": True}),
            "baseline": base._sc("B", {"Z": True}),
            "steps": 4,
            "view": "window",
            "window": {"first": 2, "last": 4, "targets": ["Z"]},
        },
    )
    return {"model_result": result, "runs": [base.UP], "link": base.link(result, table=base.SAME)}


# --- I: a declared category that happens to be called "indeterminate" ------------------------ #


def renamed(args: dict, old: str = "A", new: str = "indeterminate") -> dict:
    """The same categorical case with one category renamed everywhere it is declared or read."""
    out = copy.deepcopy(args)
    c = out["link"]["correspondence"]
    c["observed_vocabulary"] = [new if v == old else v for v in c["observed_vocabulary"]]
    for e in c["table"]:
        if e["observed_value"] == old:
            e["observed_value"] = new
    for run in out["runs"]:
        for o in run["observations"]:
            for m in o["measurements"]:
                if m.get("value") == old:
                    m["value"] = new
    return out


# --- N: the rule's own between-bands class ---------------------------------------------------- #

MIDDLE = base.run_record([({"arm": "T"}, [1.3]), ({"arm": "B"}, [1.0])])
MIDDLE_CTRL = base.run_record([({"arm": "T"}, [1.3]), ({"arm": "ctrl"}, [1.0])])


def all_cases(server) -> dict[str, dict]:
    original = base.synthetic_cases(server)
    categorical = r1.categorical_cases(server)
    held = copy.deepcopy(original["T6b_host_proposed_reference"])
    held["runs"] = [MIDDLE_CTRL]
    stated = copy.deepcopy(held)
    stated["link"]["observation"]["reference_correspondence"]["stated_by"] = "researcher"
    between = copy.deepcopy(original["T1_consistent"])
    between["runs"] = [MIDDLE]
    return (
        empty_directions(original["T3_partial"])
        | {"U1_engine_undetermined": undetermined(server)}
        | {
            f"I{i}_{name}_renamed": renamed(categorical[name])
            for i, name in enumerate(("C1_A_vs_A", "C2_A_vs_B", "C3_AB_vs_A"), start=1)
        }
        | {
            "N1_between_bands": between,
            "N2_between_bands_held": held,
            "N3_between_bands_stated": stated,
        }
    )


def summary(out: dict) -> dict:
    return r1.summary(out)


def main() -> None:
    server = build_server()
    results = {name: summary(attempt(server, args)) for name, args in all_cases(server).items()}
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
