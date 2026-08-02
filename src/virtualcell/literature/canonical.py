"""Canonical conversion of verified literature measurements (PR8d-2).

The last epistemic step before evidence storage: a measurement candidate that the
deterministic gate marked ``MACHINE_VERIFIED`` (PR8d-1) is turned into a source-neutral
:class:`~virtualcell.core.experiment.ExperimentRun`, the same shape simulation and
wet-lab data converge to. This is deliberately narrow:

* **only** a ``MACHINE_VERIFIED`` *measurement* is converted — a ``PENDING_REVIEW`` or
  ``REJECTED`` decision, a claim, an author interpretation, and a ``statistic``-tagged
  candidate are never converted (a statistic is *about* a measurement, not one);
* a decision is linked to its candidate by ``candidate_id`` and only converted when the
  candidate is actually present, so a dangling decision produces nothing;
* full provenance (article ids, exact locator, source-text hash, the verification
  decision, the raw value and its comparator/uncertainty) travels into the run;
* conversion is deterministic — the same verified measurement always yields the same
  ``run_id`` and content, and duplicate inputs collapse to one run.

This module writes **nothing**: it returns runs, and the caller decides whether to place
them in ``LiteratureEvidenceBundle.canonical_runs``. KnowledgeStore ingestion and any
weak-relation modelling are later slices (PR8e), and no reasoning happens here.
"""

from __future__ import annotations

import re

from virtualcell.core.experiment import (
    SCHEMA_VERSION,
    AcquisitionMode,
    ExperimentRun,
    Measurement,
    MeasurementQuality,
    Observation,
    OriginKind,
    PassageTimePoint,
    Provenance,
    TimePoint,
    TimestampTimePoint,
)
from virtualcell.literature.contracts import (
    CandidateKind,
    ExtractedMeasurementCandidate,
    ParseStatus,
    SourceKind,
    VerificationDecision,
    VerificationStatus,
)

# How a literature-derived run identifies itself as canonical provenance.
SOURCE_SYSTEM = "literature"
RUN_ID_PREFIX = "literature"

# A passage encoded in the (explicitly temporal) ``time_point`` field: "P35",
# "passage 35", "35". Deliberately strict — the ambiguous ``sample_group`` axis is kept
# as a verbatim condition and never guessed into a time axis.
_PASSAGE = re.compile(r"^\s*(?:passage|p)?[\s._-]*(\d+)\s*$", re.IGNORECASE)


def experiment_runs_from_verified(
    measurements: list[ExtractedMeasurementCandidate],
    decisions: list[VerificationDecision],
) -> list[ExperimentRun]:
    """Convert every ``MACHINE_VERIFIED`` measurement to a canonical ``ExperimentRun``.

    Deterministic and total-order-preserving: measurements are processed in input order,
    each verified candidate yields exactly one run, and a candidate seen twice (or a
    duplicate decision) collapses to a single run. Anything not a machine-verified
    measurement is skipped, never converted.
    """
    verified = {
        decision.candidate_id: decision
        for decision in decisions
        if decision.candidate_kind is CandidateKind.MEASUREMENT
        and decision.status is VerificationStatus.MACHINE_VERIFIED
    }
    runs: list[ExperimentRun] = []
    seen: set[str] = set()
    for measurement in measurements:
        decision = verified.get(measurement.candidate_id)
        if decision is None or measurement.candidate_id in seen:
            continue
        if not _is_convertible(measurement):
            # Defensive: a machine-verified decision should already guarantee this, but a
            # statistic / prose / unparsed value must never become a canonical run.
            continue
        seen.add(measurement.candidate_id)
        runs.append(_run_from_measurement(measurement, decision))
    return runs


def _is_convertible(measurement: ExtractedMeasurementCandidate) -> bool:
    """A canonical run is only built from an exact, quantitative table measurement."""
    return (
        measurement.source_locator.source_kind is SourceKind.TABLE
        and measurement.statistic is None
        and measurement.parse_status is ParseStatus.PARSED
        and measurement.parsed_value is not None
    )


