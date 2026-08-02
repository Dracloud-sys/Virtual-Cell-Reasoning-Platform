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

Every run carries an explicit :attr:`ExperimentRun.schema_version`, so a stored or
transmitted run states which contract it was written against instead of leaving readers to
guess. That matters because this schema is the convergence point: literature evidence,
domain packs, and (from PR13) raw-assay ingestion all produce or consume it, and a silent
shape change would corrupt data no single module owns.

**Version is mandatory.** ``schema_version`` has no default: an unversioned payload
arriving at a storage or transmission boundary is refused rather than silently assumed to
be v1 forever. Payloads serialized *before* versioning existed are still loadable, but only
through the explicit migration path (:func:`load_legacy_run` /
:func:`migrate_legacy_payload`), which injects :data:`LEGACY_SCHEMA_VERSION` for exactly
that case and refuses a payload that already declares a version.

**Compatibility policy.** The version is ``MAJOR.MINOR``:

* **MINOR** increments are *additive* — new optional fields only. A reader accepts any
  minor of its own major, including a *newer* one, because refusing structurally valid
  data would be the more damaging failure.
* **MAJOR** increments are *breaking* — renamed, removed, or re-typed fields. A reader
  refuses a different major outright (:class:`SchemaVersionError`) rather than
  misinterpreting it. Failing loudly beats silently reading a v2 payload as v1.

**Forward compatibility is preservation, not tolerance.** Accepting a newer minor is only
honest if the fields this reader does not understand survive it. Every canonical model
therefore sets ``extra="allow"``: unknown fields are kept on the model and re-serialized
unchanged, so a v1.0 reader can validate a v1.1 payload, store it, and hand it on without
quietly stripping the v1.1 additions while still declaring ``schema_version="1.1"``.

The run is the version-bearing unit, so the *strictness* check lives there: if a run
declares a version this reader fully knows (same major, minor at or below its own), unknown
fields anywhere in that run are an error, not silent extras — at a known version there are
no additive fields left to preserve, so an unknown key is a typo or a foreign shape.
Unknown fields are preserved without complaint only when the run declares a newer minor.

**Mixed-minor collections are legal.** A version is a property of a run, not of the
container holding it, so a bundle may legitimately carry runs at different minors of the
same major (older stored runs alongside newly produced ones). Containers validate each run
individually and must not require a single uniform minor.

Identity, value typing and conditions
-------------------------------------

* **Run identity is namespaced**: ``run_id`` is ``<namespace>:<local_id>`` (see
  :func:`make_run_id`). Once ingestion and a second domain pack both mint runs, an
  unqualified identifier makes collisions possible with no rule preventing them; the
  namespace states which system minted the id and keeps local ids independent.
* **Measurement values are typed**: :attr:`Measurement.value_type` distinguishes numeric,
  categorical and boolean values, so a numeric assay cannot silently carry a string.
  Consumers read numbers through :meth:`Measurement.numeric_value` instead of
  re-implementing a type guard each time.
* **Conditions compose, observation-first**: run-level conditions are defaults for the
  whole run and observation-level keys override them per time point. There is one
  canonical resolver — :meth:`ExperimentRun.effective_conditions` — so two readers cannot
  disagree about which wins.

Integrity and identity (schema 1.1, PR13a)
------------------------------------------

Two hashes, because "was this modified?" and "do I already have this?" are different
questions. One hash forced to answer both would either make a harmless re-import look like
tampering, or make two genuinely different runs look identical.

* :func:`content_checksum` — everything the run says, byte-stable. Answers **integrity**.
  Works at any declared version, since hashing bytes needs no understanding of the fields.
  The optional :attr:`ExperimentRun.checksum` seal is excluded from its own input;
  including it would be unsatisfiable, because writing the seal changes the run.
* :func:`dedup_key` — what the run *observed*. Answers **identity**, ignoring the fields
  that differ between two imports of the same data. It **refuses a newer minor**
  (:class:`DedupUnavailableError`): the hash covers the field set this reader knows, and a
  newer minor may have added the very field that tells two runs apart. Being unable to
  decide must never be reported as "same".

