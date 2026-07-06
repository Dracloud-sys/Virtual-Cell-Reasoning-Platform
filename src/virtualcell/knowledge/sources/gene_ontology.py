"""Gene Ontology (GO) connector (skeleton).

Will ingest GO terms and gene-term annotations. Implementation lands in a
subsequent release; the interface matches ``DataSource``.
"""

from __future__ import annotations

from collections.abc import Iterator

from virtualcell.knowledge.schema import BioEntity, Interaction


class GeneOntologySource:
    name = "gene_ontology"

    def __init__(self, path: str | None = None) -> None:
        self._path = path

    def entities(self) -> Iterator[BioEntity]:  # pragma: no cover
        raise NotImplementedError("Gene Ontology ingestion lands in a subsequent release")
        yield  # pragma: no cover

    def interactions(self) -> Iterator[Interaction]:  # pragma: no cover
        raise NotImplementedError("Gene Ontology ingestion lands in a subsequent release")
        yield  # pragma: no cover
