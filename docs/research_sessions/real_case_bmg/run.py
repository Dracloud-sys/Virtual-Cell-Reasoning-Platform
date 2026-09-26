"""Drive this case through the product path: build_server() and its tools, in-process.

1. repeat the literature search and the section reads, so the cited ids are server-issued;
2. check_research_draft on plan.json;
3. ingest bmg_alamar_tidy.csv under dataset_spec.json (the existing DatasetSpec path);
4. compare_research_observations with rules_and_mappings.json and, if given, decisions.json.

Needs network (Europe PMC). Usage: python run.py <out_dir> [decisions.json]
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

from virtualcell.composition import default_literature_agent
from virtualcell.ingestion import DatasetSpec, ingest_file
from virtualcell.mcp.server import build_server

HERE = Path(__file__).resolve().parent
QUERY = "bulk metallic glass Ti40Zr10Cu36Pd14 fibroblasts"
PAPER_DOI = "10.1016/j.mtbio.2022.100378"
SECTIONS = ("sec2.5.2", "sec2.6.1", "sec2.6.2", "sec2.8", "sec3.3", "sec6")
PLAN_FIELDS = (
    "question",
    "restated_question",
    "assumptions",
    "hypotheses",
    "experiments",
    "objectives",
    "sub_questions",
    "mechanism_links",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    out = Path(sys.argv[1])
    decisions = json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv) > 2 else []
    server = build_server(literature_agent=default_literature_agent())

    def call(tool, args):
        result = asyncio.run(server.call_tool(tool, args))
        if result.is_error:
            raise SystemExit(f"{tool}: {result.content[0].text}")
        return result.structured_content

    found = call("research_evidence", {"question": QUERY, "search_literature": True})
    paper = next(
        e for e in found["evidence"] if (e["locator"]["article"].get("doi") or "") == PAPER_DOI
    )
    evidence, reads = [], []
    for section in SECTIONS:
        page = call(
            "read_evidence_source",
            {"evidence_id": paper["id"], "part": "full_text", "section": section},
        )
        reads.append(
            {
                k: page.get(k)
                for k in ("status", "span_start", "span_end", "total_chars", "reached_end")
            }
            | {"section": section}
        )
        evidence.extend(page.get("evidence", []))

    plan = json.loads((HERE / "plan.json").read_text())
    cited = {e["id"] for e in evidence}
    missing = sorted({i for x in plan["evidence_links"] for i in [x["evidence_id"]]} - cited)
    if missing:
        raise SystemExit(f"plan cites ids the server did not issue this run: {missing}")
    draft = {**plan, "evidence": evidence}
    check = call("check_research_draft", draft)

    spec = DatasetSpec.model_validate(json.loads((HERE / "dataset_spec.json").read_text()))
    ingested = ingest_file(HERE / "bmg_alamar_tidy.csv", spec)
    runs = [r.model_dump(mode="json") for r in ingested.runs]

    rules = json.loads((HERE / "rules_and_mappings.json").read_text())
    mappings = [{k: v for k, v in m.items() if k != "key"} for m in rules["mappings"]]
    compared = call(
        "compare_research_observations",
        {
            **{k: plan[k] for k in PLAN_FIELDS if k in plan},
            "evidence": evidence,
            "runs": runs,
            "mappings": mappings,
            "decisions": decisions,
        },
    )

    inventory = []
    for run in ingested.runs:
        for obs in run.observations:
            cond = run.effective_conditions(obs)
            used_in = [
                f"{m['key']}:{arm}"
                for m in rules["mappings"]
                for arm, sel in (("treatment", m["treatment"]), ("reference", m["reference"]))
                if all(cond.get(k) == v for k, v in sel.items())
                and obs.time_point.model_dump(mode="json") == m["time_point"]
            ]
            inventory.append(
                {
                    "observation_id": obs.observation_id,
                    "source": f"{cond['source_sheet']}!{cond['source_cell']}",
                    "group": cond["group"],
                    "hours": obs.time_point.value,
                    "rfu": obs.measurements[0].value,
                    "quality": obs.measurements[0].quality.value,
                    "used_in": used_in,
                    "not_used_because": None
                    if used_in
                    else "no mapping selects this group: no prediction or check names it",
                }
            )

    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "inputs_sha256": {
            name: sha(HERE / name)
            for name in (
                "bmg_alamar_tidy.csv",
                "dataset_spec.json",
                "plan.json",
                "rules_and_mappings.json",
            )
        },
        "decisions_sha256": sha(Path(sys.argv[2])) if len(sys.argv) > 2 else None,
        "ingestion": {
            "status": ingested.status.value,
            "runs": [r.run_id for r in ingested.runs],
            "observations": sum(len(r.observations) for r in ingested.runs),
            "rejected_rows": [r.model_dump(mode="json") for r in ingested.rejected_rows],
            "qc_qualities": sorted({d.quality.value for d in ingested.qc.decisions}),
        },
        "paper_reads": reads,
        "revision_id": compared["comparison"]["revision_id"],
        "prior_plan_sha256": compared["comparison"]["prior_plan_sha256"],
        "observations_sha256": compared["comparison"]["observations_sha256"],
    }
    for name, payload in (
        ("manifest.json", manifest),
        ("draft_check.json", check),
        ("observation_inventory.json", inventory),
        ("comparison.json", compared),
    ):
        (out / name).write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
