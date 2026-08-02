"""Raw table -> canonical experiment runs (PR13b).

The end of the ingestion pipeline and the only place it produces
:class:`~virtualcell.core.experiment.ExperimentRun` objects:

    file -> RawTable -> ParsedCell candidates -> QCDecision -> ExperimentRun

Every run is emitted at the current :data:`SCHEMA_VERSION`, identified under the declared
namespace, sealed with its own checksum, and deduplicated against the rest of the import
using the PR13a semantic identity — so one file cannot import the same measurement twice
under two row numbers.

**This module writes nothing.** It returns runs and a report; whether any of it reaches a
KnowledgeStore is the caller's decision, exactly as in ``literature.canonical``. Ingesting
data and asserting it as evidence are different acts, and the second one deserves its own
deliberate step.
"""

from __future__ import annotations

from datetime import datetime

from virtualcell.core.experiment import (
    SCHEMA_VERSION,
    AcquisitionMode,
    ElapsedTimePoint,
    ExperimentRun,
    JSONScalar,
    Measurement,
    Observation,
    OriginKind,
    PassageTimePoint,
    Provenance,
    SimulationStepTimePoint,
    TimePoint,
    TimestampTimePoint,
    deduplicate_runs,
    make_run_id,
)
from virtualcell.ingestion.contracts import (
    ColumnRole,
    ColumnSpec,
    DatasetSpec,
    IngestionStatus,
    NormalizationStep,
    ParsedCell,
    QCDecision,
    QCReport,
    RawTable,
    RowRejection,
    RowRejectionReason,
    TabularIngestionResult,
    encode_group,
)
from virtualcell.ingestion.normalize import apply_step, normalization_step
from virtualcell.ingestion.parse import parse_row
from virtualcell.ingestion.qc import qc_decision, value_is_usable
from virtualcell.ingestion.readers import cells_of

SOURCE_SYSTEM = "tabular_ingestion"
ACQUISITION_METHOD = "declared_tabular_import_v1"


def _time_point(cell: ParsedCell, column: ColumnSpec) -> TimePoint | None:
    """Build the canonical time point a parsed axis cell describes."""
    from virtualcell.ingestion.contracts import TimeAxisKind

    if cell.value is None:
        return None
    if column.time_axis is TimeAxisKind.PASSAGE:
        return PassageTimePoint(value=int(cell.value))  # type: ignore[arg-type]
    if column.time_axis is TimeAxisKind.SIMULATION_STEP:
        return SimulationStepTimePoint(value=int(cell.value))  # type: ignore[arg-type]
    if column.time_axis is TimeAxisKind.ELAPSED_TIME:
        return ElapsedTimePoint(
            value=float(cell.value),  # type: ignore[arg-type]
            unit=column.time_unit,  # type: ignore[arg-type]
        )
    return TimestampTimePoint(value=datetime.fromisoformat(str(cell.value)))


def _measurement(
    cell: ParsedCell,
    column: ColumnSpec,
    decision: QCDecision,
    step: NormalizationStep | None,
) -> Measurement:
    """One canonical measurement, carrying its QC verdict and full cell provenance."""
    value: JSONScalar = cell.value if value_is_usable(decision) else None
    metadata: dict[str, JSONScalar] = {
        "source_name": cell.locator.source_name,
        "row_index": cell.locator.row_index,
        "column_header": cell.locator.column_header,
        "raw_text": cell.raw_text,
        "qc_rule": decision.rule.value,
        "qc_method": decision.qc_method,
    }
    if decision.detail:
        metadata["qc_detail"] = decision.detail

    if step is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
        # Keep the pre-conversion number so a wrong factor is a visible mistake rather
        # than silently corrupted data.
        metadata["pre_normalization_value"] = value
        metadata["normalization_from_unit"] = step.from_unit
        metadata["normalization_factor"] = step.factor
        metadata["normalization_method"] = step.method
        value = apply_step(float(value), step)

    return Measurement(
        name=column.canonical_name,
        value=value,
        value_type=column.value_type,
        unit=column.unit,
        quality=decision.quality,
        quality_flags=list(decision.flags),
        provenance=Provenance(
            origin_kind=OriginKind.EXPERIMENT,
            acquisition_mode=AcquisitionMode.IMPORTED,
            source_system=SOURCE_SYSTEM,
            source_run_id=cell.locator.source_name,
            method=ACQUISITION_METHOD,
            metadata=metadata,
        ),
    )


def _run_provenance(spec: DatasetSpec, source_name: str) -> Provenance:
    return Provenance(
        origin_kind=OriginKind.EXPERIMENT,
        acquisition_mode=AcquisitionMode.IMPORTED,
        source_system=SOURCE_SYSTEM,
        source_run_id=source_name,
        method=spec.method or ACQUISITION_METHOD,
        metadata={"dataset_id": spec.dataset_id, "spec_version": spec.spec_version},
    )


