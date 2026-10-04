"""Reproduce review items R1-R3 on the product path (`run_logic_model` on `build_server()`).

Prints what the code at the current HEAD returns for each item. The evidence id in R3
(`synthetic-contract-test-ev1`) is a synthetic contract-test label, not a literature source.

    python repro.py > repro_<label>.json
"""

from __future__ import annotations

import asyncio
import json
import sys

from virtualcell.mcp.server import build_server


def _call(server, args: dict) -> dict:
    result = asyncio.run(server.call_tool("run_logic_model", args))
    if result.is_error:
        return {"refused": result.content[0].text}
    return result.structured_content


def main() -> None:
    server = build_server()
    out: dict = {"code": sys.argv[1] if len(sys.argv) > 1 else ""}

    # R1: internal P with no rule, initial true, 3 steps.
    r1 = _call(
        server,
        {
            "model": {
                "id": "r1",
                "components": [{"id": "P", "kind": "internal"}],
                "rules": [],
            },
            "scenario": {"name": "r1", "initial": {"P": True}},
            "steps": 3,
            "view": "full",
        },
    )
    out["R1"] = {
        "path": r1["cases"][0]["path"],
        "P_status_by_step": [s["status"] for s in r1["summary"]],
        "repetition": r1["repetition"],
    }

    # R2: U true at t0-10, false from 11; P(next) = U; initial P true. 3 then 13 steps.
    r2_model = {
        "id": "r2",
        "components": [{"id": "U", "kind": "input"}, {"id": "P", "kind": "internal"}],
        "rules": [{"id": "R", "target": "P", "expr": {"var": "U"}}],
    }
    r2_scenario = {
        "name": "r2",
        "initial": {"P": True},
        "inputs": {
            "U": [
                {"start": 0, "end": 10, "value": True},
                {"start": 11, "end": None, "value": False},
            ]
        },
    }
    for steps in (3, 13):
        r = _call(
            server, {"model": r2_model, "scenario": r2_scenario, "steps": steps, "view": "full"}
        )
        out[f"R2_steps_{steps}"] = {
            "path": r["cases"][0]["path"],
            "repetition": r["repetition"],
        }

    # R3: P(next) = U with a stated assumption and a synthetic evidence id; baseline unclamped,
    # scenario clamps P false; identity readout; hypothesis id requested.
    r3_model = {
        "id": "r3",
        "components": [{"id": "U", "kind": "input"}, {"id": "P", "kind": "internal"}],
        "rules": [
            {
                "id": "R",
                "target": "P",
                "expr": {"var": "U"},
                "evidence_ids": ["synthetic-contract-test-ev1"],
                "assumptions": ["Synthetic contract-test assumption: P follows U."],
            }
        ],
    }
    base = {
        "name": "base",
        "initial": {"P": True},
        "inputs": {"U": [{"start": 0, "end": None, "value": True}]},
    }
    clamped = {**base, "name": "P_off", "clamps": [{"target": "P", "value": False, "start": 0}]}
    r3 = _call(
        server,
        {
            "model": r3_model,
            "scenario": clamped,
            "baseline": base,
            "steps": 3,
            "readouts": [{"readout": "R_P", "state": "P", "mapping": "identity", "basis": "test"}],
            "hypothesis_id": "H_test",
        },
    )
    out["R3"] = {
        "readout_final": next(r for r in r3["readouts"] if r["t"] == 3),
        "dependencies_P": next(d for d in r3["dependencies"] if d["component"] == "P"),
        "prediction_drafts": r3["prediction_drafts"],
        "baseline_dependencies": r3.get("baseline_dependencies"),
        "relative_dependencies": r3.get("relative_dependencies"),
    }
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
