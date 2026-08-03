"""Verbatim tabular readers: CSV and TSV (PR13b), XLSX (PR13b-2).

The reader's whole job is to *not* interpret. It produces text and positions; every
decision about what that text means happens later, where it can be traced to a declared
rule. That separation is what makes an import auditable: if a value is wrong, it is either
in the file or introduced by a named rule, never by a reader guessing.

Every format converges on :func:`build_table`, so the guarantees a header row must satisfy
are stated once and hold for all of them. A format-specific reader's only job is to turn
its container into rows of text.

Deliberately not here: type sniffing, header normalization, encoding detection, blank-row
skipping heuristics, and any vendor/binary assay format (**PR15+**).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from virtualcell.ingestion.contracts import CellLocator, RawCell, RawTable, SourceFormat

_DELIMITER: dict[SourceFormat, str] = {SourceFormat.CSV: ",", SourceFormat.TSV: "\t"}

# UTF-8 with a BOM is what Excel writes on Windows, which is where most of these files come
# from. ``utf-8-sig`` reads both, and strips the BOM so the first header is not "﻿id".
ENCODING = "utf-8-sig"


class ReaderError(ValueError):
    """Raised when a source cannot be read as the declared tabular format."""


def build_table(rows: list[list[str]], *, source_name: str) -> RawTable:
    """Assemble a :class:`RawTable` from rows of text, enforcing the header contract.

    The single place every format's header row is validated, so CSV, TSV and XLSX cannot
    drift into accepting different files.

    Cells are stripped of surrounding whitespace and nothing else: leading/trailing spaces
    are a transport artifact, while the content between them is the datum. Short rows are
    padded and long rows are refused — a row with more fields than headers means the file
    is not what the spec says it is, and quietly dropping the extra would hide that.

    **Headers must be unique and non-empty**, checked *after* stripping so ``id`` and
    ``id `` are caught. Everything downstream identifies a column by its header —
    :class:`CellLocator` carries nothing else — so two columns sharing one cannot be told
    apart: one identifier would silently overwrite the other and lose a row's identity,
    and two same-named measurements would be indistinguishable from the declared replicates
    the canonical multiset is meant to preserve. Neither is something a reader may decide;
    both are questions for whoever produced the file.
    """
    if not rows:
        return RawTable(source_name=source_name)

    headers = [cell.strip() for cell in rows[0]]
    if not any(headers):
        raise ReaderError(f"{source_name}: the first line is empty; expected a header row")

    blank = [index for index, header in enumerate(headers) if not header]
    if blank:
        raise ReaderError(
            f"{source_name}: header column(s) {', '.join(str(i) for i in blank)} are empty; "
            "a column with no name cannot be declared in a spec or named in a locator"
        )

    duplicates = sorted({header for header in headers if headers.count(header) > 1})
    if duplicates:
        raise ReaderError(
            f"{source_name}: duplicate header(s) {', '.join(repr(h) for h in duplicates)}; "
            "a column is identified by its header everywhere downstream, so two columns "
            "sharing one cannot be told apart — one identifier would silently overwrite the "
            "other, and two same-named measurements would be indistinguishable from "
            "declared replicates"
        )

    data: list[list[str]] = []
    for index, row in enumerate(rows[1:]):
        cells = [cell.strip() for cell in row]
        if not any(cells):
            continue  # a wholly blank line carries no cell, not even a missing one
        if len(cells) > len(headers):
            raise ReaderError(
                f"{source_name}: data row {index} has {len(cells)} fields but the header "
                f"declares {len(headers)}; refusing to guess which are extra"
            )
        cells.extend([""] * (len(headers) - len(cells)))
        data.append(cells)

    return RawTable(source_name=source_name, headers=headers, rows=data)


def read_delimited(text: str, *, source_name: str, source_format: SourceFormat) -> RawTable:
    """Read delimited text into a :class:`RawTable`, verbatim. See :func:`build_table`."""
    delimiter = _DELIMITER.get(source_format)
    if delimiter is None:
        raise ReaderError(f"{source_format.value} is not a delimited format")
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    return build_table(rows, source_name=source_name)


def read_path(
    path: str | Path, *, source_format: SourceFormat, sheet: str | None = None
) -> RawTable:
    """Read a file into a :class:`RawTable`. Encoding is fixed, never sniffed."""
    file_path = Path(path)
    if source_format is SourceFormat.XLSX:
        from virtualcell.ingestion.xlsx import read_workbook

        return read_workbook(file_path, sheet=sheet)

    try:
        text = file_path.read_text(encoding=ENCODING)
    except OSError as exc:
        raise ReaderError(f"cannot read {file_path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ReaderError(
            f"cannot decode {file_path} as {ENCODING}; convert it rather than letting a "
            f"reader guess an encoding: {exc}"
        ) from exc
    return read_delimited(text, source_name=file_path.name, source_format=source_format)


def cells_of(table: RawTable, row_index: int) -> list[RawCell]:
    """The located cells of one data row, in header order."""
    return [
        RawCell(
            locator=CellLocator(
                source_name=table.source_name, row_index=row_index, column_header=header
            ),
            text=value,
        )
        for header, value in zip(table.headers, table.rows[row_index], strict=True)
    ]
