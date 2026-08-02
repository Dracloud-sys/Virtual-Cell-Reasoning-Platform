"""Canonical, source-neutral experiment data contracts.

The platform's long-term goal is to run one reasoning pipeline over two kinds of
data — virtual-cell **simulation** output and **experiment** data (today
hand-recorded, later instrument/robot generated). These contracts are the
common shape both converge to *before* any domain reasoning:

    source-specific input
        -> canonical experiment schema   (this module)
        -> deterministic QC / features   (per vertical)
        -> vertical-specific reasoning
        -> grounded DecisionReport

Layering: this lives in ``core`` and is deliberately domain-agnostic. It imports
nothing from ``agents`` or ``reasoning`` (no ``DecisionReport``/trajectory types),
so verticals depend on it, never the reverse. It knows how to *hold* an
observation, not how to judge one.

Scope: a typed, JSON-round-trippable contract only. No simulator/robot/LIMS
connectors, no ingest, no normalization, no reasoning.

Canonical Experiment Schema v1 (PR12)
-------------------------------------

Every run now carries an explicit :attr:`ExperimentRun.schema_version`, so a stored or
transmitted run states which contract it was written against instead of leaving readers to
guess. That matters because this schema is the convergence point: literature evidence,
domain packs, and (from PR13) raw-assay ingestion all produce or consume it, and a silent
shape change would corrupt data no single module owns.

**Compatibility policy.** The version is ``MAJOR.MINOR``:

* **MINOR** increments are *additive* — new optional fields only. A reader accepts any
  minor of its own major, including a *newer* one: unknown additive fields are simply not
  consumed, which is safer than refusing data that is structurally fine.
* **MAJOR** increments are *breaking* — renamed, removed, or re-typed fields. A reader
  refuses a different major outright (:class:`SchemaVersionError`) rather than
  misinterpreting it. Failing loudly beats silently reading a v2 payload as v1.

Producers should leave :attr:`ExperimentRun.schema_version` at its default; consumers that
accept runs from outside their own process should call :func:`validate_schema_version`
before trusting the shape.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# JSON scalar values only — ``conditions``/``metadata`` are flat, JSON-serializable
# maps. Nested structures, arrays, and binary payloads are intentionally excluded
# from this first contract (they belong to a future artifact-reference model).
JSONScalar = str | int | float | bool | None

# --- schema version ----------------------------------------------------------

SCHEMA_MAJOR: Final = 1
SCHEMA_MINOR: Final = 0
SCHEMA_VERSION: Final = f"{SCHEMA_MAJOR}.{SCHEMA_MINOR}"
"""The canonical experiment schema version this module implements."""

_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)$")


class SchemaVersionError(ValueError):
    """Raised when a run declares a schema version this reader cannot interpret."""


def parse_schema_version(version: str) -> tuple[int, int]:
    """Split a ``MAJOR.MINOR`` version string, rejecting anything malformed."""
    match = _VERSION_PATTERN.match(version or "")
    if match is None:
        raise SchemaVersionError(
            f"malformed schema_version {version!r}; expected 'MAJOR.MINOR' "
            f"(e.g. {SCHEMA_VERSION!r})"
        )
    return int(match.group(1)), int(match.group(2))


def is_compatible(version: str) -> bool:
    """Can this reader interpret ``version``? Same major, any minor."""
    try:
        major, _minor = parse_schema_version(version)
    except SchemaVersionError:
        return False
    return major == SCHEMA_MAJOR


def validate_schema_version(version: str) -> None:
    """Raise :class:`SchemaVersionError` unless ``version`` is readable here.

    A *newer minor* is accepted deliberately: minors are additive, so the fields this
    reader knows about are still present and correctly typed, and refusing structurally
    valid data would be the more damaging failure. A different *major* is refused, because
    silently reading a v2 payload as v1 would corrupt the meaning of the data.
    """
    major, _minor = parse_schema_version(version)
    if major != SCHEMA_MAJOR:
        raise SchemaVersionError(
            f"incompatible canonical experiment schema: run declares {version!r}, "
            f"this reader implements {SCHEMA_VERSION!r} (major {SCHEMA_MAJOR})"
        )


class OriginKind(StrEnum):
    """Where the data fundamentally comes from (biological vs in-silico)."""

    SIMULATION = "simulation"
    EXPERIMENT = "experiment"


class AcquisitionMode(StrEnum):
    """*How* the data was acquired — an axis orthogonal to :class:`OriginKind`.

    ``automated`` is not an origin: a robot experiment is still an experiment. So
    acquisition is separated out (a wet-lab flow-cytometer export is
    ``experiment`` + ``instrument``; a simulator dump is ``simulation`` +
    ``imported``).
    """

    MANUAL = "manual"
    INSTRUMENT = "instrument"
    ROBOTIC = "robotic"
    IMPORTED = "imported"


class MeasurementQuality(StrEnum):
    """Conservative acquisition-quality vocabulary (never a biological verdict)."""

    VALID = "valid"
    MISSING = "missing"
    BELOW_DETECTION = "below_detection"
    ABOVE_DETECTION = "above_detection"
    SUSPECT = "suspect"
    EXCLUDED = "excluded"


# --- Time axis (discriminated union) ----------------------------------------
#
# Passage counts, elapsed culture time, simulation steps and wall-clock stamps
# are genuinely different axes; a discriminated union keeps them typed rather than
# collapsing them into one ambiguous number.


class PassageTimePoint(BaseModel):
    kind: Literal["passage"] = "passage"
    value: int = Field(ge=0)


class ElapsedTimePoint(BaseModel):
    kind: Literal["elapsed_time"] = "elapsed_time"
    value: float = Field(ge=0)
    unit: Literal["minute", "hour", "day"]


class SimulationStepTimePoint(BaseModel):
    kind: Literal["simulation_step"] = "simulation_step"
    value: int = Field(ge=0)


class TimestampTimePoint(BaseModel):
    kind: Literal["timestamp"] = "timestamp"
    value: datetime

    @field_validator("value")
    @classmethod
    def _require_timezone(cls, v: datetime) -> datetime:
        # A naive timestamp is ambiguous across sites/instruments; require tz-aware.
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp time point must be timezone-aware")
        return v


TimePoint = Annotated[
    PassageTimePoint | ElapsedTimePoint | SimulationStepTimePoint | TimestampTimePoint,
    Field(discriminator="kind"),
]


class Provenance(BaseModel):
    """Where a run or measurement came from — not how strong it is as evidence.

    Provenance answers "where from"; an evidence tier answers "how strongly does
    this support a claim". They are kept separate, and this PR does not compute an
    evidence tier from provenance.
    """

    origin_kind: OriginKind
    acquisition_mode: AcquisitionMode
    source_system: str | None = None
    source_run_id: str | None = None
    method: str | None = None
    recorded_at: datetime | None = None
    metadata: dict[str, JSONScalar] = Field(default_factory=dict)

    @field_validator("recorded_at")
    @classmethod
    def _require_timezone(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("recorded_at must be timezone-aware")
        return v


class Measurement(BaseModel):
    """A single scalar measurement. Arrays/tensors/images/FCS payloads are out of
    scope for this first contract — only JSON scalars are accepted as ``value``."""

    name: str
    value: JSONScalar = None
    unit: str | None = None
    # An optional pointer for a future ontology/registry; this PR does not resolve
    # or validate it, and does not hardcode a controlled vocabulary for ``name``.
    ontology_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    quality: MeasurementQuality = MeasurementQuality.VALID
    quality_flags: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("measurement name must not be empty")
        return v

    @model_validator(mode="after")
    def _value_quality_consistent(self) -> Measurement:
        # A present value cannot be labelled missing, and a valid measurement must
        # carry a value. Other qualities (suspect/excluded/…) may or may not.
        if self.quality == MeasurementQuality.MISSING and self.value is not None:
            raise ValueError("a measurement marked 'missing' must not carry a value")
        if self.value is None and self.quality == MeasurementQuality.VALID:
            raise ValueError("a 'valid' measurement must carry a value (use quality='missing')")
        return self


class Observation(BaseModel):
    """One time point of a run: a set of measurements sharing conditions/provenance.

    The canonical layer does not enforce measurement presence, time-point ordering,
    or uniqueness — replicates and out-of-order raw data are legitimate, and their
    detection belongs to a domain QC layer, not the container.
    """

    observation_id: str | None = None
    time_point: TimePoint
    measurements: list[Measurement] = Field(default_factory=list)
    conditions: dict[str, JSONScalar] = Field(default_factory=dict)
    provenance: Provenance | None = None


class ExperimentRun(BaseModel):
    """A source-neutral run: run-level provenance plus ordered observations.

    ``observations`` preserves input order and does not reject duplicate time
    points (replicates are allowed). Measurement-level provenance, when present,
    overrides the run-level provenance for that measurement.
    """

    # Declared first so it is the leading key in a serialized run: a reader can check
    # what it is looking at before interpreting anything else.
    schema_version: str = SCHEMA_VERSION
    run_id: str
    provenance: Provenance
    conditions: dict[str, JSONScalar] = Field(default_factory=dict)
    observations: list[Observation] = Field(default_factory=list)
    metadata: dict[str, JSONScalar] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _version_is_well_formed(cls, v: str) -> str:
        # Only the *shape* is enforced at construction. Whether this reader can interpret
        # the version is a separate question (`validate_schema_version`), because a run
        # may legitimately be constructed to be handed to a different reader.
        parse_schema_version(v)
        return v

    @property
    def schema_is_compatible(self) -> bool:
        """Can this process interpret the run's declared schema version?"""
        return is_compatible(self.schema_version)

    def require_compatible_schema(self) -> None:
        """Raise :class:`SchemaVersionError` unless this run is readable here.

        Consumers accepting runs from outside their own process (stored bundles, other
        services, future ingestion) should call this before trusting field meanings.
        """
        validate_schema_version(self.schema_version)

    @field_validator("run_id")
    @classmethod
    def _run_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("run_id must not be empty")
        return v
