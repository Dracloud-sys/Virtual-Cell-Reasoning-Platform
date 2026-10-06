"""Review r1: keep the normalisation reference and each comparison group apart, per value.

Reads `../extracted.json` only (no download, no model run). For every U0126 value in Fig 6B it
records, separately:
- the value as the authors give it, relative to PBS (their normalisation reference, = 1);
- where it lies against each untreated value of the same line;
- where it lies against the DMSO value of the same line.

Untreated, DMSO and PBS are never pooled into one "control range". No mean, no new
normalisation, no test: these are descriptions of single recorded values, with their file
lines. Writes `baselines.json`.

    python check_baselines.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXTRACTED = HERE.parent / "extracted.json"


def _against(value: float, refs: list[float]) -> str:
    """Where one value lies against each reference value, without combining the references."""
    if all(value < r for r in refs):
        return "below_each"
    if all(value > r for r in refs):
        return "above_each"
    if any(value == r for r in refs):
        return "equal_to_one"
    return "between"


def build() -> dict:
    e = json.loads(EXTRACTED.read_text(encoding="utf-8"))
    rows = e["fig6B"]["rows"]
    out: dict = {
        "about": (
            "Fig 6B, per value. 'value_vs_PBS' is the authors' number: relative to PBS-treated "
            "cells (= 1). Untreated and DMSO are separate rows with their own values, so neither "
            "is 1. Each U0126 value is placed against the untreated values and against the DMSO "
            "value separately; they are not pooled. 'below_each' and 'above_each' mean below or "
            "above every reference value of that kind. Single recorded values (one or two per "
            "dose); no mean, rescaling or test."
        ),
        "source": "../extracted.json (from msb201127-df6B.txt)",
        "lines": {},
    }
    repeated = {
        r["line"]
        for s in e["fig6B"]["by_cell_line"].values()
        for r in s["control_rows_repeated_verbatim"]
    }
    for cell in sorted({r["cell_line"] for r in rows}):
        mine = [r for r in rows if r["cell_line"] == cell and r["line"] not in repeated]
        untreated = [r for r in mine if r["agent"] == "--"]
        dmso = [r for r in mine if r["agent"] == "DMSO"]
        pbs = [r for r in mine if r["agent"].lower() == "pbs"]
        u_vals = [float(r["value"]) for r in untreated]
        d_vals = [float(r["value"]) for r in dmso]
        out["lines"][cell] = {
            "normalisation_reference": {
                "agent": "PBS",
                "value": pbs[0]["value"],
                "line": pbs[0]["line"],
            },
            "untreated": [{"value": r["value"], "line": r["line"]} for r in untreated],
            "DMSO": [{"value": r["value"], "line": r["line"]} for r in dmso],
            "U0126": [
                {
                    "concentration_uM": r["concentration_uM"],
                    "value_vs_PBS": r["value"],
                    "line": r["line"],
                    "vs_untreated_values": _against(float(r["value"]), u_vals),
                    "vs_DMSO_value": _against(float(r["value"]), d_vals),
                }
                for r in mine
                if r["agent"] == "U0126"
            ],
        }
    return out


def main() -> None:
    (HERE / "baselines.json").write_text(
        json.dumps(build(), indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
