"""Typed contracts for declared tabular ingestion (PR13b).

The three epistemic layers of the literature pipeline are reproduced here, because raw
experimental data poses the same problem as a paper: something *proposes* a value,
something else *decides* whether it is usable, and only then is it converted.

1. **Raw** (:class:`RawTable`, :class:`RawCell`) — the file, verbatim. No typing, no
   interpretation, no coercion. Every cell keeps a :class:`CellLocator` so any later
   statement can be traced back to a row and column.
2. **Parsed candidate** (:class:`ParsedCell`) — what a cell *appears* to contain under the
   column's declared type. A candidate carries **no quality verdict**; a failed parse is
   recorded as a fact about the text, not as a judgement about the datum.
3. **QC decision** (:class:`QCDecision`) — the **single authoritative home** of
   :class:`~virtualcell.core.experiment.MeasurementQuality`. Nothing else may assign it.

**Declared, never inferred.** A :class:`DatasetSpec` states which columns exist, what they
mean, what type they hold and what units they are in. An unmapped column is reported, never
guessed; a missing required column fails the run. Free-form column mapping stays out of
scope deliberately — a guess about what a column means is a guess about what an experiment
measured.

**QC is acquisition quality, never biology.** The vocabulary is exactly
:class:`MeasurementQuality`; this module defines no verdict of its own. "This reading is
below the detection limit" is a statement about an instrument. "This culture is senescent"
is a statement about cells, and it belongs to a vertical, not to ingestion.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from enum import StrEnum
from typing import Final, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, model_validator

from virtualcell.core.experiment import (
    JSONScalar,
    MeasurementQuality,
    MeasurementValueType,
    ScalarMap,
    parse_schema_version,
)
from virtualcell.core.values import ParseStatus

# --- spec versioning ---------------------------------------------------------
#
# A spec is a stored artifact that outlives the code that read it, so it declares its own
# version under the same policy as the canonical run schema: a newer minor is additive and
# accepted, a different major is refused.

SPEC_MAJOR: Final = 1
SPEC_MINOR: Final = 0
SPEC_VERSION: Final = f"{SPEC_MAJOR}.{SPEC_MINOR}"


class SpecVersionError(ValueError):
    """Raised when a dataset spec declares a version this reader cannot interpret."""


def validate_spec_version(version: str) -> None:
    """Refuse a spec version this reader cannot execute.

    Stricter than the canonical run schema, and deliberately so. A run is **data**: a
    reader that meets a newer minor can carry the fields it does not understand through
    untouched, so accepting one loses nothing. A spec is **executed** — every field is an
    instruction about how to read a file — so a newer minor may carry an instruction this
    reader would silently not follow, and the import would look successful while ignoring
    part of what the author asked for. A newer minor is therefore refused until a reader
    exists that implements it.
    """
    major, minor = parse_schema_version(version)
    if major != SPEC_MAJOR:
        raise SpecVersionError(
            f"incompatible dataset spec: declares {version!r}, this reader implements "
            f"{SPEC_VERSION!r} (major {SPEC_MAJOR})"
        )
    if minor > SPEC_MINOR:
        raise SpecVersionError(
            f"dataset spec declares minor {version!r}, newer than this reader's "
            f"{SPEC_VERSION!r}; a spec is executed rather than relayed, so an instruction "
            "this reader does not implement would be silently skipped"
        )


def _require_finite_number(value: float | None, field: str) -> float | None:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number, got {value!r}")
    return value


class SourceFormat(StrEnum):
    """Formats PR13b reads. XLSX is PR13b-2; it lands the first parsing dependency."""

    CSV = "csv"
    TSV = "tsv"


class ColumnRole(StrEnum):
    """What a column contributes to the canonical run."""

    TIME_AXIS = "time_axis"
    """The observation's time point. Exactly one column may hold this role."""

    MEASUREMENT = "measurement"
    """A reading, becoming one :class:`Measurement` per row."""

    CONDITION = "condition"
    """An observation-level condition at that time point."""

    IDENTIFIER = "identifier"
    """Groups rows into runs. Rows sharing all identifier values form one run."""

    IGNORED = "ignored"
    """Present in the file and deliberately not ingested. Declaring it is the point:
    an ignored column is a decision, an unmapped one is an oversight."""


class TimeAxisKind(StrEnum):
    """Which canonical time point a time-axis column produces."""

    PASSAGE = "passage"
    ELAPSED_TIME = "elapsed_time"
    SIMULATION_STEP = "simulation_step"
    TIMESTAMP = "timestamp"


