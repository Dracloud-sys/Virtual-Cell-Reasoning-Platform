"""Replay saved check_research_draft payloads through build_server() and measure the replies.

Usage:
    python scripts/research/measure_draft_check.py PAYLOAD.json [PAYLOAD.json ...]

For each payload, calls the tool in-process (the same server a host connects to; this is not
an MCP connection test) in the full and the compact view, and prints one JSON record: reply
sizes, finding counts, how the findings group, and the largest parts of the full reply.
Sizes are compact JSON of the structured result, in bytes; the text block the MCP SDK also
sends is reported separately because it duplicates the structured result.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from virtualcell.mcp.server import build_server


def _size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False))


def _call(server, payload: dict[str, Any], view: str) -> tuple[dict[str, Any], int]:
    result = asyncio.run(server.call_tool("check_research_draft", {**payload, "view": view}))
    if result.is_error:
        raise SystemExit(result.content[0].text)
    text = sum(len(c.text) for c in result.content if getattr(c, "text", None))
    return result.structured_content, text


def measure(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("view", None)
    server = build_server()
    full, full_text = _call(server, payload, "full")
    compact, compact_text = _call(server, payload, "compact")
    plan = full["plan_analysis"] or {}
    traces = plan.get("prediction_traces", [])
    return {
        "payload": path.name,
        "finding_count": full["finding_count"],
        "full_bytes": _size(full),
        "full_text_block_chars": full_text,
        "compact_bytes": _size(compact),
        "compact_text_block_chars": compact_text,
        "largest_full_parts": dict(
            sorted(
                ((f"plan_analysis.{k}", _size(v)) for k, v in plan.items() if _size(v) > 5_000),
                key=lambda kv: -kv[1],
            )
        )
        | {"findings": _size(full["findings"])},
        "trace_decisions_bytes": sum(_size(t["decisions"]) for t in traces),
        "prediction_traces": len(traces),
        "groups": [
            {
                "code": g["code"],
                "kind": g["kind"],
                "source": g["source"],
                "field": g["field"],
                "case": g["case"],
                "count": g["count"],
                "derived": {d["code"]: d["count"] for d in g["derived"]},
            }
            for g in compact["finding_groups"]
        ],
        "not_computed": compact["not_computed"],
    }


def main() -> None:
    records = [measure(Path(arg)) for arg in sys.argv[1:]]
    json.dump(records, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
