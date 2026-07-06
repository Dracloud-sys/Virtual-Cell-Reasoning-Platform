"""Reactome pathway connector (skeleton).

Will ingest pathways and protein-pathway participation. Implementation lands in a
subsequent release; the interface matches ``DataSource``.
"""

from __future__ import annotations

from collections.abc import Iterator

from virtualcell.knowledge.schema import BioEntity, Interaction


class ReactomeSource:
    name = "reactome"

    def __init__(self, path: str | None = None) -> None:
        self._path = path

    def entities(self) -> Iterator[BioEntity]:  # pragma: no cover
        raise NotImplementedError("Reactome ingestion lands in a subsequent release")
        yield  # pragma: no cover

    def interactions(self) -> Iterator[Interaction]:  # pragma: no cover
        raise NotImplementedError("Reactome ingestion lands in a subsequent release")
        yield  # pragma: no cover
