"""IntAct protein-protein interaction connector.

Ingests physical protein-protein interactions from an IntAct MITAB 2.5 export as
symmetric ``INTERACTS_WITH`` edges. Download from::

    https://ftp.ebi.ac.uk/pub/databases/intact/current/psimitab/

This is an *edge-only* source: it yields no entities, so it should be merged onto
a graph that already holds the referenced proteins (e.g. after a UniProt ingest).
Interactions whose endpoints are absent are skipped by ``load_into``.

MITAB is tab-separated; this connector reads three columns:

* col 0 / 1 — interactor A / B ids, e.g. ``uniprotkb:P04637`` (isoform suffixes
  like ``-1`` are collapsed to the canonical accession);
* col 14 — confidence, e.g. ``intact-miscore:0.56``.

Rows whose interactors are not both UniProt proteins, and self-interactions, are
skipped.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from virtualcell.knowledge.schema import BioEntity, Interaction, RelationType

_COL_A = 0
_COL_B = 1
_COL_SCORE = 14
_MIN_COLUMNS = 15

_UNIPROT_RE = re.compile(r"uniprotkb:([A-Za-z0-9]+)")
_MISCORE_RE = re.compile(r"intact-miscore:([0-9.]+)")


class IntActSource:
    """A DataSource over an IntAct MITAB 2.5 export (protein-protein interactions)."""

    name = "intact"

    def __init__(self, path: str | None = None, min_score: float = 0.0) -> None:
        self._path = path
        self._min_score = min_score

    def _rows(self) -> Iterator[tuple[str, str, float]]:
        """Yield ``(accession_a, accession_b, score)`` for valid protein pairs."""
        if not self._path:
            raise ValueError("IntActSource requires a path to an IntAct MITAB file")
        with open(self._path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\r\n")
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < _MIN_COLUMNS:
                    continue
                a = _UNIPROT_RE.search(parts[_COL_A])
                b = _UNIPROT_RE.search(parts[_COL_B])
                if a is None or b is None:  # not a UniProt-UniProt pair
                    continue
                acc_a, acc_b = a.group(1), b.group(1)
                if acc_a == acc_b:  # skip self-interactions
                    continue
                score_match = _MISCORE_RE.search(parts[_COL_SCORE])
                score = float(score_match.group(1)) if score_match else 0.5
                if score < self._min_score:
                    continue
                yield acc_a, acc_b, score

    def entities(self) -> Iterator[BioEntity]:
        return iter(())  # edge-only source: relies on proteins already in the graph

    def interactions(self) -> Iterator[Interaction]:
        seen: set[frozenset[str]] = set()
        for acc_a, acc_b, score in self._rows():
            pair = frozenset({acc_a, acc_b})
            if pair in seen:
                continue
            seen.add(pair)
            yield Interaction(
                source_id=f"protein:{acc_a}",
                target_id=f"protein:{acc_b}",
                relation=RelationType.INTERACTS_WITH,
                confidence=score,
                evidence=["intact"],
            )
