"""Immortalization adapters.

Two adapters live here:

* ``input_from_scenario`` (PR5c-3): a normalized scenario dict (benchmark shape)
  -> the typed :class:`ImmortalizationAssessmentInput`.
* The **canonical passage adapter** (PR8a): maps the domain-agnostic
  :class:`~virtualcell.core.experiment.ExperimentRun` / :class:`Observation` to and
  from the immortalization :class:`PassageObservation`, so canonical experiment data
  can enter this first vertical. The adapter only *reshapes* data — it performs no
  trajectory extraction, no reconciliation, and no candidate-status judgment.

Dependency direction: this module (a vertical) imports the canonical ``core``
schema; ``core`` never imports back.
"""

from __future__ import annotations

from typing import Any

from virtualcell.agents.immortalization.models import (
    AssessmentIntent,
    ImmortalizationAssessmentInput,
    PassageObservation,
)
from virtualcell.core.experiment import (
    AcquisitionMode,
    ExperimentRun,
    Measurement,
    Observation,
    OriginKind,
    PassageTimePoint,
    Provenance,
)

_MARKER_FIELDS = (
    "PDL_trend",
    "DT_trend",
    "gammaH2AX",
    "SA_b_gal",
    "p16",
    "p21",
    "adipogenic_retention",
)
# Keys consumed as typed fields (everything else is preserved in ``measurements``).
_TOP_LEVEL = {*_MARKER_FIELDS, "species", "cell_type", "construct", "observations"}


def input_from_scenario(
    intent: str | AssessmentIntent, scenario: dict[str, Any]
) -> ImmortalizationAssessmentInput:
    """Build an assessment input from an intent and a normalized scenario dict.

    A raw ``observations`` list (PR7 passage series) is routed to the typed field;
    pydantic validates each entry as a :class:`PassageObservation`.
    """
    markers = {key: scenario[key] for key in _MARKER_FIELDS if key in scenario}
    extras = {key: value for key, value in scenario.items() if key not in _TOP_LEVEL}
    return ImmortalizationAssessmentInput(
        intent=intent,
        species=scenario.get("species"),
        cell_type=scenario.get("cell_type"),
        construct_type=scenario.get("construct", "unknown"),
        observations=scenario.get("observations", []),
        measurements=extras,
        **markers,
    )


# --- Canonical passage adapter (PR8a) ---------------------------------------
#
# Fixed measurement mapping for this first vertical adapter. Only the two
# trajectory-relevant measurements are mapped; other PassageObservation fields
# (culture_day, proliferation/viability fraction, quantitative markers, endogenous
# TERT/CDK4, per-observation metadata) are NOT carried by this adapter yet and are
# lost on a forward-then-back round trip — a documented limitation of PR8a.

_PDL_NAME = "cumulative_PDL"
_DT_NAME = "DT_hours"
_UNIT = {_PDL_NAME: "population_doubling", _DT_NAME: "hour"}
_RECOGNIZED = frozenset(_UNIT)


class CanonicalAdapterError(ValueError):
    """Raised when a canonical Observation cannot be mapped to a PassageObservation."""


def _default_provenance() -> Provenance:
    """A hand-recorded wet-lab run, the default origin for immortalization data."""
    return Provenance(origin_kind=OriginKind.EXPERIMENT, acquisition_mode=AcquisitionMode.MANUAL)


def passage_observation_to_canonical(obs: PassageObservation) -> Observation:
    """Map a :class:`PassageObservation` to a canonical :class:`Observation`.

    Emits a passage time point plus a measurement for each of cumulative_PDL /
    DT_hours that is present. Only those two measurements are carried (see the
    module note); an observation with neither yields an empty measurement list.
    """
    measurements: list[Measurement] = []
    if obs.cumulative_PDL is not None:
        measurements.append(
            Measurement(name=_PDL_NAME, value=obs.cumulative_PDL, unit=_UNIT[_PDL_NAME])
        )
    if obs.DT_hours is not None:
        measurements.append(Measurement(name=_DT_NAME, value=obs.DT_hours, unit=_UNIT[_DT_NAME]))
    return Observation(time_point=PassageTimePoint(value=obs.passage), measurements=measurements)


def _numeric_value(measurement: Measurement) -> float:
    """Validate a recognized measurement's value and unit, returning a float.

    No unit conversion is performed: a present unit must equal the expected one
    (an unsupported unit is rejected, never silently reinterpreted).
    """
    value = measurement.value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CanonicalAdapterError(
            f"measurement {measurement.name!r} must be numeric, got {type(value).__name__}"
        )
    expected = _UNIT[measurement.name]
    if measurement.unit is not None and measurement.unit != expected:
        raise CanonicalAdapterError(
            f"measurement {measurement.name!r} unit {measurement.unit!r} is not supported "
            f"(expected {expected!r}); this adapter performs no unit conversion"
        )
    return float(value)


def canonical_to_passage_observation(
    obs: Observation, *, strict: bool = True
) -> PassageObservation:
    """Map a canonical :class:`Observation` back to a :class:`PassageObservation`.

    Only a passage time point is accepted. Unrecognized measurements are rejected
    when ``strict`` (the default) and ignored otherwise — they cannot be
    represented on a PassageObservation, so ``strict=False`` is a documented loss.
    """
    time_point = obs.time_point
    if time_point.kind != "passage":
        raise CanonicalAdapterError(
            f"a PassageObservation requires a passage time point, got {time_point.kind!r}"
        )

    values: dict[str, float] = {}
    for measurement in obs.measurements:
        if measurement.name in _RECOGNIZED:
            if measurement.name in values:
                raise CanonicalAdapterError(
                    f"duplicate measurement {measurement.name!r} in a single observation"
                )
            values[measurement.name] = _numeric_value(measurement)
        elif strict:
            raise CanonicalAdapterError(
                f"measurement {measurement.name!r} cannot be mapped to a PassageObservation "
                "(pass strict=False to ignore unmapped measurements)"
            )

    # Passage constraints (>= 0) and DT_hours (> 0) are enforced by PassageObservation.
    return PassageObservation(
        passage=time_point.value,
        cumulative_PDL=values.get(_PDL_NAME),
        DT_hours=values.get(_DT_NAME),
    )


def passage_series_to_run(
    observations: list[PassageObservation],
    *,
    run_id: str,
    provenance: Provenance | None = None,
    conditions: dict[str, Any] | None = None,
) -> ExperimentRun:
    """Wrap a passage series as a canonical :class:`ExperimentRun` (order preserved)."""
    return ExperimentRun(
        run_id=run_id,
        provenance=provenance or _default_provenance(),
        conditions=conditions or {},
        observations=[passage_observation_to_canonical(o) for o in observations],
    )


def run_to_passage_series(run: ExperimentRun, *, strict: bool = True) -> list[PassageObservation]:
    """Extract a passage series from a canonical run (order preserved).

    The result is exactly what ``extract_trajectory`` consumes, so a canonical run
    can drive the existing immortalization pipeline unchanged.
    """
    return [canonical_to_passage_observation(o, strict=strict) for o in run.observations]