Collection semantics are stated, never left to the serializer: ``observations`` are an
ordered **sequence** (the trajectory); ``measurements`` within an observation are an
unordered **multiset**, so order is normalized away but multiplicity is kept — replicates
are real data; ``quality_flags`` are a true **set**, so repeats are normalized away too;
``conditions`` are mappings with normalized key order. Numeric values are normalized so
``1``/``1.0`` and ``0.0``/``-0.0`` cannot split a dedup group.
:func:`deduplicate_runs` keeps the first of each group and reports every collapse, raising
a structured :class:`DedupCollision` whenever two collapsed runs do not serialize
identically.

**Only finite numbers.** NaN and ±Infinity are refused by every canonical numeric field,
and :func:`_canonical_json` refuses them again at hash time so a preserved newer-minor
extra cannot slip one past. They are not JSON, ``NaN != NaN`` breaks the equality this
schema relies on, and pydantic writes them as ``null`` while a naive hash would cover
Python's non-standard token — a seal that cannot survive its own round trip. A non-finite
reading is a missing or invalid one; ``quality`` is the field that says so.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# JSON scalar values only — ``conditions``/``metadata`` are flat, JSON-serializable
# maps. Nested structures, arrays, and binary payloads are intentionally excluded
# from this first contract (they belong to a future artifact-reference model).
JSONScalar = str | int | float | bool | None


def _require_finite(value: float, field: str) -> float:
    """NaN and ±Infinity are not JSON, and this contract claims to be JSON-round-trippable.

    They also break every equality this schema depends on: ``NaN != NaN``, so a run
    containing one is not equal to itself, and pydantic's JSON serializer writes them as
    ``null`` while :func:`content_checksum` would hash Python's non-standard ``NaN`` token —
    a seal that cannot survive the round trip it claims to protect. A non-finite reading is
    a *missing or invalid* reading; say so with ``quality``, which is the field for it.
    """
    if not math.isfinite(value):
        raise ValueError(
            f"{field} must be a finite number, got {value!r}; NaN and Infinity are not "
            "representable in JSON — use quality='missing' or 'suspect' instead"
        )
    return value


def _finite_scalar(value: JSONScalar) -> JSONScalar:
    if isinstance(value, float):
        _require_finite(value, "value")
    return value


def _finite_float(value: float) -> float:
    return _require_finite(value, "value")


# The scalar types the canonical models actually accept. Identical to ``JSONScalar``
# except that non-finite floats are refused at the boundary rather than at hash time.
CanonicalScalar = Annotated[JSONScalar, AfterValidator(_finite_scalar)]
ScalarMap = dict[str, CanonicalScalar]

# Unknown fields are *preserved*, not ignored: a reader that accepts a newer minor must
# hand the fields it does not understand back out unchanged (see the module docstring).
# ``ExperimentRun`` rejects unknown fields when the declared version is one it fully knows.
CANONICAL_MODEL_CONFIG = ConfigDict(extra="allow")

# --- schema version ----------------------------------------------------------

SCHEMA_MAJOR: Final = 1
# 1.1 (PR13a) adds the optional ``ExperimentRun.checksum``. Additive, so by this module's
# own policy it is a *minor* bump: a 1.0 reader accepts a 1.1 run and preserves the field.
SCHEMA_MINOR: Final = 1
SCHEMA_VERSION: Final = f"{SCHEMA_MAJOR}.{SCHEMA_MINOR}"
"""The canonical experiment schema version this module implements."""

LEGACY_SCHEMA_VERSION: Final = "1.0"
"""The version implicitly held by payloads serialized before versioning existed.

Only :func:`migrate_legacy_payload` may assume it. Normal validation refuses a payload
with no ``schema_version`` rather than guessing.
"""

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


# --- run identity ------------------------------------------------------------

RUN_ID_SEPARATOR: Final = ":"
_RUN_NAMESPACE = re.compile(r"^[a-z][a-z0-9_]*$")


class RunIdError(ValueError):
    """Raised when a run identifier does not follow the canonical convention."""


