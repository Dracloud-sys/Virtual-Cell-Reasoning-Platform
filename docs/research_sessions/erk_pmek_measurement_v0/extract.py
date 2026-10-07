"""Extract the pMek values of Fritsche-Guenther et al. 2011, Fig 6B and 6C, from the authors'
source data files, keeping every value's file, line and original string.

The files are the authors' "Raw data of Figure 6B" and "Raw data for Figure 6C" text files in
the PMC open-access package of PMC3130559 (CC BY-NC-SA 3.0). They are not stored in this
repository. The script downloads them into a cache directory outside it (or reads them from
there), checks the md5 the package manifest gives, and writes `extracted.json`: the values as
the authors give them (normalised, as their headers say), with no unit change, averaging or
rescaling. Fig 6D has no source data file in the package and is not extracted here.

    python extract.py [--cache DIR] [--offline]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = "https://pmc-oa-opendata.s3.amazonaws.com/PMC3130559.1/"
FILES = {
    # name: md5 from s3://pmc-oa-opendata/PMC3130559.1/PMC3130559.1.json (media_urls)
    "msb201127-df6B.txt": "ecff68be1f1d494db058e3b2c4da1a74",
    "msb201127-df6C.txt": "61e0dfc1b367d6eda897b03d638d5faa",
}


def fetch(cache: Path, offline: bool) -> dict[str, list[str]]:
    cache.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, md5 in FILES.items():
        path = cache / name
        if not path.exists():
            if offline:
                raise SystemExit(f"{name} is not in {cache} and --offline was given")
            with urllib.request.urlopen(BASE + name, timeout=60) as response:  # noqa: S310
                path.write_bytes(response.read())
        data = path.read_bytes()
        if hashlib.md5(data).hexdigest() != md5:  # noqa: S324 - the manifest's own checksum
            raise SystemExit(f"{name}: md5 differs from the package manifest")
        out[name] = data.decode("utf-8").splitlines()
    return out


def parse_6b(lines: list[str]) -> dict:
    rows = []
    for number, line in enumerate(lines, start=1):
        cells = line.split("\t")
        if number <= 3:
            continue
        cell, agent, conc, value = (c.strip() for c in cells)
        rows.append(
            {
                "line": number,
                "cell_line": cell,
                "agent": agent,
                "concentration_uM": conc,
                "value": value,
            }
        )
    by_line: dict[str, list[dict]] = {}
    for r in rows:
        by_line.setdefault(r["cell_line"], []).append(r)
    summary = {}
    for cell, items in by_line.items():
        seen: dict[tuple, int] = {}
        repeated = []
        for r in items:
            key = (r["agent"], r["value"])
            if r["agent"] in ("--", "DMSO") and key in seen:
                repeated.append({"line": r["line"], "repeats_line": seen[key]})
            seen.setdefault(key, r["line"])
        controls = {
            "untreated": [
                r["value"]
                for r in items
                if r["agent"] == "--" and r["line"] not in {x["line"] for x in repeated}
            ],
            "DMSO": [
                r["value"]
                for r in items
                if r["agent"] == "DMSO" and r["line"] not in {x["line"] for x in repeated}
            ],
            "PBS (reference, defined as 1)": [
                r["value"] for r in items if r["agent"].lower() == "pbs"
            ],
        }
        u0126: dict[str, list[str]] = {}
        for r in items:
            if r["agent"] == "U0126":
                u0126.setdefault(r["concentration_uM"], []).append(r["value"])
        summary[cell] = {
            "controls": controls,
            "U0126_by_concentration_uM": u0126,
            "values_per_U0126_concentration": {k: len(v) for k, v in u0126.items()},
            "control_rows_repeated_verbatim": repeated,
        }
    return {
        "header": lines[0].strip(),
        "column_labels": [lines[1].strip().split("\t"), lines[2].strip().split("\t")],
        "rows": rows,
        "by_cell_line": summary,
    }


def parse_6c(lines: list[str]) -> dict:
    columns = lines[1].strip().split("\t")
    rows = []
    for number, line in enumerate(lines, start=1):
        if number <= 3 or not line.strip():
            continue
        t, *values = (c.strip() for c in line.split("\t"))
        rows.append({"line": number, "time_min": t, **dict(zip(columns[1:], values, strict=True))})
    return {
        "header": lines[0].strip(),
        "column_labels": [columns, lines[2].strip().split("\t")],
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache", type=Path, default=Path(tempfile.gettempdir()) / "erk_pmek_source"
    )
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    lines = fetch(args.cache, args.offline)
    out = {
        "about": (
            "Values as given in the authors' source data files for Fig 6B and 6C of "
            "Fritsche-Guenther et al. 2011 (doi 10.1038/msb.2011.27; PMC3130559; CC BY-NC-SA "
            "3.0), with file and line. Strings are copied, not converted. The authors call the "
            "files raw data; their own headers say the values are normalised (6B: relative to "
            "PBS-treated cells; 6C: to one 0-timepoint), so they are level B (author-processed), "
            "not raw instrument readings."
        ),
        "source": {name: {"url": BASE + name, "md5": md5} for name, md5 in FILES.items()},
        "fig6B": parse_6b(lines["msb201127-df6B.txt"]),
        "fig6C": parse_6c(lines["msb201127-df6C.txt"]),
    }
    (HERE / "extracted.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: len(out[k]["rows"]) for k in ("fig6B", "fig6C")}))


if __name__ == "__main__":
    main()
