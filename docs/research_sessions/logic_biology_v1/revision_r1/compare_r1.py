"""Revision r1: re-read the r0 comparison, keeping the text, the recorded direction and the
computation apart.

Reads, and does not change: `../prereg/case.json`, `../observations.json`, `../results.json`
and `../comparison.json` (r0). Adds `row_semantics.json` (r1 annotations). Writes
`comparison_r1.json`: per row and per model/reading column,
- the r0 class (unchanged);
- the text's wording and what it states;
- the direction r0 recorded;
- the computed window classes on each side and the model's direction under the reading;
- every assumption the reading of the computation as a measurement needs;
- an r1 relation: 일치, 조건부 양립, 불일치 (현 모형·판독 규칙 하), 미결정 or 비교 제한.

Nothing is re-run; the model results are r0's. This is a case-local re-reading, not a general
classifier.

    python compare_r1.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
READINGS = ("strict", "ordinal")

IDENTITY = "identity readout: an active state reads as present, an inactive one as absent"
INTERMITTENT = (
    "an intermittent window (the state changes along one logical path) is read as an "
    "intermediate measured level; unverified, and the 32 cases are not cells or weights"
)
SATURATED = (
    "two equal Boolean states (both active, or both inactive) are read as no measured change; "
    "a change within the active state cannot be represented, so this is an assumption, not a "
    "computed equality of levels"
)
WEAKER_TEXT = "the text rules out only an increase; it does not state no change"


def _sides(pairs: dict) -> tuple[set[str], set[str]]:
    base, scen = set(), set()
    for key in pairs:
        b, s = key.split(" -> ")
        base.add(b)
        scen.add(s)
    return base, scen


def relate(stated: str, model: str, reading: str, pairs: dict) -> tuple[str, list[str]]:
    """The r1 relation for one scorable row and column, with the assumptions it needs."""
    if model == "undetermined":
        return "미결정", []
    needs = [IDENTITY]
    base, scen = _sides(pairs)
    if reading == "ordinal" and "intermittent" in base | scen:
        needs.append(INTERMITTENT)
    if model == "no_change":
        needs.append(SATURATED)
    if stated == "no_increase":
        needs.append(WEAKER_TEXT)
        agrees = model in ("no_change", "decrease")
    elif stated == "no_change_observed":
        agrees = model == "no_change"
    else:
        agrees = model == stated
    if not agrees:
        return "불일치 (현 모형·판독 규칙 하)", needs
    return ("일치" if needs == [IDENTITY] else "조건부 양립"), needs


def build() -> dict:
    case = json.loads((CASE / "prereg" / "case.json").read_text(encoding="utf-8"))
    obs = json.loads((CASE / "observations.json").read_text(encoding="utf-8"))
    results = json.loads((CASE / "results.json").read_text(encoding="utf-8"))
    r0 = {r["row"]: r for r in json.loads((CASE / "comparison.json").read_text())["rows"]}
    notes = json.loads((HERE / "row_semantics.json").read_text(encoding="utf-8"))["rows"]
    questions = {q["id"]: q for q in case["questions"]}
    columns = [(m["id"], reading) for m in case["models"] for reading in READINGS]

    rows = []
    for row in obs["rows"]:
        note = notes[row["id"]]
        q = questions[row["question"]]
        entry = {
            "row": row["id"],
            "question": row["question"],
            "series": note["series"],
            "wording": note["wording"],
            "stated": note["stated"],
            "recorded_direction_r0": row["direction"],
        }
        for mid, reading in columns:
            col = f"{mid}/{reading}"
            cell = {"r0_class": r0[row["id"]][col]["class"]}
            if cell["r0_class"] == "비교 불가":
                cell["relation"] = "비교 제한"
                cell["limit_cause"] = note["limit_cause"]
            else:
                run = results[f"{mid}/{row['group']}"]["readouts"][q["readout"]]
                model = run[reading]["direction"]
                pairs = run["ordinal"]["baseline_to_scenario"]
                cell["computed"] = {
                    "window_classes_baseline_to_scenario": pairs,
                    "strict_paired_counts": run["strict"]["counts"],
                    "model_direction": model,
                }
                cell["relation"], cell["assumptions"] = relate(
                    note["stated"], model, reading, pairs
                )
            entry[col] = cell
        rows.append(entry)

    tally = {}
    for mid, reading in columns:
        col = f"{mid}/{reading}"
        counts: dict[str, int] = {}
        for r in rows:
            counts[r[col]["relation"]] = counts.get(r[col]["relation"], 0) + 1
        tally[col] = dict(sorted(counts.items()))
    causes: dict[str, int] = {}
    for r in rows:
        for cause in r[f"{columns[0][0]}/strict"].get("limit_cause", []):
            causes[cause] = causes.get(cause, 0) + 1
    series: dict[str, list[str]] = {}
    for r in rows:
        series.setdefault(r["series"], []).append(r["row"])
    return {
        "about": (
            "Revision r1 of the logic_biology_v1 comparison. Rows are statements in the text, "
            "not independent experiments; several rows share a series. The tallies count rows, "
            "and are not hit rates or a ranking of the models."
        ),
        "rows": rows,
        "tally_of_rows": tally,
        "limit_causes_of_rows": dict(sorted(causes.items())),
        "rows_by_series": series,
        "rows_total": len(rows),
    }


def main() -> None:
    out = build()
    (HERE / "comparison_r1.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(out["tally_of_rows"], indent=1, ensure_ascii=False))
    print(json.dumps(out["limit_causes_of_rows"], indent=1))


if __name__ == "__main__":
    main()