def make_run_id(namespace: str, local_id: str) -> str:
    """Build a canonical ``<namespace>:<local_id>`` run identifier.

    The namespace names the system that minted the id (``literature``,
    ``immortalization``, an ingestion source). It is lower-case ``[a-z][a-z0-9_]*`` so
    identifiers are stable across systems and comparable without normalization.
    """
    if not _RUN_NAMESPACE.match(namespace or ""):
        raise RunIdError(
            f"run id namespace {namespace!r} is not canonical; expected lower-case "
            "'[a-z][a-z0-9_]*' naming the minting system (e.g. 'literature')"
        )
    local = (local_id or "").strip()
    if not local:
        raise RunIdError("run id local part must not be empty")
    if any(character.isspace() for character in local):
        raise RunIdError(f"run id local part {local_id!r} must not contain whitespace")
    return f"{namespace}{RUN_ID_SEPARATOR}{local}"


def parse_run_id(run_id: str) -> tuple[str, str]:
    """Split a canonical run id into ``(namespace, local_id)``.

    Only the *first* separator delimits the namespace: a local id may itself contain
    colons (a literature run keyed by DOI and sample group, for instance).
    """
    namespace, separator, local_id = (run_id or "").partition(RUN_ID_SEPARATOR)
    if not separator:
        raise RunIdError(
            f"run id {run_id!r} is not namespaced; expected '<namespace>{RUN_ID_SEPARATOR}"
            "<local_id>' so runs minted by different systems cannot collide"
        )
    make_run_id(namespace, local_id)  # re-validates both halves
    return namespace, local_id


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


class MeasurementValueType(StrEnum):
    """What kind of value a measurement holds.

    Separate from :class:`MeasurementQuality`, which is about acquisition, and from the
    unit, which is about scale. This is about *interpretability*: whether the value can be
    reasoned over arithmetically at all.
    """

    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    BOOLEAN = "boolean"


class MeasurementTypeError(ValueError):
    """Raised when a measurement is read as a type it does not hold."""


BOUND_FLAG_PREFIX: Final = "bound:"
"""Quality-flag prefix marking a reading as a bound rather than a point estimate.

Every producer of canonical runs uses it (``literature.canonical``,
``ingestion.qc``), and :meth:`Measurement.numeric_value` refuses anything carrying it, so
a limit can never be read as a value by a consumer that only remembered to check quality.
"""


# --- Time axis (discriminated union) ----------------------------------------
#
# Passage counts, elapsed culture time, simulation steps and wall-clock stamps
# are genuinely different axes; a discriminated union keeps them typed rather than
# collapsing them into one ambiguous number.


class PassageTimePoint(BaseModel):
    model_config = CANONICAL_MODEL_CONFIG

    kind: Literal["passage"] = "passage"
    value: int = Field(ge=0)


class ElapsedTimePoint(BaseModel):
    model_config = CANONICAL_MODEL_CONFIG

    kind: Literal["elapsed_time"] = "elapsed_time"
    value: Annotated[float, AfterValidator(_finite_float)] = Field(ge=0)
    unit: Literal["minute", "hour", "day"]


class SimulationStepTimePoint(BaseModel):
    model_config = CANONICAL_MODEL_CONFIG

    kind: Literal["simulation_step"] = "simulation_step"
    value: int = Field(ge=0)


