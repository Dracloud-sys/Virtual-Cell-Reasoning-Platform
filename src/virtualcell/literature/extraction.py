"""Source-grounded candidate extraction (PR8c-2/3).

Two layers, deliberately separate:

* **Deterministic extraction** reads *structured* table cells only. It is targeted:
  a number is turned into a candidate only when its row/column label matches a
  requested measurement in the :class:`ExtractionTask` — "the paper contains a
  number" is never sufficient. Values are kept split (raw vs parsed vs comparator vs
  uncertainty) so a bound is never stored as a point estimate and text with no number
  never gains one.
* **Structured LLM extraction** is an optional, injected
  :class:`StructuredLiteratureExtractor`. Its proposals are *not* trusted: every
  candidate must pass :func:`accept_candidates`, which re-checks the locator and the
  numbers against the actual document.

Acceptance is **extraction integrity** ("this source span really exists and really
contains this text"), not verification ("this span supports the claim"). Verification
is PR8d. Everything produced here is unverified: this module never creates a
:class:`VerificationDecision`.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from virtualcell.literature.contracts import (
    AuthorInterpretationCandidate,
    ExtractedClaimCandidate,
    ExtractedMeasurementCandidate,
    ExtractionMethod,
    ParseStatus,
    SourceKind,
    SourceLocator,
)
from virtualcell.literature.documents import ArticleDocument


class ExtractionTask(BaseModel):
    """What to look for. Extraction is targeted, never "grab every number"."""

    target_measurements: list[str] = Field(default_factory=list)
    target_contexts: list[str] = Field(default_factory=list)
    max_candidates: int = Field(default=200, ge=1, le=2000)


class LiteratureExtractionResult(BaseModel):
    """Candidates proposed from one document. All are unverified by construction."""

    measurements: list[ExtractedMeasurementCandidate] = Field(default_factory=list)
    claims: list[ExtractedClaimCandidate] = Field(default_factory=list)
    author_interpretations: list[AuthorInterpretationCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@runtime_checkable
class StructuredLiteratureExtractor(Protocol):
    """An optional structured extractor (e.g. LLM-backed).

    Deliberately NOT the narrative ``LLMBackend.answer`` contract: this returns typed,
    schema-validated candidates, each of which must carry a real SourceLocator and
    survive :func:`accept_candidates`.
    """

    name: str

    def extract(
        self, document: ArticleDocument, task: ExtractionTask
    ) -> LiteratureExtractionResult: ...


# --- value parsing -----------------------------------------------------------

_COMPARATOR = re.compile(r"^\s*(<=|>=|≤|≥|<|>|~|≈)\s*")
_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")
_UNCERTAINTY = re.compile(r"(?:±|\+/-|\+-)\s*([-+]?\d+(?:[.,]\d+)?)")
_UNIT_AFTER = re.compile(
    r"^\s*[-\s]?(fold|%|percent|h|hr|hrs|hour|hours|day|days|min|minutes|"
    r"nm|µm|um|mm|cm|ml|µl|ul|mg|µg|ug|ng|kda|bp|kb)\b",
    re.IGNORECASE,
)
_NON_NUMERIC_TOKENS = {"ns", "nd", "n/a", "na", "-", "—", ""}

_COMPARATOR_CANON = {"≤": "<=", "≥": ">=", "≈": "~"}


class ParsedValue(BaseModel):
    """The outcome of reading one raw value string. Nothing is invented."""

    raw_value: str
    parsed_value: float | None = None
    comparator: str | None = None
    uncertainty: float | None = None
    unit: str | None = None
    parse_status: ParseStatus = ParseStatus.UNPARSED


def parse_value_text(text: str) -> ParsedValue:
    """Split a raw cell/span into value / comparator / uncertainty / unit.

    Conservative by design: ``2.4`` parses; ``2.4-fold`` parses with a unit;
    ``2.4 ± 0.3`` keeps the error separately; ``<0.05`` keeps the comparator (it is a
    bound, not a point estimate); ``increased`` / ``NS`` stay UNPARSED with no number.
    """
    raw = text.strip()
    if raw.lower() in _NON_NUMERIC_TOKENS:
        return ParsedValue(raw_value=raw)

    rest = raw
    comparator = None
    match = _COMPARATOR.match(rest)
    if match:
        comparator = _COMPARATOR_CANON.get(match.group(1), match.group(1))
        rest = rest[match.end() :]

    number = _NUMBER.search(rest)
    if not number:
        # No number anywhere: qualitative text ("increased"). Never fabricate one.
        return ParsedValue(raw_value=raw, comparator=comparator)

    value = float(number.group(0).replace(",", "."))
    tail = rest[number.end() :]

    uncertainty = None
    unc = _UNCERTAINTY.search(tail)
    if unc:
        uncertainty = float(unc.group(1).replace(",", "."))
        tail = tail[unc.end() :]

    unit = None
    unit_match = _UNIT_AFTER.match(tail)
    if unit_match:
        unit = unit_match.group(1).lower()

    return ParsedValue(
        raw_value=raw,
        parsed_value=value,
        comparator=comparator,
        uncertainty=uncertainty,
        unit=unit,
        parse_status=ParseStatus.PARSED,
    )


# --- deterministic table extraction ------------------------------------------


def _normalize(label: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (label or "").lower())


def _match_target(label: str | None, targets: list[str]) -> str | None:
    """Match a row/column label to a requested measurement (normalized, exact-ish)."""
    key = _normalize(label)
    if not key:
        return None
    for target in targets:
        target_key = _normalize(target)
        if target_key and (key == target_key or target_key in key):
            return target
    return None


def extract_deterministic(
    document: ArticleDocument, task: ExtractionTask
) -> LiteratureExtractionResult:
    """Extract measurement candidates from structured table cells only.

    A cell becomes a candidate only when one of its axis labels matches a requested
    measurement; the opposite axis label is carried verbatim as ``sample_group`` (it
    is copied, never interpreted). Nothing is extracted from prose here.
    """
    result = LiteratureExtractionResult()
    if not task.target_measurements:
        result.warnings.append("no target_measurements requested; nothing extracted")
        return result

    for table in document.tables:
        for cell in table.cells:
            if len(result.measurements) >= task.max_candidates:
                result.warnings.append(f"stopped at max_candidates={task.max_candidates}")
                return result
            target = _match_target(cell.row_label, task.target_measurements)
            group = cell.column_label
            if target is None:
                target = _match_target(cell.column_label, task.target_measurements)
                group = cell.row_label
            if target is None or not cell.text.strip():
                continue
            # Skip the label cell itself (its text is the row label, not a value).
            if _normalize(cell.text) == _normalize(cell.row_label) and cell.column_index == 0:
                continue

            parsed = parse_value_text(cell.text)
            result.measurements.append(
                ExtractedMeasurementCandidate(
                    measurement_name=target,
                    sample_group=group,
                    raw_value=parsed.raw_value,
                    parsed_value=parsed.parsed_value,
                    comparator=parsed.comparator,
                    uncertainty=parsed.uncertainty,
                    unit=parsed.unit,
                    parse_status=parsed.parse_status,
                    extraction_method=ExtractionMethod.DETERMINISTIC_TABLE,
                    extraction_confidence=0.9 if parsed.parse_status is ParseStatus.PARSED else 0.4,
                    source_locator=SourceLocator(
                        article=document.article,
                        source_kind=SourceKind.TABLE,
                        table_id=table.table_id,
                        row_label=cell.row_label,
                        column_label=cell.column_label,
                        source_text=cell.text,
                    ),
                )
            )
    return result


# --- source anchoring (extraction integrity, NOT verification) ---------------


def _locator_errors(document: ArticleDocument, locator: SourceLocator) -> list[str]:
    if locator.article != document.article:
        return [f"locator article {locator.article!r} does not match the document"]
    if locator.source_kind is SourceKind.TABLE:
        table = next((t for t in document.tables if t.table_id == locator.table_id), None)
        if table is None:
            return [f"unknown table_id {locator.table_id!r}"]
        cells = [c for c in table.cells if c.text == locator.source_text]
        if not cells:
            return [f"source_text not found in table {locator.table_id!r}"]
        if locator.row_label is not None and all(c.row_label != locator.row_label for c in cells):
            return [f"row_label {locator.row_label!r} does not match the cell"]
        if locator.column_label is not None and all(
            c.column_label != locator.column_label for c in cells
        ):
            return [f"column_label {locator.column_label!r} does not match the cell"]
        return []
    haystacks = [document.abstract or "", *(s.text for s in document.sections)]
    if not any(locator.source_text in h for h in haystacks):
        return ["source_text not found in the document text"]
    return []


def _value_is_in_source(candidate: ExtractedMeasurementCandidate) -> bool:
    """A parsed number must actually appear in the candidate's own source span."""
    if candidate.parsed_value is None:
        return True
    numbers = {
        float(n.replace(",", ".")) for n in _NUMBER.findall(candidate.source_locator.source_text)
    }
    return any(abs(candidate.parsed_value - n) < 1e-9 for n in numbers)


