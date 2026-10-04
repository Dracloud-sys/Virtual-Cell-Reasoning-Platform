"""Run the pre-registered ERK-feedback case through the MCP tool and compare with the observations.

Every model run is `run_logic_model` on `build_server()`, the path a host uses. Inputs are
`prereg/case.json` (fixed and committed before the results text was read) and
`observations.json` (category B). Writes:
- `results.json`: per model and comparison, the run hashes, repetition, the window states and
  both readings per readout, and the rules each readout's comparison rests on;
- `comparison.json`: one row per observation with its class under each reading and model;
- `run.json`: code revision, input/output hashes, call count, wall time and response sizes.

    python run_case.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import time
from pathlib import Path

from virtualcell.mcp.server import build_server

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ORDER = {"always_inactive": 0, "intermittent": 1, "always_active": 2}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _call(server, arguments: dict) -> tuple[dict, float, int]:
    start = time.perf_counter()
    result = asyncio.run(server.call_tool("run_logic_model", arguments))
    elapsed = time.perf_counter() - start
    if result.is_error:
        raise RuntimeError(result.content)
    out = result.structured_content
    return out, elapsed, len(json.dumps(out).encode("utf-8"))


def _single(directions: set[str]) -> str:
    if len(directions) == 1 and next(iter(directions)) in ("increase", "decrease", "no_change"):
        return next(iter(directions))
    return "undetermined"


def strict_reading(out: dict, readout: str, window: range) -> dict:
    """The engine's own per-case paired directions, required to agree over the whole window."""
    seen: dict[str, int] = {}
    for r in out["readouts"]:
        if r["readout"] == readout and r["t"] in window:
            if not r["paired"]:
                seen["unpaired"] = seen.get("unpaired", 0) + 1
            for direction in r["paired"].values():
                seen[direction] = seen.get(direction, 0) + 1
    return {"direction": _single(set(seen)), "counts": dict(sorted(seen.items()))}


def _window_class(values: list[bool | None]) -> str | None:
    if any(v is None for v in values):
        return None
    if all(values):
        return "always_active"
    if not any(values):
        return "always_inactive"
    return "intermittent"


def ordinal_reading(out: dict, state: str, window: range) -> dict:
    """Host aggregation fixed in the pre-registration: window class per case and side."""
    pairs: dict[str, int] = {}
    directions = set()
    base = {c["case"]: c for c in out["baseline_cases"]}
    for case in out["cases"]:
        a = _window_class([case["path"][t][state] for t in window])
        b = _window_class([base[case["case"]]["path"][t][state] for t in window])
        if a is None or b is None:
            direction = "undetermined"
        elif ORDER[a] == ORDER[b]:
            direction = "no_change"
        else:
            direction = "increase" if ORDER[a] > ORDER[b] else "decrease"
        directions.add(direction)
        key = f"{b} -> {a}"
        pairs[key] = pairs.get(key, 0) + 1
    return {"direction": _single(directions), "baseline_to_scenario": dict(sorted(pairs.items()))}


def classify(row: dict, question: dict, model_direction: str | None) -> tuple[str, str]:
    if question.get("precommitted_class"):
        return question["precommitted_class"], question["why"]
    if row["group"] not in ("KRAS", "BRAF"):
        return "비교 불가", "no scenario for this cell system"
    if row["direction"] is None:
        return "비교 불가", "no direction versus untreated stated in the text read"
    if model_direction == "undetermined":
        return "미결정", "the model's direction under this reading is undetermined"
    if model_direction == row["direction"]:
        return "부합", "same direction"
    return "불일치", f"model {model_direction}, text {row['direction']}"