class TimestampTimePoint(BaseModel):
    model_config = CANONICAL_MODEL_CONFIG

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

    model_config = CANONICAL_MODEL_CONFIG

    origin_kind: OriginKind
    acquisition_mode: AcquisitionMode
    source_system: str | None = None
    source_run_id: str | None = None
    method: str | None = None
    recorded_at: datetime | None = None
    metadata: ScalarMap = Field(default_factory=dict)

    @field_validator("recorded_at")
    @classmethod
    def _require_timezone(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("recorded_at must be timezone-aware")
        return v


class Measurement(BaseModel):
    """A single scalar measurement. Arrays/tensors/images/FCS payloads are out of
    scope for this first contract — only JSON scalars are accepted as ``value``."""

    model_config = CANONICAL_MODEL_CONFIG

    name: str
    value: CanonicalScalar = None
    # What the value *is*, so a numeric assay cannot silently hold a string. Inferred from
    # the value when a producer does not state it; when a producer does state it, a
    # mismatch is an error rather than a coercion.
    value_type: MeasurementValueType | None = None
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

    @model_validator(mode="after")
    def _value_type_matches_value(self) -> Measurement:
        """Infer the value type, or verify a declared one against the actual value.

        A value with no declared type is classified rather than left ambiguous, so every
        present value has a type. A *declared* type that disagrees with the value is the
        case this exists to catch: a numeric assay whose value arrived as ``"24.0"`` is
        refused at the boundary instead of failing somewhere downstream. A measurement
        with no value keeps whatever type was declared (a missing numeric reading is
        still a numeric measurement).
        """
        if self.value is None:
            return self
        actual = _classify_value(self.value)
        if self.value_type is None:
            self.value_type = actual
        elif self.value_type is not actual:
            raise ValueError(
                f"measurement {self.name!r} declares value_type "
                f"{self.value_type.value!r} but carries a {actual.value} value "
                f"({self.value!r}); the schema does not coerce between value types"
            )
        return self

    @property
    def is_numeric(self) -> bool:
        """Does this measurement hold a value that may be reasoned over arithmetically?"""
        return self.value_type is MeasurementValueType.NUMERIC and self.value is not None

    @property
    def bound(self) -> str | None:
        """The comparator this reading is bounded by (``<``, ``>=``, …), or ``None``.

        Producers record a bound as a ``bound:<comparator>`` quality flag rather than
        folding it into the value, precisely so it cannot be lost.
        """
        for flag in self.quality_flags:
            if flag.startswith(BOUND_FLAG_PREFIX):
                return flag[len(BOUND_FLAG_PREFIX) :]
        return None

    @property
    def is_point_estimate(self) -> bool:
        """Is this a single measured value, rather than a bound on one?"""
        return self.is_numeric and self.bound is None

    def numeric_value(self) -> float:
        """Return the value as a float, or raise :class:`MeasurementTypeError`.

        The single place a consumer converts a measurement to a number. Booleans are
        refused rather than promoted to 1/0, and a numeric-looking string is refused
        rather than parsed — reading ``"24.0"`` as 24.0 is exactly the silent
        reinterpretation the value type exists to prevent.

        A **bounded** reading is refused too. ``<0.05`` does not mean 0.05; it means the
        true value is somewhere below it, and every arithmetic a consumer would perform —
        a trend, a mean, a comparison — would be wrong in a way nothing downstream could
        detect. Read :attr:`bound` and decide deliberately, or use :attr:`value`.
        """
        if self.bound is not None:
            raise MeasurementTypeError(
                f"measurement {self.name!r} is bounded ({self.bound}{self.value!r}), not a "
                "point estimate; reading it as a number would treat a limit as a value"
            )
        if self.value is None:
            raise MeasurementTypeError(
                f"measurement {self.name!r} carries no value to read "
                f"(quality {self.quality.value!r})"
            )
        if not self.is_numeric:
            declared = self.value_type.value if self.value_type else "untyped"
            raise MeasurementTypeError(
                f"measurement {self.name!r} is {declared}, not numeric (value {self.value!r})"
            )
        return float(self.value)  # type: ignore[arg-type]


def _classify_value(value: JSONScalar) -> MeasurementValueType:
    # bool before int: in Python ``bool`` is a subclass of ``int``, and a flag is not a
    # quantity — classifying True as numeric would let it be averaged.
    if isinstance(value, bool):
        return MeasurementValueType.BOOLEAN
    if isinstance(value, (int, float)):
        return MeasurementValueType.NUMERIC
    return MeasurementValueType.CATEGORICAL


class Observation(BaseModel):
    """One time point of a run: a set of measurements sharing conditions/provenance.

    The canonical layer does not enforce measurement presence, time-point ordering,
    or uniqueness — replicates and out-of-order raw data are legitimate, and their
    detection belongs to a domain QC layer, not the container.

    ``conditions`` here are the conditions *at this time point*; they override the
    run-level defaults key by key. Resolve them with
    :meth:`ExperimentRun.effective_conditions` rather than merging by hand.
    """

    model_config = CANONICAL_MODEL_CONFIG

    observation_id: str | None = None
    time_point: TimePoint
    measurements: list[Measurement] = Field(default_factory=list)
    conditions: ScalarMap = Field(default_factory=dict)
    provenance: Provenance | None = None


def _extra_field_paths(model: BaseModel, prefix: str = "") -> list[str]:
    """Dotted paths of every unknown field carried anywhere inside ``model``."""
    paths = [f"{prefix}{key}" for key in sorted(model.model_extra or {})]
    for name in type(model).model_fields:
        value = getattr(model, name, None)
        if isinstance(value, BaseModel):
            paths.extend(_extra_field_paths(value, f"{prefix}{name}."))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, BaseModel):
                    paths.extend(_extra_field_paths(item, f"{prefix}{name}[{index}]."))
    return paths


