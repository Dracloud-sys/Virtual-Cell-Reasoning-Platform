"""Set revision 2 beside revision 1 and beside the original, on the product path, and record it.

Writes:
- `revision_r1_to_r2.json`: check_research_draft_file on revision 2 with revision 1 as prior,
  then the same inline with `decisions_r2.json`;
- `revision_original_to_r2.json`: revision 2 against the original plan, no decisions;
- `prediction_changes.json`: for each comparison, predictions split into value changed, added,
  removed, and changed in other fields only (an empty value_changes does not mean the
  predictions are unchanged);
- `run_r2.json`: code revision and input/output hashes.

Nothing here judges the biology. Revision 1's own record (`../revision_*.json`) is not rewritten.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

from virtualcell.mcp.server import build_server

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPO = HERE.parents[4]
ORIGINAL = "records/condition_B_payload_2.json"
REVISION_1 = "evidence_gap_v1/draft_revised.json"
REVISION_2 = "evidence_gap_v1/r2/draft_revised_r2.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _call(server, tool: str, arguments: dict) -> dict:
    result = asyncio.run(server.call_tool(tool, arguments))
    if result.is_error:
        raise RuntimeError(result.content)
    return result.structured_content


def _file_check(server, prior: str) -> dict:
    return _call(
        server,
        "check_research_draft_file",
        {
            "path": REVISION_2,
            "sha256": _sha(ROOT / REVISION_2),
            "prior_path": prior,
            "prior_sha256": _sha(ROOT / prior),
        },
    )


def _prediction_changes(revision: dict) -> dict:
    moved = {v["prediction"] for v in revision["value_changes"]}
    out: dict[str, list] = {"value_changed": [], "added": [], "removed": [], "other_fields": []}
    for c in revision["changes"]:
        if c["kind"] != "prediction":
            continue
        if c["change"] in ("added", "removed"):
            out[c["change"]].append(c["id"])
        elif c["id"] in moved:
            out["value_changed"].append(c["id"])
        else:
            out["other_fields"].append({"id": c["id"], "fields": c["fields"]})
    out["value_changes"] = revision["value_changes"]
    return out


def _write(name: str, payload: object) -> None:
    (HERE / name).write_text(
        json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    server = build_server(draft_dir=ROOT)
    r1_to_r2 = {
        "file_route": _file_check(server, REVISION_1),
        "with_decisions": _call(
            server,
            "check_research_draft",
            {
                **json.loads((ROOT / REVISION_2).read_text(encoding="utf-8")),
                "prior_draft": json.loads((ROOT / REVISION_1).read_text(encoding="utf-8")),
                "revision_decisions": json.loads(
                    (HERE / "decisions_r2.json").read_text(encoding="utf-8")
                ),
                "view": "compact",
            },
        ),
    }
    original_to_r2 = _file_check(server, ORIGINAL)
    _write("revision_r1_to_r2.json", r1_to_r2)
    _write("revision_original_to_r2.json", original_to_r2)
    _write(
        "prediction_changes.json",
        {
            "r1_to_r2": _prediction_changes(r1_to_r2["with_decisions"]["revision"]),
            "original_to_r2": _prediction_changes(original_to_r2["revision"]),
        },
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
    names = ["revision_r1_to_r2.json", "revision_original_to_r2.json", "prediction_changes.json"]
    run = {
        "code": {"git_head": head, "src_uncommitted_changes": bool(dirty)},
        "inputs": {
            p: _sha(ROOT / p)
            for p in (ORIGINAL, REVISION_1, REVISION_2, "evidence_gap_v1/r2/decisions_r2.json")
        },
        "outputs": {n: _sha(HERE / n) for n in names},
    }
    (HERE / "run_r2.json").write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(run, indent=1))


if __name__ == "__main__":
    main()
