"""Measure the window view on the ERK case of logic_biology_v1, against full and summary.

Reads `../logic_biology_v1/prereg/case.json` (unchanged): M1 and M2, KRAS and BRAF, 24 steps,
window 18-24, all four readouts. For each run it calls `run_logic_model` on `build_server()`
three times (view full, summary, window) and records:
- bytes of the structured content (`json.dumps`, default separators, the same as
  `logic_biology_v1/run_case.py` used) and of the MCP text blocks;
- wall time of each call;
- whether the window answers the same questions as an independent recomputation from the full
  view's case paths: the class per case and side, and the paired directions per case.

Writes `measure.json` (sizes, times, agreement, code revision) and `window_results.json` (the
`window` part of the four window responses, with the model and run hashes). No full or
summary response is stored.

    python measure_erk.py
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
ERK = HERE.parent / "logic_biology_v1" / "prereg" / "case.json"
FIRST, LAST = 18, 24


def _call(server, args: dict) -> tuple[dict, dict]:
    start = time.perf_counter()
    result = asyncio.run(server.call_tool("run_logic_model", args))
    seconds = time.perf_counter() - start
    if result.is_error:
        raise RuntimeError(result.content)
    out = result.structured_content
    return out, {
        "seconds": round(seconds, 4),
        "structured_bytes": len(json.dumps(out).encode("utf-8")),
        "text_block_bytes": sum(
            len(getattr(c, "text", "").encode("utf-8")) for c in result.content
        ),
    }


def _class(values: list) -> str:
    if all(v is None for v in values):
        return "not_computed"
    if any(v is None for v in values):
        return "partly_not_computed"
    if set(values) == {True}:
        return "all_active"
    if set(values) == {False}:
        return "all_inactive"
    return "both_values"


def _dir(a, b) -> str:
    if a is None or b is None:
        return "undetermined"
    return "no_change" if a == b else ("increase" if a else "decrease")


def reference(full: dict, state: str) -> dict:
    """The window's questions answered from the full paths, by separate code."""
    window = range(FIRST, LAST + 1)
    base = {c["case"]: c for c in full["baseline_cases"]}
    return {
        "scenario": {
            c["case"]: _class([c["path"][t][state] for t in window]) for c in full["cases"]
        },
        "baseline": {
            c["case"]: _class([c["path"][t][state] for t in window]) for c in full["baseline_cases"]
        },
        "paired": {
            c["case"]: sorted(
                {_dir(c["path"][t][state], base[c["case"]]["path"][t][state]) for t in window}
            )
            for c in full["cases"]
        },
    }


def from_window(window: dict, target: dict) -> dict:
    labels = window["cases"]
    return {
        side: {labels[i]: g["window_class"] for g in target[side]["groups"] for i in g["cases"]}
        for side in ("scenario", "baseline")
    } | {
        "paired": {
            labels[i]: g["directions"] for g in target["paired"]["groups"] for i in g["cases"]
        }
    }


def main() -> None:
    case = json.loads(ERK.read_text(encoding="utf-8"))
    server = build_server()
    states = {r["readout"]: r["state"] for r in case["readouts"]}
    names = sorted(states)
    runs, windows = {}, {}
    for model in case["models"]:
        for group, pair in case["comparisons"].items():

            def sc(name):
                return {"name": name, "initial": case["initial"], **case["scenarios"][name]}

            base = {
                "model": model,
                "scenario": sc(pair["scenario"]),
                "baseline": sc(pair["baseline"]),
                "steps": case["steps"],
                "readouts": case["readouts"],
                "max_cases": case["max_cases"],
            }
            full, m_full = _call(server, {**base, "view": "full"})
            summ, m_summ = _call(server, {**base, "view": "summary"})
            win, m_win = _call(
                server,
                {
                    **base,
                    "view": "window",
                    "window": {"first": FIRST, "last": LAST, "targets": names},
                },
            )
            agree = {
                t["target"]: from_window(win["window"], t) == reference(full, states[t["target"]])
                for t in win["window"]["targets"]
            }
            key = f"{model['id']}/{group}"
            windows[key] = {k: win[k] for k in ("model_sha256", "run_sha256", "window")}
            runs[key] = {
                "run_sha256": {
                    "full": full["run_sha256"],
                    "summary": summ["run_sha256"],
                    "window": win["run_sha256"],
                },
                "window_request_sha256": win["window"]["request_sha256"],
                "full": m_full,
                "summary": m_summ,
                "window": m_win,
                "window_over_full": round(
                    m_win["structured_bytes"] / m_full["structured_bytes"], 5
                ),
                "window_over_summary": round(
                    m_win["structured_bytes"] / m_summ["structured_bytes"], 5
                ),
                "window_agrees_with_full_paths": agree,
                "pairing": win["window"]["pairing"]["status"],
                "exploration_complete": win["exploration_complete"],
            }
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
    (HERE / "window_results.json").write_text(
        json.dumps(windows, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    totals = {
        view: {
            "calls": len(runs),
            "seconds": round(sum(r[view]["seconds"] for r in runs.values()), 4),
            "structured_bytes": sum(r[view]["structured_bytes"] for r in runs.values()),
            "text_block_bytes": sum(r[view]["text_block_bytes"] for r in runs.values()),
        }
        for view in ("full", "summary", "window")
    }
    measure = {
        "code": {"git_head": head, "src_uncommitted_changes": bool(dirty)},
        "input_sha256": hashlib.sha256(ERK.read_bytes()).hexdigest(),
        "window": {"first": FIRST, "last": LAST, "targets": names},
        "runs": runs,
        "totals": totals,
        "note": "Seconds vary between runs and machines. Bytes are of this code and this input; "
        "they are not tokens or cost.",
    }
    (HERE / "measure.json").write_text(
        json.dumps(measure, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"code": measure["code"], "totals": totals}, indent=1))
    print(
        json.dumps(
            {
                k: (r["window_over_full"], r["window_agrees_with_full_paths"])
                for k, r in runs.items()
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
