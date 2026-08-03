"""Turn located cells into typed candidates (PR13b).

This layer answers one question per cell: *under the type this column declares, what does
this text contain?* It never answers "is this datum any good" — that is
:mod:`virtualcell.ingestion.qc`, and keeping the two apart is what stops a parse failure
from being quietly reinterpreted as a biological observation.

Numbers go through the platform's one value grammar
(:func:`virtualcell.core.values.parse_value_text`), so a CSV cell and a table cell in a
paper are read with the same conservative rules: ``1,234`` is refused rather than guessed,
``<0.05`` keeps its comparator, and qualitative text never gains a number.
"""

from __future__ import annotations

from datetime import datetime

from virtualcell.core.experiment import MeasurementValueType
from virtualcell.core.values import ParseStatus, parse_value_text
from virtualcell.ingestion.contracts import (
    CellLocator,
    ColumnRole,
    ColumnSpec,
    DatasetSpec,
    ParsedCell,
    RawCell,
    TimeAxisKind,
)

# A fixed, declared boolean vocabulary. Deliberately small and case-insensitive: anything
# outside it is a parse failure a human can see, not a value coerced to False.
_TRUE_TOKENS = frozenset({"true", "yes", "y", "1"})
_FALSE_TOKENS = frozenset({"false", "no", "n", "0"})


def _unparsed(cell: RawCell, column: ColumnSpec, note: str) -> ParsedCell:
    return ParsedCell(
        locator=cell.locator,
        column=column.canonical_name,
        role=column.role,
        raw_text=cell.text,
        value_type=column.value_type,
        parse_note=note,
    )


def _parse_numeric(cell: RawCell, column: ColumnSpec) -> ParsedCell:
    # ``strict``: a declared numeric column claims the *whole* field is the value, so
    # "abc24xyz" and "24 (n=3)" are refused rather than yielding 24. Deciding which part
    # of a cell was the datum is the reader interpreting, which is what this layer is for
    # avoiding.
    parsed = parse_value_text(cell.text, strict=True)
    if parsed.parse_status is not ParseStatus.PARSED or parsed.parsed_value is None:
        return _unparsed(
            cell,
            column,
            f"{cell.text!r} is not a value in full under the platform grammar; a cell "
            "that merely contains a number is not a reading",
        )
    return ParsedCell(
        locator=cell.locator,
        column=column.canonical_name,
        role=column.role,
        raw_text=cell.text,
        value=parsed.parsed_value,
        value_type=MeasurementValueType.NUMERIC,
        unit=parsed.unit,
        comparator=parsed.comparator,
        uncertainty=parsed.uncertainty,
        parse_status=ParseStatus.PARSED,
    )


def _parse_boolean(cell: RawCell, column: ColumnSpec) -> ParsedCell:
    token = cell.text.strip().casefold()
    if token in _TRUE_TOKENS or token in _FALSE_TOKENS:
        return ParsedCell(
            locator=cell.locator,
            column=column.canonical_name,
            role=column.role,
            raw_text=cell.text,
            value=token in _TRUE_TOKENS,
            value_type=MeasurementValueType.BOOLEAN,
            parse_status=ParseStatus.PARSED,
        )
    return _unparsed(
        cell,
        column,
        f"{cell.text!r} is not one of the declared boolean tokens "
        f"({', '.join(sorted(_TRUE_TOKENS | _FALSE_TOKENS))})",
    )


def _parse_categorical(cell: RawCell, column: ColumnSpec) -> ParsedCell:
    return ParsedCell(
        locator=cell.locator,
        column=column.canonical_name,
        role=column.role,
        raw_text=cell.text,
        value=cell.text.strip(),
        value_type=MeasurementValueType.CATEGORICAL,
        parse_status=ParseStatus.PARSED,
    )


_BY_TYPE = {
    MeasurementValueType.NUMERIC: _parse_numeric,
    MeasurementValueType.BOOLEAN: _parse_boolean,
    MeasurementValueType.CATEGORICAL: _parse_categorical,
}


