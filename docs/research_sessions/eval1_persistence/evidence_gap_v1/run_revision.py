"""Set the revised draft beside the original through the product path, and record the result.

Two calls on `build_server(draft_dir=...)` from this repository's `src/`:

1. `check_research_draft_file` with `prior_path` (the original plan, by hash): the file route.
2. `check_research_draft` with `prior_draft` and `revision_decisions`: the same check plus the
   host's decisions, which the file route carries only inside a draft file.

Writes `revision_file_route.json`, `revision_with_decisions.json` and `run.json` (hashes, sizes,
the code revision). Nothing here judges the biology; it records what the code computed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

from virtualcell.mcp.server import build_server

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = HERE.parents[3]
PRIOR = "records/condition_B_payload_2.json"
REVISED = "evidence_gap_v1/draft_revised.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _call(server, tool: str, arguments: dict) -> dict:
    result = asyncio.run(server.call_tool(tool, arguments))
    if result.is_error:
        raise RuntimeError(result.content)
    return result.structured_content


def main() -> None:
    server = build_server(draft_dir=ROOT)
    by_file = _call(
        server,
        "check_research_draft_file",
        {
            "path": REVISED,
            "sha256": _sha(ROOT / REVISED),
            "prior_path": PRIOR,
            "prior_sha256": _sha(ROOT / PRIOR),
        },
    )
    revised = json.loads((ROOT / REVISED).read_text(encoding="utf-8"))
    prior = json.loads((ROOT / PRIOR).read_text(encoding="utf-8"))
    decisions = json.loads((HERE / "decisions.json").read_text(encoding="utf-8"))
    with_decisions = _call(
        server,
        "check_research_draft",
        {**revised, "prior_draft": prior, "revision_decisions": decisions, "view": "compact"},
    )
    outputs = {
        "revision_file_route.json": by_file,
        "revision_with_decisions.json": with_decisions,
    }
    for name, payload in outputs.items():
        (HERE / name).write_text(
            json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
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
            PRIOR: _sha(ROOT / PRIOR),
            REVISED: _sha(ROOT / REVISED),
            "evidence_gap_v1/decisions.json": _sha(HERE / "decisions.json"),
        },
        "outputs": {name: _sha(HERE / name) for name in outputs},
        "revision_same_on_both_routes_apart_from_decisions": _strip(by_file["revision"])
        == _strip(with_decisions["revision"]),
    }
    (HERE / "run.json").write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(run, indent=1))


def _strip(revision: dict) -> dict:
    """The revision without what only the decisions add, for comparing the two routes."""
    keep = dict(revision)
    for key in ("decisions", "findings", "untraced_changes", "undecided_changes"):
        keep.pop(key, None)
    keep["changes"] = [{**c, "decided_as": []} for c in keep["changes"]]
    keep["new_evidence_use"] = [{**u, "decisions": []} for u in keep["new_evidence_use"]]
    return keep


if __name__ == "__main__":
    main()