class ColumnSpec(BaseModel):
    """What one source column means. Everything here is declared by a human."""

    model_config = ConfigDict(extra="forbid")

    header: str
    """The exact header text in the file. Matched literally after stripping."""

    role: ColumnRole
    name: str | None = None
    """Canonical measurement/condition name. Defaults to :attr:`header`."""

    value_type: MeasurementValueType | None = None
    """Required for a measurement: the type every cell in this column must hold. This is
    what stops a numeric assay from silently carrying a string — a non-numeric cell in a
    numeric column becomes a QC failure, never a categorical measurement."""

    unit: str | None = None
    """The unit measurements are *emitted* in."""

    source_unit: str | None = None
    """The unit the file is actually in, when it differs from :attr:`unit`."""

    unit_factor: float | None = None
    """``canonical = source * factor``. Required whenever ``source_unit != unit``: this
    layer performs no conversion it was not told about."""

    time_axis: TimeAxisKind | None = None
    time_unit: Literal["minute", "hour", "day"] | None = None
    """Required for an ``elapsed_time`` axis."""

    detection_limit_low: float | None = None
    detection_limit_high: float | None = None
    plausible_min: float | None = None
    plausible_max: float | None = None
    allowed_categories: list[str] | None = None
    required: bool = True
    """Whether the column must be present in the file."""

    @property
    def canonical_name(self) -> str:
        return self.name or self.header

    @model_validator(mode="after")
    def _role_requirements(self) -> ColumnSpec:
        if self.role is ColumnRole.MEASUREMENT and self.value_type is None:
            raise ValueError(
                f"measurement column {self.header!r} must declare a value_type; inferring "
                "it per cell is exactly the silent reinterpretation this layer prevents"
            )
        if self.role is ColumnRole.TIME_AXIS:
            if self.time_axis is None:
                raise ValueError(f"time-axis column {self.header!r} must declare time_axis")
            if self.time_axis is TimeAxisKind.ELAPSED_TIME and self.time_unit is None:
                raise ValueError(
                    f"elapsed-time column {self.header!r} must declare time_unit; an "
                    "elapsed duration with no unit is not a time point"
                )
        if self.source_unit is not None and self.source_unit != self.unit:
            if self.unit_factor is None:
                raise ValueError(
                    f"column {self.header!r} declares source_unit {self.source_unit!r} but "
                    f"emits {self.unit!r} with no unit_factor; this layer never guesses a "
                    "conversion"
                )
            if self.unit_factor <= 0:
                raise ValueError(
                    f"column {self.header!r} unit_factor must be positive, got "
                    f"{self.unit_factor!r}; a zero or negative factor is not a unit "
                    "conversion, it is a different measurement"
                )
        for field in (
            "unit_factor",
            "detection_limit_low",
            "detection_limit_high",
            "plausible_min",
            "plausible_max",
        ):
            _require_finite_number(getattr(self, field), f"column {self.header!r} {field}")
        if (
            self.detection_limit_low is not None
            and self.detection_limit_high is not None
            and self.detection_limit_low > self.detection_limit_high
        ):
            raise ValueError(
                f"column {self.header!r} detection_limit_low "
                f"({self.detection_limit_low}) is above detection_limit_high "
                f"({self.detection_limit_high}); no reading could ever satisfy both"
            )
        if (
            self.plausible_min is not None
            and self.plausible_max is not None
            and self.plausible_min > self.plausible_max
        ):
            raise ValueError(
                f"column {self.header!r} plausible_min ({self.plausible_min}) is above "
                f"plausible_max ({self.plausible_max}); the range is empty"
            )
        return self