def _parse_time_axis(cell: RawCell, column: ColumnSpec) -> ParsedCell:
    """Parse a time-axis cell into the value its declared axis needs.

    Passage counts and simulation steps are whole counts, so ``P3.5`` is refused rather
    than truncated; a timestamp must be ISO 8601 *and* carry an offset, because a naive
    stamp is ambiguous across sites and instruments.
    """
    if column.time_axis is TimeAxisKind.TIMESTAMP:
        try:
            stamp = datetime.fromisoformat(cell.text.strip())
        except ValueError:
            return _unparsed(cell, column, f"{cell.text!r} is not an ISO 8601 timestamp")
        if stamp.tzinfo is None or stamp.tzinfo.utcoffset(stamp) is None:
            # A declared offset is applied only here, to a stamp that carries none of its
            # own: a stamp that states its zone is authoritative over the spec, because it
            # describes the reading while the spec describes the file.
            if column.timestamp_offset is None:
                return _unparsed(
                    cell,
                    column,
                    f"timestamp {cell.text!r} has no UTC offset; a naive stamp is ambiguous "
                    "across sites and instruments. Declare 'timestamp_offset' on the column "
                    "if the source records times in a known zone (an xlsx workbook always "
                    "does, since the format stores no timezone)",
                )
            try:
                stamp = datetime.fromisoformat(f"{stamp.isoformat()}{column.timestamp_offset}")
            except ValueError:
                return _unparsed(
                    cell, column, f"{cell.text!r} could not take the declared UTC offset"
                )
        return ParsedCell(
            locator=cell.locator,
            column=column.canonical_name,
            role=column.role,
            raw_text=cell.text,
            value=stamp.isoformat(),
            value_type=MeasurementValueType.CATEGORICAL,
            parse_status=ParseStatus.PARSED,
        )

    parsed = _parse_numeric(cell, column)
    if parsed.parse_status is not ParseStatus.PARSED:
        return parsed
    if parsed.comparator is not None:
        return _unparsed(cell, column, f"a time point cannot be a bound ({cell.text!r})")

    number = float(parsed.value)  # type: ignore[arg-type]
    if column.time_axis in (TimeAxisKind.PASSAGE, TimeAxisKind.SIMULATION_STEP):
        if number != int(number):
            return _unparsed(
                cell,
                column,
                f"{column.time_axis.value} must be a whole count, got {cell.text!r}",
            )
        if number < 0:
            return _unparsed(cell, column, f"{column.time_axis.value} must not be negative")
        return parsed.model_copy(update={"value": int(number)})
    if number < 0:
        return _unparsed(cell, column, "elapsed time must not be negative")
    return parsed


def parse_cell(cell: RawCell, column: ColumnSpec, spec: DatasetSpec) -> ParsedCell:
    """Read one cell under its column's declared type. Never assigns a quality."""
    if cell.text.strip() in {token.strip() for token in spec.missing_tokens}:
        return _unparsed(cell, column, "declared missing token")

    if column.role is ColumnRole.TIME_AXIS:
        return _parse_time_axis(cell, column)
    if column.role is ColumnRole.IDENTIFIER:
        return _parse_categorical(cell, column)
    if column.value_type is None:
        # An undeclared condition is a *label*. Reading "5" as the number five here would
        # be inference, and inference is what this layer exists to avoid.
        return _parse_categorical(cell, column)
    return _BY_TYPE[column.value_type](cell, column)


def parse_row(
    cells: list[RawCell], spec: DatasetSpec
) -> tuple[list[ParsedCell], list[CellLocator]]:
    """Parse one row's cells, returning candidates and the locators of unmapped columns."""
    by_header = spec.by_header()
    parsed: list[ParsedCell] = []
    unmapped: list[CellLocator] = []
    for cell in cells:
        column = by_header.get(cell.locator.column_header)
        if column is None:
            unmapped.append(cell.locator)
            continue
        if column.role is ColumnRole.IGNORED:
            continue
        parsed.append(parse_cell(cell, column, spec))
    return parsed, unmapped
