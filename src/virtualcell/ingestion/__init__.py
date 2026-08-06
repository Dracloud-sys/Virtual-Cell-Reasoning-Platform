"""Declared tabular ingestion, QC and normalization (PR13b).

Turns a raw CSV/TSV export into canonical :class:`~virtualcell.core.experiment.ExperimentRun`
objects, under a *declared* :class:`~virtualcell.ingestion.contracts.DatasetSpec` rather
than by inferring what its columns mean:

    file -> RawTable -> ParsedCell candidates -> QCDecision -> ExperimentRun

The three layers are the literature pipeline's, for the same reason: a proposal, a
decision, and a conversion are different acts, and merging any two of them is how a parse
failure quietly becomes an observation.

Scope: CSV, TSV and XLSX. The spreadsheet reader (PR13b-2) sits behind the same
``DatasetSpec`` and the same header contract, and needs the optional ``virtualcell[xlsx]``
extra. qPCR Ct, FCS, imaging and omics readers are PR15+, once a second domain pack has
shown the QC boundary generalizes. Free-form column mapping remains deliberately out of
scope.
"""

from virtualcell.ingestion.canonical import ingest_table
from virtualcell.ingestion.contracts import (
    ColumnRole,
    ColumnSpec,
    DatasetSpec,
    IngestionStatus,
    QCDecision,
    QCReport,
    QCRule,
    SourceFormat,
    TabularIngestionResult,
    TimeAxisKind,
)
from virtualcell.ingestion.readers import ReaderError, read_delimited, read_path

__all__ = [
    "ColumnRole",
    "ColumnSpec",
    "DatasetSpec",
    "IngestionStatus",
    "QCDecision",
    "QCReport",
    "QCRule",
    "ReaderError",
    "SourceFormat",
    "TabularIngestionResult",
    "TimeAxisKind",
    "ingest_file",
    "ingest_table",
    "read_delimited",
    "read_path",
]


def ingest_file(path, spec: DatasetSpec) -> TabularIngestionResult:
    """Read a file under ``spec`` and convert it to canonical runs.

    An unreadable source is reported as a typed status rather than raised, so one bad file
    in a batch cannot abort the rest — the same rule the literature run status follows.
    """
    try:
        table = read_path(path, source_format=spec.source_format, sheet=spec.sheet)
    except ReaderError as exc:
        return TabularIngestionResult(
            status=IngestionStatus.UNREADABLE_SOURCE,
            spec_version=spec.spec_version,
            source_name=str(path),
            errors=[str(exc)],
        )
    return ingest_table(table, spec)