class ExperimentRun(BaseModel):
    """A source-neutral run: run-level provenance plus ordered observations.

    ``observations`` preserves input order and does not reject duplicate time
    points (replicates are allowed). Measurement-level provenance, when present,
    overrides the run-level provenance for that measurement, and observation-level
    conditions override run-level conditions key by key
    (:meth:`effective_conditions`).
    """

    model_config = CANONICAL_MODEL_CONFIG

    # Declared first so it is the leading key in a serialized run: a reader can check
    # what it is looking at before interpreting anything else. Required, not defaulted —
    # an unversioned payload is refused rather than assumed to be v1 (see
    # :func:`load_legacy_run` for the one path that may assume it).
    schema_version: str
    run_id: str
    provenance: Provenance
    conditions: ScalarMap = Field(default_factory=dict)
    observations: list[Observation] = Field(default_factory=list)
    metadata: ScalarMap = Field(default_factory=dict)
    # Optional integrity seal (schema 1.1). Self-verifying when present: it must equal
    # :func:`content_checksum` of this run, so a stored run that was edited in place no
    # longer validates. Absent means "not sealed", never "verified".
    checksum: str | None = None

    @field_validator("schema_version")
    @classmethod
    def _version_is_well_formed(cls, v: str) -> str:
        # Only the *shape* is enforced at construction. Whether this reader can interpret
        # the version is a separate question (`validate_schema_version`), because a run
        # may legitimately be constructed to be handed to a different reader.
        parse_schema_version(v)
        return v

    @field_validator("run_id")
    @classmethod
    def _run_id_is_namespaced(cls, v: str) -> str:
        parse_run_id(v)
        return v

    @model_validator(mode="after")
    def _unknown_fields_require_a_newer_minor(self) -> ExperimentRun:
        """Unknown fields are preserved only when the run claims a version we don't know.

        At a version this reader fully implements there are no additive fields left to
        carry, so an unknown key is a typo or a foreign shape and is refused. Preservation
        (``extra="allow"``) exists for the forward-compatibility case, not as a general
        invitation to attach arbitrary keys — ``metadata`` is the field for that.
        """
        major, minor = parse_schema_version(self.schema_version)
        if major != SCHEMA_MAJOR or minor > SCHEMA_MINOR:
            return self
        unknown = _extra_field_paths(self)
        if unknown:
            raise ValueError(
                f"run {self.run_id!r} declares schema_version {self.schema_version!r}, "
                f"which this reader fully implements, but carries unknown fields: "
                f"{', '.join(unknown)}. Use 'metadata' for extra keys, or declare a newer "
                "minor version if these are additive schema fields."
            )
        return self

    @model_validator(mode="after")
    def _declared_checksum_matches(self) -> ExperimentRun:
        """A declared checksum must match the run it seals, or it is worse than none."""
        if self.checksum is not None:
            expected = content_checksum(self)
            if self.checksum != expected:
                raise ValueError(
                    f"run {self.run_id!r} declares checksum {self.checksum!r} but its "
                    f"content hashes to {expected!r}; the run was modified after it was "
                    "sealed, or the checksum was computed over different content"
                )
        return self

    def sealed(self) -> ExperimentRun:
        """A copy of this run carrying its own :func:`content_checksum`.

        Producers seal a run when they hand it to something that stores or transmits it,
        so a later reader can tell an intact run from an edited one.
        """
        return self.model_copy(update={"checksum": content_checksum(self)})

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

    @property
    def run_namespace(self) -> str:
        """The system that minted this run's identifier."""
        return parse_run_id(self.run_id)[0]

    @property
    def run_local_id(self) -> str:
        """The identifier local to :attr:`run_namespace`."""
        return parse_run_id(self.run_id)[1]

    def effective_conditions(self, observation: Observation) -> dict[str, JSONScalar]:
        """Conditions in force at ``observation``: run-level defaults, then overrides.

        The canonical resolver. Run-level conditions describe the whole run, so they are
        the base; an observation states what changed at that time point, so its keys win.
        A reader must never merge these by hand — two readers disagreeing about precedence
        would silently disagree about what an experiment measured.
        """
        return {**self.conditions, **observation.conditions}


