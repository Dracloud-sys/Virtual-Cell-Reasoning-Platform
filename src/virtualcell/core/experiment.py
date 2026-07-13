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

Scope of this first PR: a typed, JSON-round-trippable contract only. No
simulator/robot/LIMS connectors, no ingest, no normalization, no reasoning.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# JSON scalar values only — ``conditions``/``metadata`` are flat, JSON-serializable
# maps. Nested structures, arrays, and binary payloads are intentionally excluded
# from this first contract (they belong to a future artifact-reference model).
JSONScalar = str | int | float | bool | None


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

    run_id: str
    provenance: Provenance
    conditions: dict[str, JSONScalar] = Field(default_factory=dict)
    observations: list[Observation] = Field(default_factory=list)
    metadata: dict[str, JSONScalar] = Field(default_factory=dict)

    @field_validator("run_id")
    @classmethod
    def _run_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("run_id must not be empty")
        return v
