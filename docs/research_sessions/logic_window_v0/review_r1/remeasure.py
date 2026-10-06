"""Re-run `../measure_erk.py` after review r1, writing here; compare with the first record.

`../measure.json` and `../window_results.json` (recorded at 8ebb303) are not rewritten. This
runs the same measurement code with its output directory set to this folder, then checks that
every class, group, pairing and direction set of the 16 ERK targets is the same as recorded.

    python remeasure.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = HERE.parent


def main() -> None:
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("measure_erk", CASE / "measure_erk.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HERE = HERE
    module.main()
    before = json.loads((CASE / "window_results.json").read_text(encoding="utf-8"))
    after = json.loads((HERE / "window_results.json").read_text(encoding="utf-8"))
    rows = {}
    for key in sorted(before):
        a, b = before[key]["window"], after[key]["window"]
        rows[key] = {
            "run_sha256_same": before[key]["run_sha256"] == after[key]["run_sha256"],
            "cases_same": a["cases"] == b["cases"],
            "pairing_same": a["pairing"] == b["pairing"],
            "targets_same": a["targets"] == b["targets"],
            "request_sha256_same": a["request_sha256"] == b["request_sha256"],
        }
    out = {"rows": rows, "all_same": all(all(r.values()) for r in rows.values())}
    (HERE / "compare.json").write_text(
        json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(out["all_same"]))


if __name__ == "__main__":
    main()