def migrate_legacy_payload(
    payload: Mapping[str, Any], *, namespace: str | None = None
) -> dict[str, Any]:
    """Add the implicit version to a payload serialized before versioning existed.

    This is the *only* place :data:`LEGACY_SCHEMA_VERSION` may be assumed. A payload that
    already declares a version is not a legacy payload and is refused, so this can never
    be used to paper over a version that failed a compatibility check.

    ``namespace`` optionally qualifies a pre-convention ``run_id`` that carries no
    namespace. It is opt-in and never guessed: silently renaming an identifier a caller
    may have stored elsewhere is worse than refusing it.
    """
    if "schema_version" in payload:
        raise SchemaVersionError(
            f"payload already declares schema_version "
            f"{payload['schema_version']!r}; legacy migration is only for payloads "
            "written before the version existed — validate it normally instead"
        )
    migrated: dict[str, Any] = {"schema_version": LEGACY_SCHEMA_VERSION, **payload}
    run_id = migrated.get("run_id")
    if namespace is not None and isinstance(run_id, str) and RUN_ID_SEPARATOR not in run_id:
        migrated["run_id"] = make_run_id(namespace, run_id)
    return migrated


def load_legacy_run(payload: Mapping[str, Any], *, namespace: str | None = None) -> ExperimentRun:
    """Load a pre-versioning payload as a v1 run. See :func:`migrate_legacy_payload`."""
    return ExperimentRun.model_validate(migrate_legacy_payload(payload, namespace=namespace))


# --- integrity and identity (PR13a) ------------------------------------------

HASH_PREFIX: Final = "sha256:"


class DedupUnavailableError(SchemaVersionError):
    """Raised when a run's declared version makes semantic dedup unsound."""


def _canonical_json(payload: Any) -> str:
    """One byte-stable serialization, so a hash is reproducible across processes.

    ``allow_nan=False`` is the last line of defence rather than the first: the canonical
    fields already refuse non-finite floats at validation, but a **preserved newer-minor
    extra** is by definition unvalidated, and Python's ``json`` module both emits and
    accepts the non-standard ``NaN``/``Infinity`` tokens. Hashing one would produce a seal
    no standards-compliant reader could reproduce.
    """
    try:
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
    except ValueError as exc:
        raise ValueError(
            "cannot hash a run containing a non-finite number (NaN or Infinity); it is not "
            f"representable in JSON, so the hash would not be reproducible: {exc}"
        ) from exc


def _canonical_numbers(value: Any) -> Any:
    """Collapse numeric values that differ only in Python spelling, recursively.

    ``1`` and ``1.0`` are the same measurement — :meth:`Measurement.numeric_value` reads
    both as ``1.0`` — and ``0.0``/``-0.0`` are the same quantity. Two producers writing the
    same reading with different Python types (a CSV reader emitting ``int``, the literature
    converter emitting ``float``) must land in the same dedup group, or PR13b ingestion
    would import a measurement it already had.

    Used only by :func:`dedup_key`. :func:`content_checksum` deliberately does **not**
    normalize: it answers whether the bytes changed, and ``1`` and ``1.0`` are different
    bytes.
    """
    if isinstance(value, bool):
        return value  # a flag is not a quantity; keep it distinct from 0/1
    if isinstance(value, float):
        if not math.isfinite(value):
            # Unreachable through validated fields; leave it for _canonical_json to refuse
            # with a clear message rather than crashing on int(inf).
            return value
        integral = int(value)
        return integral if value == integral else value
    if isinstance(value, dict):
        return {key: _canonical_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_numbers(item) for item in value]
    return value


