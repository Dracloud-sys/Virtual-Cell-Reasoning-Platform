"""Re-run the U-S-P reference case with the current code and compare with the stored record.

`../results.json` (computed at 1660785) is not rewritten. This prints, per run and comparison,
whether the state paths, final states, repetition, differences and readouts are unchanged, and
what changed in the tracing (dependencies, drafts). Also re-checks every hand-traced value.

    python compare_case.py > case_compare.json
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from virtualcell.mcp.server import build_server

CASE = Path(__file__).resolve().parents[1]


def _call(server, args: dict) -> dict:
    result = asyncio.run(server.call_tool("run_logic_model", args))
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


def _strip(repetition: list[dict]) -> list[dict]:
    """Repetition without the field added in this review, for comparing with the record."""
    return [{k: v for k, v in r.items() if k != "reason"} for r in repetition]


def main() -> None:
    case = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
    hand = json.loads((CASE / "expected_by_hand.json").read_text(encoding="utf-8"))
    stored = json.loads((CASE / "results.json").read_text(encoding="utf-8"))
    server = build_server()
    steps = case["steps"]
    out: dict = {"runs": {}, "comparisons": {}, "hand": {"checked": 0, "mismatched": []}}

    def scenario(name: str) -> dict:
        return {"name": name, **case["scenarios"][name]}

    for model in case["models"]:
        mid = model["id"]
        for name in case["scenarios"]:
            now = _call(
                server, {"model": model, "scenario": scenario(name), "steps": steps, "view": "full"}
            )
            was = stored["runs"][f"{mid}/{name}"]
            paths = {_key(c["case"]): _rows(c) for c in now["cases"]}
            out["runs"][f"{mid}/{name}"] = {
                "paths_unchanged": paths == was["paths_USP"],
                "final_unchanged": now["final"] == was["final"],
                "repetition_unchanged": _strip(now["repetition"]) == was["repetition"],
                "repetition_now": now["repetition"],
                # The record predates `sides`; it is empty for a run's own dependencies.
                "dependencies_unchanged": now["dependencies"]
                == [
                    {**d, "rules": [{**r, "sides": []} for r in d["rules"]]}
                    for d in was["dependencies"]
                ],
            }
            out["hand"]["checked"] += 1
            if paths != hand["paths"][mid][name]:
                out["hand"]["mismatched"].append(f"path {mid}/{name}")
        for name, base in case["comparisons"]:
            now = _call(
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
            key = f"{mid}/{name}_vs_{base}"
            was = stored["comparisons"][key]
            final = next(r for r in now["readouts"] if r["t"] == steps)
            out["comparisons"][key] = {
                "differences_unchanged": [d for d in now["differences"] if d["status"] != "same"]
                == was["differences"],
                "readout_unchanged": final == was["readout_final"],
                "draft_expected_unchanged": [d["expected"] for d in now["prediction_drafts"]]
                == [d["expected"] for d in was["prediction_drafts"]],
                "draft_evidence_and_assumptions_now": [
                    {"evidence_ids": d["evidence_ids"], "assumptions": d["assumptions"]}
                    for d in now["prediction_drafts"]
                ],
                "draft_assumptions_before": [d["assumptions"] for d in was["prediction_drafts"]],
                "relative_rules_now": [
                    [(r["rule_id"], r["sides"]) for r in rel["rules"]]
                    for rel in now["relative_dependencies"]
                ],
            }
            out["hand"]["checked"] += 1
            expected = hand["readout_R_P_at_step_6_vs_baseline"][mid][name]
            if final["versus_baseline"] != expected:
                out["hand"]["mismatched"].append(f"readout {key}")
    print(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