def compute(case: dict, obs: dict) -> tuple[dict, dict, list[dict]]:
    """Run every pre-registered comparison and classify every observation row."""
    server = build_server()
    window = range(case["window"]["first"], case["window"]["last"] + 1)
    by_readout = {r["readout"]: r for r in case["readouts"]}
    questions = {q["id"]: q for q in case["questions"]}

    def scenario(name: str) -> dict:
        return {"name": name, "initial": case["initial"], **case["scenarios"][name]}

    results: dict = {}
    calls: list[dict] = []
    for model in case["models"]:
        mid = model["id"]
        for group, pair in case["comparisons"].items():
            out, elapsed, size = _call(
                server,
                {
                    "model": model,
                    "scenario": scenario(pair["scenario"]),
                    "baseline": scenario(pair["baseline"]),
                    "steps": case["steps"],
                    "readouts": case["readouts"],
                    "hypothesis_id": f"H_{mid}",
                    "max_cases": case["max_cases"],
                    "view": "full",
                },
            )
            calls.append({"run": f"{mid}/{group}", "seconds": round(elapsed, 4), "bytes": size})
            relative = {d["readout"]: d for d in out["relative_dependencies"]}
            results[f"{mid}/{group}"] = {
                "model_sha256": out["model_sha256"],
                "run_sha256": out["run_sha256"],
                "cases_explored": out["cases_explored"],
                "cases_total": out["cases_total"],
                "exploration_complete": out["exploration_complete"],
                "repetition_scenario": sorted(
                    {(r["status"], r["period"]) for r in out["repetition"]}, key=str
                ),
                "limits_reached": out["limits_reached"],
                "readouts": {
                    name: {
                        "state": m["state"],
                        "strict": strict_reading(out, name, window),
                        "ordinal": ordinal_reading(out, m["state"], window),
                        "rules": [
                            {
                                "rule_id": u["rule_id"],
                                "sides": u["sides"],
                                "evidence_ids": u["evidence_ids"],
                            }
                            for u in relative[name]["rules"]
                        ],
                    }
                    for name, m in by_readout.items()
                },
                "draft_basis": sorted({d["basis"] for d in out["prediction_drafts"]}),
            }
            # Baseline repetition, from the case paths, without re-running.
            base_out, elapsed, size = _call(
                server,
                {
                    "model": model,
                    "scenario": scenario(pair["baseline"]),
                    "steps": case["steps"],
                    "max_cases": case["max_cases"],
                },
            )
            calls.append(
                {"run": f"{mid}/{group}/baseline_only", "seconds": round(elapsed, 4), "bytes": size}
            )
            results[f"{mid}/{group}"]["repetition_baseline"] = sorted(
                {(r["status"], r["period"]) for r in base_out["repetition"]}, key=str
            )

    rows = []
    for row in obs["rows"]:
        q = questions[row["question"]]
        entry = {
            "row": row["id"],
            "question": row["question"],
            "evidence_id": row["evidence_id"],
            "cells": row["cells"],
            "time_in_text": row["time"],
            "text_direction": row["direction"],
        }
        for model in case["models"]:
            mid = model["id"]
            for reading in ("strict", "ordinal"):
                key = f"{mid}/{row['group']}"
                direction = None
                # O6 has no mapped comparison: the MEK-inhibitor run is not its comparison.
                if not q.get("precommitted_class") and key in results:
                    direction = results[key]["readouts"][q["readout"]][reading]["direction"]
                cls, why = classify(row, q, direction)
                entry[f"{mid}/{reading}"] = {"model": direction, "class": cls, "why": why}
        rows.append(entry)
    tally = {}
    for model in case["models"]:
        for reading in ("strict", "ordinal"):
            col = f"{model['id']}/{reading}"
            counts: dict[str, int] = {}
            for r in rows:
                counts[r[col]["class"]] = counts.get(r[col]["class"], 0) + 1
            tally[col] = dict(sorted(counts.items()))

    return results, {"rows": rows, "tally_of_all_rows": tally, "rows_total": len(rows)}, calls


def main() -> None:
    case = json.loads((HERE / "prereg" / "case.json").read_text(encoding="utf-8"))
    obs = json.loads((HERE / "observations.json").read_text(encoding="utf-8"))
    results, comparison, calls = compute(case, obs)
    tally = comparison["tally_of_all_rows"]
    for name, data in (("results.json", results), ("comparison.json", comparison)):
        (HERE / name).write_text(
            json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", str(REPO / "src")],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    ).stdout.strip()
    run = {
        "code": {"git_head": head, "src_uncommitted_changes": bool(dirty)},
        "inputs": {
            n: _sha(HERE / n) for n in ("prereg/case.json", "prereg/PREREG.md", "observations.json")
        },
        "outputs": {n: _sha(HERE / n) for n in ("results.json", "comparison.json")},
        "tool_calls": len(calls),
        "calls": calls,
        "seconds_total": round(sum(c["seconds"] for c in calls), 4),
        "response_bytes_total": sum(c["bytes"] for c in calls),
        "note": "Seconds and bytes vary between runs and machines; they are not outputs.",
    }
    (HERE / "run.json").write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: run[k] for k in ("code", "tool_calls", "seconds_total")}, indent=1))
    print(json.dumps(tally, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