def _digest(payload: Any) -> str:
    return HASH_PREFIX + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _reject_non_finite_numbers(payload: Any, path: str = "") -> None:
    """Refuse a non-finite number anywhere in ``payload``, naming where it is.

    Runs against the **python-mode** dump, before serialization, because pydantic's JSON
    mode rewrites NaN and ±Infinity to ``null``. Checking afterwards would be too late in
    the way that matters: a run carrying NaN and a run carrying null would seal to the same
    checksum, so the seal would certify data it had already silently altered.
    """
    where = path or "value"
    if isinstance(payload, bool):
        return
    if isinstance(payload, float):
        if not math.isfinite(payload):
            raise ValueError(
                f"cannot hash a run containing a non-finite number at {where}: {payload!r} "
                "is not representable in JSON, so the hash would not be reproducible"
            )
        return
    if isinstance(payload, Mapping):
        for key, item in payload.items():
            _reject_non_finite_numbers(item, f"{where}.{key}" if path else str(key))
        return
    if isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            _reject_non_finite_numbers(item, f"{where}[{index}]")


def content_checksum(run: ExperimentRun) -> str:
    """Hash of everything the run says — the *integrity* question.

    Covers the full serialization: version, identity, metadata, provenance timestamps and
    any preserved unknown fields. Two runs with the same checksum are byte-identical as
    canonical JSON, so a mismatch means the run changed after it was sealed.

    :attr:`ExperimentRun.checksum` is excluded from its own input. Including it would make
    the seal unsatisfiable — writing the checksum into the run changes the run, so no value
    could ever equal the hash of the run containing it.

    Works at **any** declared version, including a newer minor: hashing bytes needs no
    understanding of what the fields mean. That is the difference from :func:`dedup_key`.

    Refuses a run carrying a non-finite number anywhere, including inside a preserved
    newer-minor extra that no field validator saw.
    """
    _reject_non_finite_numbers(run.model_dump())
    payload = run.model_dump(mode="json")
    payload.pop("checksum", None)
    return _digest(payload)


def _measurement_identity(measurement: Measurement) -> dict[str, Any]:
    return _canonical_numbers(
        {
            "name": measurement.name,
            "value": measurement.value,
            "value_type": measurement.value_type.value if measurement.value_type else None,
            "unit": measurement.unit,
            "quality": measurement.quality.value,
            # A genuine *set*: order carries nothing, and a flag repeated twice says exactly
            # what it says once, so both order and multiplicity are normalized away.
            "quality_flags": sorted(set(measurement.quality_flags)),
        }
    )


def dedup_key(run: ExperimentRun) -> str:
    """Hash of what the run *observed* — the *identity* question.

    Answers "have I already stored this measurement?", so it deliberately ignores the
    fields that differ between two imports of the same data: ``run_id``,
    ``schema_version``, ``checksum``, ``metadata``, ``observation_id``,
    ``provenance.recorded_at``, ``provenance.metadata``, and observation/measurement-level
    provenance. Those record *where a datum came from*, not what it says.

    Run-level provenance ``origin_kind``/``acquisition_mode``/``source_system``/
    ``source_run_id``/``method`` **is** included: a simulation run and a wet-lab run with
    identical numbers are not duplicates of one another.

    Ordering and normalization, stated rather than left to the serializer:

    * ``observations`` — an ordered **sequence**: order is significant and preserved. The
      sequence is the trajectory; reordering it changes what the run means.
    * ``measurements`` within an observation — an unordered **multiset**: order is
      normalized away by sorting, multiplicity is **not**. Two readings of the same value
      at one time point are replicates, and a run with two is not the same experiment as a
      run with one.
    * ``quality_flags`` — a true **set**: order and multiplicity are both normalized away.
      A flag repeated twice says exactly what it says once.
    * numeric values, anywhere in the payload — normalized so that ``1`` and ``1.0`` and
      ``0.0`` and ``-0.0`` are the same quantity (:func:`_canonical_numbers`). Consumers
      already read them that way, and two producers spelling one reading differently must
      not land in different dedup groups.
    * ``conditions`` (both levels) — mappings, so key order is normalized by sorting.
      Observation entries carry :meth:`ExperimentRun.effective_conditions`; run-level
      conditions are hashed separately as well, because *where* a condition is declared is
      itself a statement (a run-level condition asserts it held for the whole run) and
      because a run may have no observations at all.

    Refuses a run declaring a **newer minor** (:class:`DedupUnavailableError`). This hash
    is computed over the field set this reader knows; a newer minor may have added a field
    that distinguishes two runs, and hashing without it would collapse records that are
    not duplicates. Silently merging distinct experimental data is the one outcome dedup
    must never produce, so an unknown minor means "cannot decide", not "same".
    """
    major, minor = parse_schema_version(run.schema_version)
    if major != SCHEMA_MAJOR:
        raise DedupUnavailableError(
            f"cannot compute a dedup key for run {run.run_id!r}: it declares "
            f"{run.schema_version!r} and this reader implements {SCHEMA_VERSION!r}"
        )
    if minor > SCHEMA_MINOR:
        raise DedupUnavailableError(
            f"cannot compute a dedup key for run {run.run_id!r}: it declares minor "
            f"{run.schema_version!r}, newer than this reader's {SCHEMA_VERSION!r}, so a "
            "field that distinguishes it from another run may be invisible here"
        )
    provenance = run.provenance
    payload = {
        "provenance": {
            "origin_kind": provenance.origin_kind.value,
            "acquisition_mode": provenance.acquisition_mode.value,
            "source_system": provenance.source_system,
            "source_run_id": provenance.source_run_id,
            "method": provenance.method,
        },
        "conditions": _canonical_numbers(dict(run.conditions)),
        "observations": [
            {
                "time_point": _canonical_numbers(observation.time_point.model_dump(mode="json")),
                "conditions": _canonical_numbers(run.effective_conditions(observation)),
                # An unordered *multiset*: order is normalized away, multiplicity is not.
                # Two readings of the same value at one time point are replicates, and a run
                # with two is not the same experiment as a run with one.
                "measurements": sorted(
                    (_measurement_identity(m) for m in observation.measurements),
                    key=_canonical_json,
                ),
            }
            for observation in run.observations
        ],
    }
    return _digest(payload)


