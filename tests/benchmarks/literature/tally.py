"""What evidence does the literature actually offer when it claims an immortalized line?

Runs offline over the committed hit matrix. No network, no abstracts on disk needed.

This exists because a single paper cannot answer the question it is asked to answer. The
external evaluation scored the platform case by case, and each case was bounded by whatever
that one paper happened to measure — so when every case stalled on a missing marker, "the
platform requires something papers do not report" was a guess with n=1 behind it, repeated
five times. The question is distributional: *across* the field, what do authors present?

That is what this tallies, and the answer is evidence a person can use to decide whether
the platform's required panel is well-founded. It is not a rule, and nothing here changes
behaviour: picking what a positive call should require is a biological and editorial
judgement, which this repository treats as a stop condition for an unattended change.

Run ``python tally.py`` from this directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from assay_classes import GATE_CLASSES, PATTERNS

HITS = Path(__file__).parent / "assay_hits.json"


def main() -> int:
    data = json.loads(HITS.read_text(encoding="utf-8"))
    papers = data["papers"]
    total = len(papers)
    source = data.get("source", {})

    counts = {name: sum(1 for p in papers if name in p["hits"]) for name in PATTERNS}

    print("Evidence offered for establishing an immortalized line")
    print(f"Corpus: {total} papers, unit = {data['unit']}")
    if source:
        print(f"Search: {source.get('query', '?')}")
        print(
            f"        PubMed, {source.get('retrieved', '?')}, "
            f"{source.get('returned', '?')} of {source.get('total_hits', '?')} hits by relevance"
        )
    print()

    width = max(len(n) for n in PATTERNS)
    print(f"{'evidence class':<{width}}  papers  share")
    print("-" * (width + 16))
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"{name:<{width}}  {n:>6}  {n / total:>5.0%}")

    print(f"\nThe platform's positive-call gate ({'; '.join(GATE_CLASSES)})")
    print("is a conjunction — all three must hold before `possible_candidate` is reachable:")
    for name in GATE_CLASSES:
        print(f"  {name:<32} {counts[name]:>2}/{total} ({counts[name] / total:>4.0%})")

    both = [p["pmid"] for p in papers if all(g in p["hits"] for g in GATE_CLASSES)]
    print(f"\nPapers satisfying all three at once: {len(both)}/{total} ({len(both) / total:.0%})")
    if both:
        print("  " + ", ".join(both))

    print(
        "\nAbstract-level reporting is a LOWER BOUND on assays performed; methods sections"
        "\ncarry more. It is arguably the right unit for this question even so: a gate decides"
        "\nwhat is sufficient to call something a candidate, and what an author puts in the"
        "\nabstract is what that author considered sufficient to claim it. A class at 0% is 0%"
        "\neither way."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
