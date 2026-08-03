"""Declared unit normalization (PR13b).

One rule: **no conversion this layer was not told about.** A column that reports hours
while the canonical measurement is in hours needs nothing; a column reporting minutes
declares ``source_unit="minute"``, ``unit="hour"`` and ``unit_factor=1/60``, and every
converted value carries a :class:`~virtualcell.ingestion.contracts.NormalizationStep` plus
its pre-conversion value in provenance.

That combination is what keeps normalization from being a one-way door. A number in a
canonical run can always be traced back to the number in the file and the factor that
linked them, so a wrong factor is a visible mistake rather than silently corrupted data.

Deliberately out of scope: unit *inference* (guessing that "hr" means hours), dimensional
analysis, and any cross-run statistical normalization — batch correction, quantile
normalization and friends need a model of the whole dataset, which is reasoning, not
ingestion.
"""

from __future__ import annotations

from virtualcell.ingestion.contracts import ColumnSpec, NormalizationStep


def normalization_step(column: ColumnSpec) -> NormalizationStep | None:
    """The conversion this column declares, or ``None`` when it declares none."""
    if column.source_unit is None or column.source_unit == column.unit:
        return None
    # ColumnSpec validation guarantees a non-zero factor whenever the units differ.
    return NormalizationStep(
        column=column.canonical_name,
        from_unit=column.source_unit,
        to_unit=column.unit or "",
        factor=float(column.unit_factor),  # type: ignore[arg-type]
    )


def apply_step(value: float, step: NormalizationStep | None) -> float:
    """Apply a declared conversion. Identity when nothing was declared."""
    return value if step is None else value * step.factor