def _time_point(
    measurement: ExtractedMeasurementCandidate, decision: VerificationDecision
) -> TimePoint:
    """A typed time axis: a passage when the temporal field cleanly encodes one, else the
    record's creation stamp (the verification time) — the literature source carries no
    other machine-readable measurement time, and none is invented."""
    match = _PASSAGE.match(measurement.time_point) if measurement.time_point else None
    if match:
        return PassageTimePoint(value=int(match.group(1)))
    return TimestampTimePoint(value=decision.verified_at)


def _conditions(measurement: ExtractedMeasurementCandidate) -> dict[str, str]:
    """Verbatim experimental context — copied, never interpreted."""
    fields = {
        "sample_group": measurement.sample_group,
        "species": measurement.species,
        "cell_type": measurement.cell_type,
        "time_point": measurement.time_point,
        "normalization": measurement.normalization,
        "control": measurement.control,
        "assay": measurement.assay,
    }
    return {key: value for key, value in fields.items() if value is not None}


def _provenance(
    measurement: ExtractedMeasurementCandidate, decision: VerificationDecision
) -> Provenance:
    locator = measurement.source_locator
    article = locator.article
    metadata: dict[str, str | int | float | bool | None] = {
        "article_key": article.stable_key(),
        "article_doi": article.doi,
        "article_pmid": article.pmid,
        "article_pmcid": article.pmcid,
        "article_provider_id": article.provider_id,
        "source_kind": locator.source_kind.value,
        "table_id": locator.table_id,
        "row_index": locator.row_index,
        "column_index": locator.column_index,
        "row_label": locator.row_label,
        "column_label": locator.column_label,
        "section_title": locator.section_title,
        "source_text": locator.source_text,
        "source_text_hash": locator.source_text_hash,
        "candidate_id": measurement.candidate_id,
        "extraction_method": measurement.extraction_method.value,
        "raw_value": measurement.raw_value,
        "comparator": measurement.comparator,
        "uncertainty": measurement.uncertainty,
        "verification_status": decision.status.value,
        "verifier": decision.verifier,
        "verification_method": decision.method,
        "verified_at": decision.verified_at.isoformat(),
    }
    return Provenance(
        origin_kind=OriginKind.EXPERIMENT,  # a paper reports a real experiment, not a sim
        acquisition_mode=AcquisitionMode.IMPORTED,  # imported from literature, not measured here
        source_system=SOURCE_SYSTEM,
        source_run_id=article.stable_key(),
        method=decision.method,
        recorded_at=decision.verified_at,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _quality_flags(measurement: ExtractedMeasurementCandidate) -> list[str]:
    """Value modifiers the scalar ``Measurement`` has no dedicated field for, kept so a
    bound is never later read as a point estimate and an error is not lost."""
    flags: list[str] = []
    if measurement.comparator is not None:
        flags.append(f"bound:{measurement.comparator}")
    if measurement.uncertainty is not None:
        flags.append(f"uncertainty:{measurement.uncertainty}")
    return flags


def _run_from_measurement(
    measurement: ExtractedMeasurementCandidate, decision: VerificationDecision
) -> ExperimentRun:
    provenance = _provenance(measurement, decision)
    scalar = Measurement(
        name=measurement.measurement_name,
        value=measurement.parsed_value,
        unit=measurement.unit,
        quality=MeasurementQuality.VALID,
        quality_flags=_quality_flags(measurement),
    )
    observation = Observation(
        observation_id=f"{measurement.candidate_id}:obs",
        time_point=_time_point(measurement, decision),
        measurements=[scalar],
        conditions=_conditions(measurement),
    )
    return ExperimentRun(
        # Stated explicitly rather than relying on the default: literature is a *producer*
        # of canonical runs, and the version it wrote against should be visible here.
        schema_version=SCHEMA_VERSION,
        run_id=f"{RUN_ID_PREFIX}:{measurement.candidate_id}",
        provenance=provenance,
        conditions=_conditions(measurement),
        observations=[observation],
    )
