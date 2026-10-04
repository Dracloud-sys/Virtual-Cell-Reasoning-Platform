"""Run the reference case through the MCP tool and record the results beside the hand trace.

Every call is `run_logic_model` on `build_server()`, the path a host uses. Writes:
- `results.json`: each model x scenario (summary view, plus case paths), and each comparison
  with its baseline, readout and Prediction draft;
- `hand_check.json`: each hand-traced value against the computed one;
- `run.json`: the code revision and input/output hashes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

from virtualcell.mcp.server import build_server

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _call(server, arguments: dict) -> dict:
    result = asyncio.run(server.call_tool("run_logic_model", arguments))
    if result.is_error:
        raise RuntimeError(result.content)
    return result.structured_content


def _rows(case: dict) -> list[str]:
    return [
        "".join("?" if st[c] is None else str(int(st[c])) for c in "USP") for st in case["path"]
    ]


def _key(label: str) -> str:
    if label == "all":
        return label
    name, value = label.split("=")
    return f"{name.split('[')[0]}={value}"


def main() -> None:
    case = json.loads((HERE / "case.json").read_text(encoding="utf-8"))
    hand = json.loads((HERE / "expected_by_hand.json").read_text(encoding="utf-8"))
    server = build_server()
    steps = case["steps"]

    def scenario(name: str) -> dict:
        return {"name": name, **case["scenarios"][name]}

    results: dict = {"runs": {}, "comparisons": {}}
    check: list[dict] = []
    for model in case["models"]:
        mid = model["id"]
        for name in case["scenarios"]:
            out = _call(
                server, {"model": model, "scenario": scenario(name), "steps": steps, "view": "full"}
            )
            paths = {_key(c["case"]): _rows(c) for c in out["cases"]}
            results["runs"][f"{mid}/{name}"] = {
                "model_sha256": out["model_sha256"],
                "run_sha256": out["run_sha256"],
                "unknowns": out["unknowns"],
                "cases_explored": out["cases_explored"],
                "cases_total": out["cases_total"],
                "paths_USP": paths,
                "final": out["final"],
                "repetition": out["repetition"],
                "dependencies": out["dependencies"],
            }
            check.append(
                {
                    "what": f"path {mid}/{name}",
                    "hand": hand["paths"][mid][name],
                    "computed": paths,
                    "match": paths == hand["paths"][mid][name],
                }
            )
        for name, base in case["comparisons"]:
            out = _call(
                server,
                {
                    "model": model,
                    "scenario": scenario(name),
                    "baseline": scenario(base),
                    "steps": steps,
                    "readouts": case["readouts"],
                    "readouts_requested": ["R_P", "alpha_SMA_IF"],
                    "hypothesis_id": f"H_{mid}",
                },
            )
            final = next(r for r in out["readouts"] if r["t"] == steps)
            results["comparisons"][f"{mid}/{name}_vs_{base}"] = {
                "differences": [d for d in out["differences"] if d["status"] != "same"],
                "paired_differences": out["paired_differences"],
                "readout_final": final,
                "readouts_not_derivable": out["readouts_not_derivable"],
                "prediction_drafts": out["prediction_drafts"],
                "limits": out["limits"],
            }
            expected = hand["readout_R_P_at_step_6_vs_baseline"][mid][name]
            check.append(
                {
                    "what": f"R_P at step {steps}, {mid}/{name} vs {base}",
                    "hand": expected,
                    "computed": final["versus_baseline"],
                    "match": final["versus_baseline"] == expected,
                }
            )

    for name, data in (("results.json", results), ("hand_check.json", check)):
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
        "inputs": {n: _sha(HERE / n) for n in ("case.json", "expected_by_hand.json")},
        "outputs": {n: _sha(HERE / n) for n in ("results.json", "hand_check.json")},
        "hand_checks": len(check),
        "hand_mismatches": sum(not c["match"] for c in check),
    }
    (HERE / "run.json").write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(run, indent=1))


if __name__ == "__main__":
    main()
