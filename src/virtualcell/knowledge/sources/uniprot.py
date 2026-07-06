"""UniProt protein connector.

Ingests a UniProtKB TSV export into the knowledge base. Download a reviewed
(Swiss-Prot) human set from the UniProt REST API::

    https://rest.uniprot.org/uniprotkb/stream?query=reviewed:true+AND+organism_id:9606&format=tsv&fields=accession,id,protein_name,gene_primary,organism_name

The TSV has a header row and these five columns::

    Entry  Entry Name  Protein names  Gene Names (primary)  Organism

Each row yields a rich :class:`Protein` entity — enriching any skeletal protein
already ingested from Reactome under the same ``protein:<accession>`` id — and,
when a primary gene is present, a :class:`Gene` entity plus a ``gene ENCODES
protein`` interaction.
"""

from __future__ import annotations

from collections.abc import Iterator

from virtualcell.knowledge.schema import (
    BioEntity,
    Gene,
    Interaction,
    Protein,
    RelationType,
)

# Column indices in the UniProtKB TSV export (fields as documented above).
_COL_ACCESSION = 0
_COL_ENTRY_NAME = 1
_COL_PROTEIN_NAME = 2
_COL_GENE = 3
_COL_ORGANISM = 4
_MIN_COLUMNS = 5


class UniProtSource:
    """A DataSource over a UniProtKB TSV export.

    ``species`` filters rows by substring against the file's Organism column (which
    reads e.g. ``Homo sapiens (Human)``); ``None`` ingests every organism, relying
    on the download query to scope them. ``has_header`` skips the leading header
    line that UniProt TSV exports always include.
    """

    name = "uniprot"

    def __init__(
        self,
        path: str | None = None,
        species: str | None = None,
        has_header: bool = True,
    ) -> None:
        self._path = path
        self._species = species
        self._has_header = has_header

    def _rows(self) -> Iterator[tuple[str, str, str, str, str]]:
        """Yield ``(accession, entry_name, protein_name, gene, organism)`` per valid row."""
        if not self._path:
            raise ValueError("UniProtSource requires a path to a UniProtKB TSV export")
        with open(self._path, encoding="utf-8") as fh:
            for index, raw in enumerate(fh):
                if self._has_header and index == 0:
                    continue
                line = raw.rstrip("\r\n")
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < _MIN_COLUMNS:
                    continue  # malformed / truncated line
                organism = parts[_COL_ORGANISM].strip()
                if self._species is not None and self._species not in organism:
                    continue
                accession = parts[_COL_ACCESSION].strip()
                if not accession:
                    continue
                yield (
                    accession,
                    parts[_COL_ENTRY_NAME].strip(),
                    parts[_COL_PROTEIN_NAME].strip(),
                    parts[_COL_GENE].strip(),
                    organism,
                )

    def entities(self) -> Iterator[BioEntity]:
        seen_proteins: set[str] = set()
        seen_genes: set[str] = set()
        for accession, entry_name, protein_name, gene, organism in self._rows():
            protein_id = f"protein:{accession}"
            if protein_id not in seen_proteins:
                seen_proteins.add(protein_id)
                yield Protein(
                    id=protein_id,
                    name=protein_name or accession,
                    uniprot_id=accession,
                    aliases=[a for a in (entry_name, gene) if a],
                    properties={"source": self.name},
                )
            if gene:
                gene_id = f"gene:{gene}"
                if gene_id not in seen_genes:
                    seen_genes.add(gene_id)
                    yield Gene(
                        id=gene_id,
                        name=gene,
                        symbol=gene,
                        organism=organism or None,
                        properties={"source": self.name},
                    )

    def interactions(self) -> Iterator[Interaction]:
        seen: set[tuple[str, str]] = set()
        for accession, _entry_name, _protein_name, gene, _organism in self._rows():
            if not gene:
                continue
            edge = (gene, accession)
            if edge in seen:
                continue
            seen.add(edge)
            yield Interaction(
                source_id=f"gene:{gene}",
                target_id=f"protein:{accession}",
                relation=RelationType.ENCODES,
                evidence=["uniprot"],
            )