def ingest_table(table: RawTable, spec: DatasetSpec) -> TabularIngestionResult:
    """Convert one raw table into canonical runs under ``spec``.

    Rows sharing all identifier-column values form one run, and each row becomes one
    observation at its time point. Row order is preserved within a run, because the
    sequence of observations *is* the trajectory (PR13a).
    """
    result = TabularIngestionResult(spec_version=spec.spec_version, source_name=table.source_name)
    by_header = spec.by_header()

    declared = set(by_header)
    present = set(table.headers)
    result.unmapped_columns = sorted(present - declared)
    result.missing_columns = sorted(
        header for header, column in by_header.items() if column.required and header not in present
    )
    if result.missing_columns:
        result.status = IngestionStatus.SPEC_MISMATCH
        result.errors.append(
            f"the source is missing required column(s): {', '.join(result.missing_columns)}"
        )
        return result
    if not table.rows:
        result.status = IngestionStatus.NO_ROWS
        return result

    steps = {
        column.canonical_name: normalization_step(column)
        for column in spec.columns
        if column.role is ColumnRole.MEASUREMENT
    }
    result.normalizations = [step for step in steps.values() if step is not None]

    axis = next((c for c in spec.columns if c.role is ColumnRole.TIME_AXIS), None)
    decisions: list[QCDecision] = []
    groups: dict[str, list[Observation]] = {}
    group_identifiers: dict[str, dict[str, str]] = {}

    by_name = {c.canonical_name: c for c in spec.columns}

    for row_index in range(len(table.rows)):
        cells, unmapped = parse_row(cells_of(table, row_index), spec)
        _ = unmapped  # already reported at the header level; not repeated per row

        identifiers: dict[str, str] = {}
        conditions: dict[str, JSONScalar] = {}
        row_decisions: list[QCDecision] = []
        measurements: list[Measurement] = []
        time_point: TimePoint | None = None
        rejection: RowRejection | None = None

        for cell in cells:
            column = by_name[cell.column]
            if cell.role is ColumnRole.IDENTIFIER:
                # An unreadable required identifier means the row's run is unknown.
                # Defaulting it to "" would group every such row together, silently
                # merging unrelated cultures into one run — the one outcome grouping must
                # never produce.
                usable = cell.value if isinstance(cell.value, str) else None
                if column.required and not (usable or "").strip():
                    rejection = rejection or RowRejection(
                        row_index=row_index,
                        reason=RowRejectionReason.UNUSABLE_IDENTIFIER,
                        column=cell.column,
                        detail=(
                            f"required identifier {cell.column!r} is blank or unreadable "
                            f"({cell.raw_text!r}); which run this row belongs to is unknown"
                        ),
                    )
                    continue
                if usable is not None and usable.strip():
                    identifiers[cell.column] = usable.strip()
                continue
            if cell.role is ColumnRole.CONDITION:
                conditions[cell.column] = cell.value
                continue
            if cell.role is ColumnRole.TIME_AXIS:
                time_point = _time_point(cell, column)
                if time_point is None:
                    rejection = rejection or RowRejection(
                        row_index=row_index,
                        reason=RowRejectionReason.UNUSABLE_TIME_POINT,
                        column=cell.column,
                        detail=(
                            f"{cell.locator}: {cell.parse_note}; an observation with no "
                            "time point is not an observation"
                        ),
                    )
                continue
            decision = qc_decision(cell, column)
            row_decisions.append(decision)
            measurements.append(_measurement(cell, column, decision, steps[cell.column]))

        if axis is not None and time_point is None and rejection is None:
            rejection = RowRejection(
                row_index=row_index,
                reason=RowRejectionReason.UNUSABLE_TIME_POINT,
                detail="the declared time-axis column held no usable value",
            )
        if rejection is not None:
            # A rejected row contributes nothing at all: its QC decisions describe cells
            # that never became measurements, and reporting them would inflate the counts
            # a human reads to judge the import.
            result.rejected_rows.append(rejection)
            continue

        decisions.extend(row_decisions)
        if time_point is None:
            time_point = SimulationStepTimePoint(value=row_index)

        key = encode_group(identifiers)
        groups.setdefault(key, []).append(
            Observation(
                observation_id=f"{table.source_name}:row{row_index}",
                time_point=time_point,
                measurements=measurements,
                conditions=conditions,
            )
        )
        group_identifiers.setdefault(key, identifiers)

    result.qc = QCReport(decisions=decisions)

    runs: list[ExperimentRun] = []
    for key, observations in groups.items():
        local = f"{spec.dataset_id}:{key}" if key else spec.dataset_id
        run_conditions: dict[str, JSONScalar] = {**spec.conditions, **group_identifiers[key]}
        runs.append(
            ExperimentRun(
                # Stated explicitly: ingestion is a *producer* of canonical runs, so the
                # version it wrote against is visible at the construction site.
                schema_version=SCHEMA_VERSION,
                run_id=make_run_id(spec.run_namespace, local),
                provenance=_run_provenance(spec, table.source_name),
                conditions=run_conditions,
                observations=observations,
            ).sealed()
        )

    deduplicated = deduplicate_runs(runs)
    result.runs = deduplicated.runs
    result.collapsed_duplicates = list(deduplicated.collapsed)
    result.collisions = list(deduplicated.collisions)

    # The status is authoritative, so it must distinguish "imported everything" from
    # "imported some of it" from "imported none of it". A caller reading counts to work
    # that out is a caller that will eventually forget to.
    if not result.runs:
        result.status = IngestionStatus.NO_VALID_ROWS
    elif result.rejected_rows:
        result.status = IngestionStatus.PARTIAL
    return result