class DatasetSpec(BaseModel):
    """A declared description of one tabular source. The whole contract of an import."""

    model_config = ConfigDict(extra="forbid")

    spec_version: str
    """Required. An unversioned spec is refused rather than assumed to be the current
    version: a spec is executed, and guessing which instructions it meant is how a file
    gets read under rules its author never wrote."""

    dataset_id: str
    """Names this dataset in the run identity: ``<run_namespace>:<dataset_id>[:<group>]``."""

    source_format: SourceFormat = SourceFormat.CSV
    columns: list[ColumnSpec]
    run_namespace: str = "ingestion"
    missing_tokens: list[str] = Field(default_factory=lambda: ["", "NA", "N/A", "na", "n/a"])
    """Cell texts that mean "no reading was taken". Declared, because a bare ``-`` means
    'not measured' in one lab and 'not detected' in another."""

    conditions: ScalarMap = Field(default_factory=dict)
    """Constant run-level conditions that are true of the whole file."""

    method: str | None = None
    """Free-text acquisition method, carried into provenance."""

    @model_validator(mode="after")
    def _spec_is_coherent(self) -> DatasetSpec:
        validate_spec_version(self.spec_version)
        if not self.dataset_id.strip():
            raise ValueError("dataset_id must not be empty")
        headers = [column.header for column in self.columns]
        duplicates = sorted({h for h in headers if headers.count(h) > 1})
        if duplicates:
            raise ValueError(f"duplicate column headers in spec: {', '.join(duplicates)}")
        axes = [c for c in self.columns if c.role is ColumnRole.TIME_AXIS]
        if len(axes) > 1:
            raise ValueError(
                f"a run has one time axis, but the spec declares {len(axes)}: "
                f"{', '.join(c.header for c in axes)}"
            )
        if not any(c.role is ColumnRole.MEASUREMENT for c in self.columns):
            raise ValueError("a spec must declare at least one measurement column")
        # Canonical names must be unique across *every* ingested column, not just the
        # measurements. Two columns sharing a name collapse into one entry wherever the
        # pipeline keys by name — and for identifiers that is data loss with teeth: rows
        # differing only in the shadowed column would group into a single run, silently
        # merging unrelated cultures. Ignored columns are exempt: they contribute nothing,
        # so their names cannot collide with anything.
        names: list[str] = [
            c.canonical_name for c in self.columns if c.role is not ColumnRole.IGNORED
        ]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            raise ValueError(
                f"duplicate canonical column name(s) in spec: {', '.join(repeated)}. "
                "Every ingested column must resolve to a distinct name; two columns "
                "sharing one would collapse into a single value."
            )
        return self

    def by_header(self) -> dict[str, ColumnSpec]:
        return {column.header: column for column in self.columns}


# --- raw layer ---------------------------------------------------------------


class CellLocator(BaseModel):
    """Where a value came from — the tabular analogue of a literature ``SourceLocator``."""

    model_config = ConfigDict(extra="forbid")

    source_name: str
    row_index: int = Field(ge=0)
    """0-based index over *data* rows, so row 0 is the first row under the header."""

    column_header: str

    def __str__(self) -> str:
        return f"{self.source_name}[row {self.row_index}, {self.column_header!r}]"


class RawCell(BaseModel):
    """One cell, verbatim. No typing happens at this layer."""

    model_config = ConfigDict(extra="forbid")

    locator: CellLocator
    text: str


class RawTable(BaseModel):
    """A source file read as text. Nothing is interpreted, nothing is dropped."""

    model_config = ConfigDict(extra="forbid")

    source_name: str
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


# --- parsed candidate layer --------------------------------------------------


class ParsedCell(BaseModel):
    """What a cell appears to contain under its column's declared type.

    Carries **no** quality verdict. ``parse_note`` explains what the text did, not whether
    the datum is any good — that decision belongs to :class:`QCDecision` alone.
    """

    model_config = ConfigDict(extra="forbid")

    locator: CellLocator
    column: str
    role: ColumnRole
    raw_text: str
    value: JSONScalar = None
    value_type: MeasurementValueType | None = None
    unit: str | None = None
    comparator: str | None = None
    """A bound (``<``/``>``), kept separate so it is never read as a point estimate."""

    uncertainty: float | None = None
    parse_status: ParseStatus = ParseStatus.UNPARSED
    parse_note: str | None = None


# --- QC decision layer -------------------------------------------------------

QC_METHOD: Final = "declared_tabular_qc_v1"


class QCRule(StrEnum):
    """The deterministic rule that produced a decision. No rule consults biology."""

    ACCEPTED = "accepted"
    MISSING_TOKEN = "missing_token"
    UNPARSEABLE = "unparseable"
    TYPE_MISMATCH = "type_mismatch"
    UNIT_MISMATCH = "unit_mismatch"
    BOUNDED = "bounded"
    BELOW_DETECTION = "below_detection"
    ABOVE_DETECTION = "above_detection"
    OUT_OF_RANGE = "out_of_range"
    UNEXPECTED_CATEGORY = "unexpected_category"


class QCDecision(BaseModel):
    """The sole authority for a measurement's :class:`MeasurementQuality`.

    Mirrors the literature ``VerificationDecision``: a candidate proposes, a decision
    judges, and the two are never merged. ``rule`` names the deterministic rule that fired,
    so any decision can be re-derived rather than trusted.
    """

    model_config = ConfigDict(extra="forbid")

    locator: CellLocator
    column: str
    quality: MeasurementQuality
    rule: QCRule
    flags: list[str] = Field(default_factory=list)
    detail: str | None = None
    qc_method: str = QC_METHOD


