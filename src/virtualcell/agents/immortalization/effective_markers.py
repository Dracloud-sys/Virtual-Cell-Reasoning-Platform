"""Snapshot ⊕ time-series marker reconciliation (PR7c, hardened).

When a sufficient passage series is present, the trend it *derives* takes
precedence over the snapshot trend the user supplied — but never silently, and
never from a low-quality axis. Quality gating is applied **per axis**:

* a derived PDL trend is blocked from overriding the snapshot when the PDL series
  has an integrity problem (``NON_MONOTONIC_PDL``) or was sampled too sparsely to
  trust an absolute-gain judgment (``SPARSE_PASSAGE_SAMPLING``);
* a derived DT trend that could not be established (``unknown`` — too few usable
  DT points) simply leaves the snapshot DT in place.

A blocked override is reported in ``blocked_overrides`` (a structured, top-level
reason), and the snapshot value is used — it is *not* shown in ``derived_input``
as though it had been applied. A *material* disagreement between an applied
derived trend and the snapshot (an adverse-boundary crossing) is surfaced as an
``input_conflict``. ``baseline_status`` itself is untouched.
"""

from __future__ import annotations

from virtualcell.agents.immortalization.models import ImmortalizationAssessmentInput, MarkerValue
from virtualcell.agents.immortalization.trajectory import (
    SeriesQualityFlag,
    TrajectoryAssessment,
)

# The adverse pole of each trend: a worsening doubling time, or stalled doublings.
_ADVERSE = {"DT_trend": MarkerValue.WORSENING, "PDL_trend": MarkerValue.PLATEAU}

# Quality flags that block a PDL-derived trend from overriding the snapshot. The DT
# fold change is a ratio and is not gated by these (it is gated by usable DT count,
# which already yields ``unknown`` when too few DT points exist).
_PDL_BLOCKING = {
    SeriesQualityFlag.NON_MONOTONIC_PDL: (
        "Cumulative PDL decreased between observations; the derived PDL trend was "
        "not used for status assessment."
    ),
    SeriesQualityFlag.SPARSE_PASSAGE_SAMPLING: (
        "Passage sampling was sparse (a gap exceeds the supported maximum), so the "
        "absolute PDL-gain trend is low-confidence and was not used for status assessment."
    ),
}


def _explicit(value: MarkerValue | None) -> bool:
    return value is not None and value != MarkerValue.UNKNOWN


def reconcile_markers(
    data: ImmortalizationAssessmentInput,
    trajectory: TrajectoryAssessment | None,
) -> tuple[dict[str, MarkerValue], dict[str, str], list[str], list[str]]:
    """Return ``(effective_markers, derived_input, input_conflicts, blocked_overrides)``.

    ``effective_markers`` is a full marker dict (the snapshot with PDL/DT trends
    overridden where the series derived a usable, quality-passing value). When the
    series is absent or insufficient, the snapshot is returned unchanged.
    """
    markers: dict[str, MarkerValue] = dict(data.marker_dict())
    derived_input: dict[str, str] = {}
    conflicts: list[str] = []
    blocked: list[str] = []

    # No series at all -> nothing to reconcile. NOTE: we deliberately do NOT early-return
    # on ``state == INSUFFICIENT_SERIES``: that state is a *PDL-axis* verdict (too few
    # usable PDL points), and a fully-sampled DT axis can still carry a valid derived
    # trend. Each axis is evaluated on its own derived value, not the overall state.
    if trajectory is None:
        return markers, derived_input, conflicts, blocked

    qflags = set(trajectory.quality_flags)

    def _apply(field: str, derived: MarkerValue, block_reasons: list[str]) -> None:
        if derived == MarkerValue.UNKNOWN:
            return  # nothing was derived for this axis; keep the snapshot silently
        if block_reasons:
            blocked.extend(block_reasons)
            return  # a value was derived but withheld; snapshot stays, not shown as applied
        snapshot = markers.get(field)
        markers[field] = derived
        derived_input[field] = derived.value
        adverse = _ADVERSE[field]
        if _explicit(snapshot) and (snapshot == adverse) != (derived == adverse):
            conflicts.append(
                f"Provided {field} was {snapshot.value!r}, but the passage series supports "
                f"{derived.value!r}; the time-series-derived trend was used for assessment."
            )

    _apply(
        "PDL_trend",
        trajectory.derived_PDL_trend,
        [msg for flag, msg in _PDL_BLOCKING.items() if flag in qflags],
    )
    _apply("DT_trend", trajectory.derived_DT_trend, [])
    return markers, derived_input, conflicts, blocked
