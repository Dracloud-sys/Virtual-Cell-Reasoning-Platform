"""Snapshot ⊕ time-series marker reconciliation (PR7c).

When a sufficient passage series is present, the trend it *derives* takes
precedence over the snapshot trend the user supplied — but never silently. The
snapshot is replaced by the derived value, the replacement is recorded in
``derived_input``, and a *material* disagreement (one side says the doubling time
is worsening / doublings have stalled, the other does not) is surfaced as an
``input_conflict``. Two values on the same side of the adverse boundary (e.g.
``stable`` vs ``improved``) update the effective value without raising a conflict.

``baseline_status`` itself is untouched: it still consumes a normalized marker
dict; this module only decides *which* trend value that dict carries.
"""

from __future__ import annotations

from virtualcell.agents.immortalization.models import ImmortalizationAssessmentInput, MarkerValue
from virtualcell.agents.immortalization.trajectory import TrajectoryAssessment, TrajectoryState

# The adverse pole of each trend: a worsening doubling time, or stalled doublings.
_ADVERSE = {"DT_trend": MarkerValue.WORSENING, "PDL_trend": MarkerValue.PLATEAU}


def _explicit(value: MarkerValue | None) -> bool:
    return value is not None and value != MarkerValue.UNKNOWN


def reconcile_markers(
    data: ImmortalizationAssessmentInput,
    trajectory: TrajectoryAssessment | None,
) -> tuple[dict[str, MarkerValue], dict[str, str], list[str]]:
    """Return ``(effective_markers, derived_input, input_conflicts)``.

    ``effective_markers`` is a full marker dict (the snapshot with PDL/DT trends
    overridden where the series derived a usable value). When the series is
    absent or insufficient, the snapshot is returned unchanged.
    """
    markers: dict[str, MarkerValue] = dict(data.marker_dict())
    derived_input: dict[str, str] = {}
    conflicts: list[str] = []

    if trajectory is None or trajectory.state == TrajectoryState.INSUFFICIENT_SERIES:
        return markers, derived_input, conflicts

    for field, derived in (
        ("PDL_trend", trajectory.derived_PDL_trend),
        ("DT_trend", trajectory.derived_DT_trend),
    ):
        if derived == MarkerValue.UNKNOWN:
            continue
        snapshot = markers.get(field)
        markers[field] = derived
        derived_input[field] = derived.value
        adverse = _ADVERSE[field]
        if _explicit(snapshot) and (snapshot == adverse) != (derived == adverse):
            conflicts.append(
                f"Provided {field} was {snapshot.value!r}, but the passage series supports "
                f"{derived.value!r}; the time-series-derived trend was used for assessment."
            )
    return markers, derived_input, conflicts
