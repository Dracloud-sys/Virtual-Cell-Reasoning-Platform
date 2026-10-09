"""Copy the rows of Fritsche-Guenther et al. 2011, Fig 4B source data, with their line numbers.

The file is the authors' "Source Data for Figure 4B" text file in the PMC open-access package of
PMC3130559 (CC BY-NC-SA 3.0). It is not stored in this repository. The script reads it from a
cache directory outside the repository, checks the md5 the package manifest gives, and writes
`extracted.json`: every line as written, and the data rows split into their cells. Nothing is
averaged, renormalised or tested.

    python extract.py --cache DIR
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "msb201127-df4B.txt"
# From s3://pmc-oa-opendata/PMC3130559.1/PMC3130559.1.json, media_urls (fetched 2026-10-08).
MANIFEST_MD5 = "5b20422c6124264857d86eee1aad931f"


def read(cache: Path) -> tuple[bytes, list[str]]:
    data = (cache / NAME).read_bytes()
    if hashlib.md5(data).hexdigest() != MANIFEST_MD5:  # noqa: S324 - the manifest's own checksum
        raise SystemExit(f"{NAME}: md5 differs from the package manifest")
    return data, data.decode("utf-8").splitlines()


def extract(data: bytes, lines: list[str]) -> dict:
    header = [line.rstrip("\r") for line in lines[:3]]
    rows = []
    for number, line in enumerate(lines, start=1):
        if number <= 3:
            continue
        cell_line, treatment, value, sd = (c.strip() for c in line.rstrip("\r").split("\t"))
        rows.append(
            {
                "line": number,
                "cell_line": cell_line,
                "treatment": treatment,
                "value": value,
                "sd": sd,
            }
        )
    return {
        "file": NAME,
        "md5": hashlib.md5(data).hexdigest(),  # noqa: S324
        "sha256": hashlib.sha256(data).hexdigest(),
        "header_lines": {str(i + 1): h for i, h in enumerate(header)},
        "rows": rows,
        "values_as": "strings copied from the file; the column header gives them as mean "
        "normalised integrated density (normalisation to DMSO control) and standard deviation",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    data, lines = read(args.cache)
    (HERE / "extracted.json").write_text(
        json.dumps(extract(data, lines), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
