"""Reactome pathway connector.

Ingests Reactome's ``UniProt2Reactome`` mapping file — a tab-separated export of
protein-to-pathway participation — into the knowledge base. Download the current
release from::

    https://reactome.org/download/current/UniProt2Reactome.txt

Each line has six tab-separated columns::

    UniProtID  ReactomePathwayStableID  URL  PathwayName  EvidenceCode  Species

From every (species-matching) row this connector produces a :class:`Protein`
entity, a :class:`Pathway` entity, and a ``PARTICIPATES_IN`` interaction between
them. Proteins are skeletal here (only the accession is known); a UniProt
connector can later upsert richer records over the same ``protein:<accession>``
id.
"""

from __future__ import annotations

from collections.abc import Iterator

from virtualcell.knowledge.schema import (
    BioEntity,
    Interaction,
    Pathway,
    Protein,
    RelationType,
)

# Column indices in the UniProt2Reactome file.
_COL_UNIPROT = 0
_COL_PATHWAY = 1
_COL_PATHWAY_NAME = 3
_COL_EVIDENCE = 4
_COL_SPECIES = 5
_MIN_COLUMNS = 6


class ReactomeSource:
    """A DataSource over a Reactome ``UniProt2Reactome`` export.

    ``species`` filters rows by the file's species column (default human). Set it
    to ``None`` to ingest every species.
    """

    name = "reactome"

    def __init__(self, path: str | None = None, species: str | None = "Homo sapiens") -> None:
        self._path = path
        self._species = species

    def _rows(self) -> Iterator[tuple[str, str, str, str]]:
        """Yield ``(uniprot_id, pathway_id, pathway_name, evidence_code)`` per valid row."""
        if not self._path:
            raise ValueError("ReactomeSource requires a path to a UniProt2Reactome file")
        with open(self._path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\r\n")
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < _MIN_COLUMNS:
                    continue  # malformed / truncated line
                if self._species is not None and parts[_COL_SPECIES] != self._species:
                    continue
                uniprot_id = parts[_COL_UNIPROT].strip()
                pathway_id = parts[_COL_PATHWAY].strip()
                if not uniprot_id or not pathway_id:
                    continue
                yield uniprot_id, pathway_id, parts[_COL_PATHWAY_NAME], parts[_COL_EVIDENCE]

    def entities(self) -> Iterator[BioEntity]:
        seen_proteins: set[str] = set()
        seen_pathways: set[str] = set()
        for uniprot_id, pathway_id, pathway_name, _evidence in self._rows():
            protein_id = f"protein:{uniprot_id}"
            if protein_id not in seen_proteins:
                seen_proteins.add(protein_id)
                yield Protein(
                    id=protein_id,
                    name=uniprot_id,
                    uniprot_id=uniprot_id,
                    properties={"source": self.name},
                )
            pathway_key = f"pathway:{pathway_id}"
            if pathway_key not in seen_pathways:
                seen_pathways.add(pathway_key)
                yield Pathway(
                    id=pathway_key,
                    name=pathway_name,
                    source="Reactome",
                    properties={"source": self.name},
                )

    def interactions(self) -> Iterator[Interaction]:
        seen: set[tuple[str, str]] = set()
        for uniprot_id, pathway_id, _name, evidence_code in self._rows():
            edge = (uniprot_id, pathway_id)
            if edge in seen:
                continue
            seen.add(edge)
            yield Interaction(
                source_id=f"protein:{uniprot_id}",
                target_id=f"pathway:{pathway_id}",
                relation=RelationType.PARTICIPATES_IN,
                evidence=[f"reactome:{evidence_code}" if evidence_code else "reactome"],
            )
