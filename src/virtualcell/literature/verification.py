"""Deterministic literature verification gate (PR8d-1).

The third of three deliberately separate layers:

1. **extraction candidate** — a source-grounded *proposal* (PR8c).
2. **verification decision** — this module: does the candidate still match the
   *current* document, and may it be machine-approved?
3. **canonical conversion** — PR8d-2 only; nothing here writes an ``ExperimentRun``,
   a ``canonical_runs`` entry, or the KnowledgeStore.

A candidate never carries a status of its own: :class:`VerificationDecision` is the
single authoritative home of verified status (a candidate with no decision is
implicitly unverified). This gate is *conservative*: only an exact, re-verified table
measurement is machine-approved; prose, claims, author interpretations, qualitative
values and statistics need human review; and anything whose source integrity no longer
holds is rejected rather than softened to pending.

To avoid inventing a second, divergent rulebook, integrity is decided by re-running
PR8c's own :func:`accept_candidates` boundary against the current document — the same
locator, exact-cell, value-integrity, target-binding and unsupported-notation rules.
"""

from __future__ import annotations

from datetime import UTC, datetime

from virtualcell.literature.contracts import (
    AuthorInterpretationCandidate,
    CandidateKind,
    ExtractedClaimCandidate,
    ExtractedMeasurementCandidate,
    ParseStatus,
    SourceKind,
    VerificationDecision,
    VerificationStatus,
)
from virtualcell.literature.documents import ArticleDocument
from virtualcell.literature.extraction import (
    ExtractionTask,
    LiteratureExtractionResult,
    accept_candidates,
)

# Stable, explicit provenance for every decision this gate makes.
VERIFIER = "deterministic_source_verifier"
METHOD = "exact_source_location_v1"


def verify_candidates(
    document: ArticleDocument,
    result: LiteratureExtractionResult,
    task: ExtractionTask,
    *,
    verified_at: datetime | None = None,
) -> list[VerificationDecision]:
    """Return one :class:`VerificationDecision` per candidate in ``result``.

    Pure and deterministic: input candidates are never mutated, at most one decision is
    produced per ``candidate_id`` (in input order — measurements, then claims, then
    author interpretations), and ``verified_at`` can be injected so time is testable. A
    missing clock defaults to timezone-aware UTC now.
    """
    when = verified_at or datetime.now(UTC)
    decisions: list[VerificationDecision] = []
    seen: set[str] = set()

    for measurement in result.measurements:
        if measurement.candidate_id in seen:
            continue
        seen.add(measurement.candidate_id)
        decisions.append(_verify_measurement(document, measurement, task, when))

    for claim in result.claims:
        if claim.candidate_id in seen:
            continue
        seen.add(claim.candidate_id)
        decisions.append(
            _verify_prose_only(
                document,
                claim,
                CandidateKind.CLAIM,
                "claim entailment requires human review",
                task,
                when,
            )
        )

    for interpretation in result.author_interpretations:
        if interpretation.candidate_id in seen:
            continue
        seen.add(interpretation.candidate_id)
        decisions.append(
            _verify_prose_only(
                document,
                interpretation,
                CandidateKind.AUTHOR_INTERPRETATION,
                "author interpretation requires human review",
                task,
                when,
            )
        )

    return decisions


def _decision(
    candidate_id: str,
    kind: CandidateKind,
    status: VerificationStatus,
    reasons: list[str],
    source_text_hash: str | None,
    verified_at: datetime,
) -> VerificationDecision:
    return VerificationDecision(
        candidate_id=candidate_id,
        candidate_kind=kind,
        status=status,
        reasons=reasons,
        verifier=VERIFIER,
        method=METHOD,
        verified_at=verified_at,
        source_text_hash=source_text_hash,
    )


def _pending_measurement_reasons(candidate: ExtractedMeasurementCandidate) -> list[str]:
    """Why an integrity-passing measurement still cannot be machine-verified.

    Only an exact, quantitative table cell is machine-approvable. Prose is a semantic
    judgement, a statistic is not a biological measurement, and an unparsed/qualitative
    value has no machine-checkable number.
    """
    reasons: list[str] = []
    if candidate.source_locator.source_kind is not SourceKind.TABLE:
        reasons.append("prose context requires semantic review")
    if candidate.statistic is not None:
        reasons.append("statistic candidate is not a biological measurement")
    if candidate.parse_status is not ParseStatus.PARSED or candidate.parsed_value is None:
        reasons.append("qualitative value cannot be machine-verified as a quantitative measurement")
    return reasons


def _verify_measurement(
    document: ArticleDocument,
    candidate: ExtractedMeasurementCandidate,
    task: ExtractionTask,
    verified_at: datetime,
) -> VerificationDecision:
    source_hash = candidate.source_locator.source_text_hash
    # Re-run PR8c's acceptance boundary against the *current* document. A failure here
    # is a source-integrity failure (drift, wrong coordinates, value mismatch, target
    # mismatch, unsupported notation) and is REJECTED — never softened to pending.
    accepted, rejected = accept_candidates(
        document, LiteratureExtractionResult(measurements=[candidate]), task
    )
    if not accepted.measurements:
        return _decision(
            candidate.candidate_id,
            CandidateKind.MEASUREMENT,
            VerificationStatus.REJECTED,
            rejected or ["source integrity check failed against the current document"],
            source_hash,
            verified_at,
        )

    reasons = _pending_measurement_reasons(candidate)
    if reasons:
        return _decision(
            candidate.candidate_id,
            CandidateKind.MEASUREMENT,
            VerificationStatus.PENDING_REVIEW,
            reasons,
            source_hash,
            verified_at,
        )
    return _decision(
        candidate.candidate_id,
        CandidateKind.MEASUREMENT,
        VerificationStatus.MACHINE_VERIFIED,
        ["exact table cell measurement re-verified against the current document"],
        source_hash,
        verified_at,
    )


def _verify_prose_only(
    document: ArticleDocument,
    candidate: ExtractedClaimCandidate | AuthorInterpretationCandidate,
    kind: CandidateKind,
    review_reason: str,
    task: ExtractionTask,
    verified_at: datetime,
) -> VerificationDecision:
    """Claims and author interpretations are only ever source-anchored, never
    machine-approved: an intact locator earns PENDING_REVIEW, a broken one REJECTED."""
    source_hash = candidate.source_locator.source_text_hash
    if kind is CandidateKind.CLAIM:
        result = LiteratureExtractionResult(claims=[candidate])
    else:
        result = LiteratureExtractionResult(author_interpretations=[candidate])
    accepted, rejected = accept_candidates(document, result, task)
    survivors = accepted.claims if kind is CandidateKind.CLAIM else accepted.author_interpretations
    if not survivors:
        return _decision(
            candidate.candidate_id,
            kind,
            VerificationStatus.REJECTED,
            rejected or ["source integrity check failed against the current document"],
            source_hash,
            verified_at,
        )
    return _decision(
        candidate.candidate_id,
        kind,
        VerificationStatus.PENDING_REVIEW,
        [review_reason],
        source_hash,
        verified_at,
    )
