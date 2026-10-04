"""Each experiment's pair analysis for each recorded draft, under the importable `virtualcell`.

Run once with this repository's `src/` and once with a checkout of 28c4933 on PYTHONPATH (the
pair analysis before the condition fix). Prints, per draft and experiment: each separated pair
with the readouts and conditions that separate it, unseparated pairs with reasons, and every
readout exclusion. Nothing is written.

    PYTHONPATH=<checkout>/src python pair_analysis.py <label> > pairs_<label>.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import virtualcell
from virtualcell.mcp.server import build_server

ROOT = Path(__file__).resolve().parents[2]
DRAFTS = {
    "original": ROOT / "records" / "condition_B_payload_2.json",
    "revision_1": ROOT / "evidence_gap_v1" / "draft_revised.json",
    "revision_2": ROOT / "evidence_gap_v1" / "r2" / "draft_revised_r2.json",
}


def main() -> None:
    server = build_server()
    out = {"code": sys.argv[1] if len(sys.argv) > 1 else "", "src": virtualcell.__file__}
    for name, path in DRAFTS.items():
        if not path.exists():
            continue
        draft = json.loads(path.read_text(encoding="utf-8"))
        result = asyncio.run(server.call_tool("check_research_draft", {**draft, "view": "full"}))
        content = result.structured_content
        out[name] = {"finding_codes": sorted({f["code"] for f in content["findings"]})}
        for e in content["plan_analysis"]["experiments"]:
            out[name][e["experiment_id"]] = {
                "separated_pairs": {
                    "|".join(p["pair"]): sorted(
                        f"{d['readout']} @ {d.get('condition')}" for d in p["readouts"]
                    )
                    for p in e["separated_pairs"]
                },
                "unseparated_pairs": [[*u["pair"], u["reason"]] for u in e["unseparated_pairs"]],
                "readout_exclusions": [
                    [*x["pair"], x["readout"], x.get("condition"), x["reason"]]
                    for x in e["readout_exclusions"]
                ],
                "outcome_rows": len(e["outcome_table"]),
            }
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
