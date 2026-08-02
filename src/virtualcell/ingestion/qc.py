"""Deterministic quality control (PR13b): the sole authority for measurement quality.

Every rule here answers a question about **acquisition**: was a reading taken, could the
instrument represent it, is it inside the range the instrument can report, is it one of the
categories this column is allowed to hold. Not one of them asks whether the *biology* is
interesting, healthy, senescent or immortal. That boundary is the reason QC can be shared
across verticals at all: the moment a QC rule encodes a biological judgement, it stops
being reusable and starts being a hidden domain model.

The vocabulary is exactly :class:`~virtualcell.core.experiment.MeasurementQuality`. This
module defines no verdict of its own, and a candidate never carries one — a
:class:`~virtualcell.ingestion.contracts.QCDecision` is the only thing that may assign it,
mirroring the literature pipeline's candidate/verification split.

Rules, in the order they are checked:

============================ ============================== ==========================
rule                         when                           quality
============================ ============================== ==========================
``MISSING_TOKEN``            no reading in the cell         ``missing``
``UNPARSEABLE``              text held no readable value    ``suspect`` (no value)
``TYPE_MISMATCH``            value is not the declared type ``suspect`` (no value)
``UNIT_MISMATCH``            cell unit ≠ declared unit      ``suspect`` (no value)
``BELOW_DETECTION``          below the declared low limit   ``below_detection``
``ABOVE_DETECTION``          above the declared high limit  ``above_detection``
``OUT_OF_RANGE``             outside the plausible range    ``suspect`` (value kept)
``UNEXPECTED_CATEGORY``      not a declared category        ``suspect`` (value kept)
``ACCEPTED``                 none of the above              ``valid``
============================ ============================== ==========================

A ``suspect`` reading that could not be read keeps **no** value: there is nothing to keep,
and inventing one is the failure mode this whole layer exists to prevent. A ``suspect``
reading that *was* read keeps its value, because a human reviewing the flag needs to see
what was recorded.
"""

from __future__ import annotations

from virtualcell.core.experiment import MeasurementQuality, MeasurementValueType
from virtualcell.core.values import ParseStatus
from virtualcell.ingestion.contracts import (
    ColumnSpec,
    ParsedCell,
    QCDecision,
    QCRule,
)


def _decision(
    cell: ParsedCell,
    quality: MeasurementQuality,
    rule: QCRule,
    *,
    flags: list[str] | None = None,
    detail: str | None = None,
) -> QCDecision:
    return QCDecision(
        locator=cell.locator,
        column=cell.column,
        quality=quality,
        rule=rule,
        flags=flags or [],
        detail=detail,
    )


def qc_decision(cell: ParsedCell, column: ColumnSpec) -> QCDecision:
    """Decide one cell's acquisition quality. Deterministic and self-explaining."""
    if cell.parse_status is not ParseStatus.PARSED:
        if cell.parse_note == "declared missing token":
            return _decision(
                cell, MeasurementQuality.MISSING, QCRule.MISSING_TOKEN, detail=cell.parse_note
            )
        return _decision(
            cell,
            MeasurementQuality.SUSPECT,
            QCRule.UNPARSEABLE,
            flags=[f"unparseable:{cell.raw_text}"],
            detail=cell.parse_note,
        )

    # The declared type is authoritative. A numeric column holding "high" is not a
    # categorical measurement that happens to live in the wrong column — it is a failure.
    if column.value_type is not None and cell.value_type is not column.value_type:
        return _decision(
            cell,
            MeasurementQuality.SUSPECT,
            QCRule.TYPE_MISMATCH,
            flags=[f"type_mismatch:{cell.value_type}"],
            detail=(
                f"column declares {column.value_type.value}, cell holds "
                f"{cell.value_type.value if cell.value_type else 'nothing'}"
            ),
        )

    expected_unit = column.source_unit or column.unit
    if cell.unit is not None and expected_unit is not None and cell.unit != expected_unit.lower():
        return _decision(
            cell,
            MeasurementQuality.SUSPECT,
            QCRule.UNIT_MISMATCH,
            flags=[f"unit_mismatch:{cell.unit}"],
            detail=(
                f"cell carries unit {cell.unit!r} but the column declares {expected_unit!r}; "
                "this layer performs no conversion it was not told about"
            ),
        )

    flags = _value_flags(cell)

    if cell.comparator is not None:
        # "<0.05" does not mean 0.05. The value is kept, because the limit is real
        # information, but the reading is not a point estimate and must never be read as
        # one: a trend, a mean or a comparison computed from it would be wrong in a way
        # nothing downstream could detect.
        return _decision(
            cell,
            MeasurementQuality.SUSPECT,
            QCRule.BOUNDED,
            flags=flags,
            detail=(
                f"{cell.raw_text!r} is a bound, not a point estimate; the value is a limit "
                "on the reading, not the reading"
            ),
        )

    if cell.value_type is MeasurementValueType.NUMERIC and isinstance(cell.value, (int, float)):
        number = float(cell.value)
        if column.detection_limit_low is not None and number < column.detection_limit_low:
            return _decision(
                cell,
                MeasurementQuality.BELOW_DETECTION,
                QCRule.BELOW_DETECTION,
                flags=[*flags, f"detection_limit_low:{column.detection_limit_low}"],
            )
        if column.detection_limit_high is not None and number > column.detection_limit_high:
            return _decision(
                cell,
                MeasurementQuality.ABOVE_DETECTION,
                QCRule.ABOVE_DETECTION,
                flags=[*flags, f"detection_limit_high:{column.detection_limit_high}"],
            )
        out_of_range = (column.plausible_min is not None and number < column.plausible_min) or (
            column.plausible_max is not None and number > column.plausible_max
        )
        if out_of_range:
            return _decision(
                cell,
                MeasurementQuality.SUSPECT,
                QCRule.OUT_OF_RANGE,
                flags=[*flags, f"out_of_range:{number}"],
                detail=(
                    f"outside the declared plausible range "
                    f"[{column.plausible_min}, {column.plausible_max}]"
                ),
            )

    if (
        column.allowed_categories is not None
        and cell.value_type is MeasurementValueType.CATEGORICAL
        and cell.value not in column.allowed_categories
    ):
        return _decision(
            cell,
            MeasurementQuality.SUSPECT,
            QCRule.UNEXPECTED_CATEGORY,
            flags=[*flags, f"unexpected_category:{cell.value}"],
            detail=f"declared categories: {', '.join(column.allowed_categories)}",
        )

    return _decision(cell, MeasurementQuality.VALID, QCRule.ACCEPTED, flags=flags)


def _value_flags(cell: ParsedCell) -> list[str]:
    """Modifiers the scalar measurement has no field for, kept so nothing is lost.

    Same vocabulary the literature converter uses, so a bound imported from a CSV and a
    bound extracted from a paper are flagged identically and neither is ever later read as
    a point estimate.
    """
    flags: list[str] = []
    if cell.comparator is not None:
        flags.append(f"bound:{cell.comparator}")
    if cell.uncertainty is not None:
        flags.append(f"uncertainty:{cell.uncertainty}")
    return flags


def value_is_usable(decision: QCDecision) -> bool:
    """May a decision's value be carried into a canonical measurement at all?

    A reading that could not be read has nothing to carry. Everything else does — including
    a flagged one, because dropping a suspect value would hide it from the human whose job
    it is to look.
    """
    return decision.rule not in {
        QCRule.MISSING_TOKEN,
        QCRule.UNPARSEABLE,
        QCRule.TYPE_MISMATCH,
        QCRule.UNIT_MISMATCH,
    }
