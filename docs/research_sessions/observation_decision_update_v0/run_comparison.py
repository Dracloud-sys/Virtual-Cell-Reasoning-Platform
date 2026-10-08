"""Compare the ERK case's base and alternative models with one published observation.

Reads `before.json` (fixed before this was first run), the stored window records and the
model-observation link's ERK builders. Calls `compare_model_observation` on `build_server()`
once per model. No model is re-run and no source record is written.

    python run_comparison.py        # writes comparison.json and run.json here
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
DOCS = HERE.parent
REPO = HERE.parents[2]

# Every input file this reads; their hashes go into run.json.
INPUTS = [
    HERE / "before.json",
    DOCS / "logic_window_v0" / "window_results.json",
    DOCS / "logic_biology_v1" / "results.json",
    DOCS / "logic_biology_v1" / "prereg" / "case.json",
    DOCS / "erk_pmek_measurement_v0" / "extracted.json",
    DOCS / "model_observation_link_v0" / "cases.py",
]


def _link_cases():
    path = DOCS / "model_observation_link_v0" / "cases.py"
    spec = importlib.util.spec_from_file_location("model_observation_link_cases", path)
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode, before = True, sys.dont_write_bytecode
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


def model_result(model_id: str) -> dict:
    """The stored KRAS window result of one model, as erk_cases() builds M2's."""
    window = json.loads((DOCS / "logic_window_v0" / "window_results.json").read_text())
    stored = json.loads((DOCS / "logic_biology_v1" / "results.json").read_text())
    case = json.loads((DOCS / "logic_biology_v1" / "prereg" / "case.json").read_text())
    key = f"{model_id}/KRAS"
    pair = case["comparisons"]["KRAS"]
    return {
        "model_id": model_id,
        "model_sha256": window[key]["model_sha256"],
        "run_sha256": window[key]["run_sha256"],
        "scenario": pair["scenario"],
        "baseline": pair["baseline"],
        "cases_explored": stored[key]["cases_explored"],
        "cases_total": stored[key]["cases_total"],
        "exploration_complete": stored[key]["exploration_complete"],
        "window": window[key]["window"],
    }


def comparison_args() -> dict[str, dict]:
    """One argument set per model, from before.json and the PR #41 ERK case."""
    fixed = json.loads((HERE / "before.json").read_text())["comparison_fixed"]
    erk = _link_cases().erk_cases()["E2_category"]
    out = {}
    for entry in fixed["models"]:
        result = model_result(entry["model_id"])
        link = copy.deepcopy(erk["link"])
        link["id"] = f"odu-{entry['model_id']}-pmek-kras"
        link["model"].update(
            run_sha256=result["run_sha256"],
            model_sha256=result["model_sha256"],
        )
        link["observation"]["rule"] = fixed["rule"]
        link["correspondence"].update(
            table=fixed["table"],
            asks="category",
            assumptions=[*link["correspondence"]["assumptions"], fixed["table_assumption"]],
        )
        out[entry["model_id"]] = {"model_result": result, "runs": erk["runs"], "link": link}
    return out


def compare(server, args: dict) -> dict:
    result = asyncio.run(server.call_tool("compare_model_observation", args))
    if result.is_error:
        raise RuntimeError(" ".join(getattr(c, "text", "") for c in result.content))
    return result.structured_content


def record(out: dict) -> dict:
    """What the decision reads: identifiers, the outcome and its grounds. Limits by count only."""
    obs = out["observation"]
    return {
        k: out[k]
        for k in (
            "comparison_id",
            "link_id",
            "link_sha256",
            "observations_sha256",
            "model_id",
            "model_sha256",
            "run_sha256",
            "window_request_sha256",
            "comparability",
            "relation",
            "result",
            "explored_result",
            "if_accepted",
            "reasons",
            "needs",
            "observation_meaning",
            "correspondence_accepted",
            "scientific_validity_checked",
        )
    } | {
        "model_claim": {
            k: out["model_claim"][k]
            for k in ("form", "model_values", "groups", "cases_explored", "applies_to")
        },
        "observation": {
            k: obs[k]
            for k in (
                "status",
                "observed",
                "reasons",
                "treatment_values",
                "reference_values",
                "pairwise",
                "pairwise_classes",
                "versus",
                "reference_link",
                "left_out",
            )
        },
        "correspondence": {
            k: out["correspondence"][k]
            for k in ("table", "stated_by", "accepted_by", "assumptions")
        },
        "observation_findings": [f["code"] for f in out["observation_findings"]],
        "limits_count": len(out["limits"]),
    }


def compute(server) -> dict:
    return {name: record(compare(server, args)) for name, args in comparison_args().items()}


def main() -> None:
    results = compute(build_server())
    (HERE / "comparison.json").write_text(
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
        "calls": {"compare_model_observation": len(results), "run_logic_model": 0},
        "inputs_sha256": {
            str(p.relative_to(DOCS)): hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS
        },
        "comparison_sha256": hashlib.sha256((HERE / "comparison.json").read_bytes()).hexdigest(),
    }
    (HERE / "run.json").write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
