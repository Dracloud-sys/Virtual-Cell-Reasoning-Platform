"""Check revision 2 against an independent calculation, and against the original run.

* Medians, minima, maxima and counts are recomputed straight from bmg_alamar_tidy.csv with the
  standard library and compared with each arm summary in results_r2/comparison.json.
* Statuses, reasons, class counts, reference links and every outcome are compared with the
  original results/comparison.json: revision 2 must add a description and change no judgement.

Usage: python check_r2.py  (writes results_r2/descriptive_check.json)
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    rows = list(csv.DictReader((HERE / "bmg_alamar_tidy.csv").open(encoding="utf-8")))
    by = {}
    for i, r in enumerate(rows):
        key = (float(r["culture_hours"]), r["group_label"])
        by.setdefault(key, []).append((f"bmg_alamar_tidy.csv:row{i}", float(r["rfu"])))

    new = json.loads((HERE / "results_r2/comparison.json").read_text())["comparison"]
    old = json.loads((HERE / "results/comparison.json").read_text())["comparison"]
    mappings = json.loads((HERE / "rules_and_mappings.json").read_text())["mappings"]

    checks, mismatches = [], []
    for m, row, before in zip(mappings, new["comparisons"], old["comparisons"], strict=True):
        hours = m["time_point"]["value"]
        for arm, sel in (("treatment", m["treatment"]), ("reference", m["reference"])):
            ids, values = zip(*by[(hours, sel["group"])], strict=True)
            expected = {
                "observation_ids": list(ids),
                "recorded": len(values),
                "values": list(values),
                "median": statistics.median(values),
                "minimum": min(values),
                "maximum": max(values),
            }
            got = row[f"{arm}_summary"]
            for k, v in expected.items():
                if got[k] != v:
                    mismatches.append(f"{m['key']} {arm} {k}: {got[k]!r} != {v!r}")
            checks.append({"mapping": m["key"], "arm": arm, "group": sel["group"], **expected})
        if dict(Counter(row["pairwise_classes"])) != row["pairwise_class_counts"]:
            mismatches.append(f"{m['key']}: class counts disagree with classes")
        for field in (
            "status",
            "reasons",
            "observed",
            "pairwise",
            "pairwise_classes",
            "reference_link",
            "combinations",
            "left_out",
        ):
            if row[field] != before[field]:
                mismatches.append(f"{m['key']} {field}: {before[field]!r} -> {row[field]!r}")
        for a, b in zip(row["by_hypothesis"], before["by_hypothesis"], strict=True):
            if (a["outcome"], a["if_accepted"]) != (b["outcome"], b["if_accepted"]):
                mismatches.append(f"{m['key']} {a['hypothesis_id']} outcome changed")
        for a, b in zip(row["assumption_outcomes"], before["assumption_outcomes"], strict=True):
            if a["outcome"] != b["outcome"]:
                mismatches.append(f"{m['key']} assumption outcome changed")
    report = {
        "independent_summaries": checks,
        "mismatches": mismatches,
        "result": "agree" if not mismatches else "DISAGREE",
    }
    (HERE / "results_r2/descriptive_check.json").write_text(json.dumps(report, indent=1) + "\n")
    print(report["result"], mismatches)


if __name__ == "__main__":
    main()
