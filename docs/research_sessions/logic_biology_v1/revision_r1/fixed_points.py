"""Which of the 32 internal states are fixed points of each model under each scenario?

A fixed point is a state that every rule maps to itself. That is a property of the rules and the
inputs alone: every update scheme (synchronous, asynchronous, any order) has the same fixed
points, because each rule must already return the current value. So this check needs one
synchronous step per state, and its answer does not depend on the update scheme. What the
engine's synchronous path does when there is no fixed point (the cycles in `../results.json`) does
depend on the scheme; no other scheme is run here.

Every call is `run_logic_model` on `build_server()`, 1 step, all internal states unknown, so
each of the 32 cases starts from one state; a case is a fixed point if its state at step 1
equals its state at step 0.

    python fixed_points.py > fixed_points.json
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from virtualcell.mcp.server import build_server

CASE = Path(__file__).resolve().parents[1]
INTERNAL = ("RAS", "RAF", "pMEK", "pERK", "pRaf1fb")


def fixed_points(server, case: dict, model: dict, name: str) -> list[dict]:
    scenario = {"name": name, "initial": case["initial"], **case["scenarios"][name]}
    result = asyncio.run(
        server.call_tool(
            "run_logic_model",
            {"model": model, "scenario": scenario, "steps": 1, "view": "full"},
        )
    )
    if result.is_error:
        raise RuntimeError(result.content)
    out = result.structured_content
    assert out["cases_explored"] == out["cases_total"] == 32
    found = []
    for c in out["cases"]:
        before, after = c["path"][0], c["path"][1]
        if all(before[k] == after[k] for k in INTERNAL):
            found.append({k: before[k] for k in INTERNAL})
    return found


def main() -> None:
    case = json.loads((CASE / "prereg" / "case.json").read_text(encoding="utf-8"))
    server = build_server()
    out = {
        f"{model['id']}/{name}": fixed_points(server, case, model, name)
        for model in case["models"]
        for name in case["scenarios"]
    }
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
