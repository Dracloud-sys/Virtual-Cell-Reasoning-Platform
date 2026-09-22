"""Rebuild ``assay_hits.json`` from locally fetched abstracts.

Separate from ``tally.py`` for one reason: **abstracts are not committed.** They are
publisher-copyrighted, so redistributing fifty of them in this repository is not something
a survey needs to do. What is committed is the derived hit matrix plus the patterns that
produced it, which is enough for a reader to check any classification and enough for anyone
to reproduce the whole thing from the PMIDs.

Usage — fetch the corpus yourself, then:

    python build_hits.py /path/to/corpus.json

where ``corpus.json`` is a list of ``{pmid, doi, year, title, abstract, keywords}``. The
PMIDs are listed in ``assay_hits.json`` and the search that produced them is in the README,
so a refresh is a re-run rather than a rediscovery.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

from assay_classes import PATTERNS

HERE = Path(__file__).parent
OUT = HERE / "assay_hits.json"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    corpus = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    existing = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}

    papers = []
    for art in corpus:
        blob = " ".join(
            [art.get("title", ""), art.get("abstract", ""), " ".join(art.get("keywords", []))]
        )
        papers.append(
            {
                "pmid": art["pmid"],
                "doi": art.get("doi", ""),
                "year": art.get("year", ""),
                "title": art.get("title", ""),
                "hits": [
                    name
                    for name, pattern in PATTERNS.items()
                    if re.search(pattern, blob, re.IGNORECASE)
                ],
            }
        )
    papers.sort(key=lambda p: p["pmid"])

    payload = {
        "source": existing.get("source", {}),
        "generated": date.today().isoformat(),
        "unit": "title + abstract + author keywords",
        "papers": papers,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(papers)} papers)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