def accept_candidates(
    document: ArticleDocument, result: LiteratureExtractionResult
) -> tuple[LiteratureExtractionResult, list[str]]:
    """Keep only candidates whose source span really exists in ``document``.

    This is the acceptance boundary every extractor (including an LLM) must pass: a
    fabricated locator, or a number that is not present in the cited span, is
    rejected here. Passing does NOT mean the candidate is verified — that is PR8d.
    """
    accepted = LiteratureExtractionResult(warnings=list(result.warnings))
    rejected: list[str] = []

    for measurement in result.measurements:
        errors = _locator_errors(document, measurement.source_locator)
        if not errors and not _value_is_in_source(measurement):
            errors = [
                f"parsed_value {measurement.parsed_value!r} does not appear in the "
                "cited source text"
            ]
        if errors:
            rejected.append(f"measurement {measurement.measurement_name!r}: {'; '.join(errors)}")
        else:
            accepted.measurements.append(measurement)

    for claim in result.claims:
        errors = _locator_errors(document, claim.source_locator)
        if errors:
            rejected.append(f"claim {claim.subject!r}: {'; '.join(errors)}")
        else:
            accepted.claims.append(claim)

    for interpretation in result.author_interpretations:
        errors = _locator_errors(document, interpretation.source_locator)
        if errors:
            rejected.append(f"author interpretation: {'; '.join(errors)}")
        else:
            accepted.author_interpretations.append(interpretation)

    return accepted, rejected