class DedupCollision(BaseModel):
    """Two runs claim the same observations but do not serialize identically.

    Reported as a record rather than a warning string so a caller can act on it: the
    difference lies entirely in fields :func:`dedup_key` excludes (identity, metadata,
    provenance timestamps), which usually means the same data was imported twice under
    different provenance — but "usually" is not "always", and a human should be able to
    look at both.

    ``run_id`` is part of the checksum and not part of the key, so **two distinct records
    asserting the same observations always produce a collision**, while a byte-identical
    re-import collapses quietly. That asymmetry is the point: one record seen twice is
    housekeeping, two records making the same claim is a fact about the data.
    """

    dedup_key: str
    kept_run_id: str
    kept_checksum: str
    dropped_run_id: str
    dropped_checksum: str


class DeduplicationResult(BaseModel):
    """The outcome of :func:`deduplicate_runs`."""

    runs: list[ExperimentRun] = Field(default_factory=list)
    """The runs to keep, in input order."""

    collapsed: list[str] = Field(default_factory=list)
    """Run ids dropped because an earlier run reported the same observations."""

    collisions: list[DedupCollision] = Field(default_factory=list)
    """Collapses where the two runs did not serialize identically."""

    not_deduplicated: list[str] = Field(default_factory=list)
    """Run ids kept without a dedup decision because their version blocked one.

    These are **kept**, never dropped: being unable to prove two runs are duplicates is a
    reason to hold both, not a reason to discard one.
    """


def deduplicate_runs(runs: list[ExperimentRun]) -> DeduplicationResult:
    """Collapse runs reporting the same observations, keeping the first of each.

    Deterministic: input order decides which run is kept, so the same input always yields
    the same output. Nothing is dropped silently — every collapse is named in
    :attr:`DeduplicationResult.collapsed`, and any collapse whose runs differ outside the
    dedup field set is additionally reported as a :class:`DedupCollision`.
    """
    result = DeduplicationResult()
    seen: dict[str, tuple[str, str]] = {}
    for run in runs:
        try:
            key = dedup_key(run)
        except DedupUnavailableError:
            result.not_deduplicated.append(run.run_id)
            result.runs.append(run)
            continue
        checksum = content_checksum(run)
        previous = seen.get(key)
        if previous is None:
            seen[key] = (run.run_id, checksum)
            result.runs.append(run)
            continue
        kept_run_id, kept_checksum = previous
        result.collapsed.append(run.run_id)
        if kept_checksum != checksum:
            result.collisions.append(
                DedupCollision(
                    dedup_key=key,
                    kept_run_id=kept_run_id,
                    kept_checksum=kept_checksum,
                    dropped_run_id=run.run_id,
                    dropped_checksum=checksum,
                )
            )
    return result