class QCReport(BaseModel):
    """Every decision made during one import, plus counts for a human to scan."""

    model_config = ConfigDict(extra="forbid")

    decisions: list[QCDecision] = Field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for decision in self.decisions:
            counts[decision.quality.value] = counts.get(decision.quality.value, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def accepted(self) -> int:
        return sum(1 for d in self.decisions if d.quality is MeasurementQuality.VALID)

    def for_rule(self, rule: QCRule) -> list[QCDecision]:
        return [d for d in self.decisions if d.rule is rule]


# --- normalization -----------------------------------------------------------


class NormalizationStep(BaseModel):
    """A unit conversion that was actually applied, recorded so it can be undone.

    No conversion happens without one of these, and the pre-conversion value is kept in the
    measurement's provenance, so normalization is auditable rather than a one-way door.
    """

    model_config = ConfigDict(extra="forbid")

    column: str
    from_unit: str
    to_unit: str
    factor: float
    method: str = "declared_linear_factor_v1"


# --- result ------------------------------------------------------------------


class RowRejectionReason(StrEnum):
    """Why a row could not become an observation. Never a judgement about the biology."""

    UNUSABLE_TIME_POINT = "unusable_time_point"
    """An observation with no time point is not an observation."""

    UNUSABLE_IDENTIFIER = "unusable_identifier"
    """A required identifier was blank or unreadable, so which run the row belongs to is
    unknown. Grouping it with every other such row would silently merge unrelated data."""


class RowRejection(BaseModel):
    """One rejected row, reported structurally so a caller can act on it."""

    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0)
    reason: RowRejectionReason
    column: str | None = None
    detail: str


class IngestionStatus(StrEnum):
    """The authoritative outcome of an import. Callers must not infer it from counts.

    ``PARTIAL`` exists because "some rows were rejected" is neither success nor failure:
    real runs were produced *and* a human needs to look. Collapsing it into either one
    would hide the half that matters.
    """

    SUCCESS = "success"
    PARTIAL = "partial"
    NO_VALID_ROWS = "no_valid_rows"
    NO_ROWS = "no_rows"
    SPEC_MISMATCH = "spec_mismatch"
    UNREADABLE_SOURCE = "unreadable_source"

    @property
    def is_failure(self) -> bool:
        """Did the import fail to produce usable runs? ``PARTIAL`` did not."""
        return self not in (IngestionStatus.SUCCESS, IngestionStatus.PARTIAL)

    @property
    def exit_code(self) -> int:
        """The process exit code for this outcome.

        Three values, because there are three answers: 0 imported everything, 2 imported
        something and rejected something, 1 imported nothing. A partial import must not
        exit 0 (the rejects would go unseen) nor 1 (the runs it did produce are real).
        """
        if self is IngestionStatus.SUCCESS:
            return 0
        if self is IngestionStatus.PARTIAL:
            return 2
        return 1


class TabularIngestionResult(BaseModel):
    """Everything one import produced. This module writes nothing; the caller decides."""

    model_config = ConfigDict(extra="forbid")

    status: IngestionStatus = IngestionStatus.SUCCESS
    spec_version: str = SPEC_VERSION
    source_name: str = ""
    runs: list = Field(default_factory=list)
    """Canonical :class:`~virtualcell.core.experiment.ExperimentRun` objects, sealed."""

    qc: QCReport = Field(default_factory=QCReport)
    normalizations: list[NormalizationStep] = Field(default_factory=list)
    unmapped_columns: list[str] = Field(default_factory=list)
    """Columns present in the file that the spec does not describe. Reported, never
    guessed at — a column nobody declared is a question for a human."""

    missing_columns: list[str] = Field(default_factory=list)
    rejected_rows: list[RowRejection] = Field(default_factory=list)
    """Rows that could not become observations, each with the reason it was rejected."""

    errors: list[str] = Field(default_factory=list)
    collapsed_duplicates: list[str] = Field(default_factory=list)
    collisions: list = Field(default_factory=list)

    @property
    def rows_ingested(self) -> int:
        return sum(len(run.observations) for run in self.runs)


def encode_group(identifiers: Mapping[str, str]) -> str:
    """Encode identifier values into a collision-safe ``run_id`` local part.

    Every name and value is percent-encoded before the ``name=value`` pairs are joined with
    ``|``, so the encoding is **injective**: no combination of identifier values can produce
    the string another combination produces. Concatenating raw values with delimiters would
    not be — ``{"a": "x|b=y"}`` and ``{"a": "x", "b": "y"}`` would collide, silently merging
    two unrelated cultures into one run.

    Percent-encoding also removes the whitespace a canonical run id forbids, so an
    identifier like ``IMR 90`` needs no lossy slug. The untouched values are written to the
    run's conditions regardless, so nothing about the data lives only in the handle.
    """
    return "|".join(
        f"{quote(name, safe='')}={quote(value, safe='')}"
        for name, value in sorted(identifiers.items())
    )
