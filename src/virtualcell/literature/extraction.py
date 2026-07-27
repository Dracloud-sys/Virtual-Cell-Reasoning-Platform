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
from enum import StrEnum
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
from virtualcell.literature.documents import ArticleDocument, TableCell


class StatisticKind(StrEnum):
    """A table column that reports a *statistic about* a measurement, not the
    measurement itself. These are never turned into biological measurements."""

    P_VALUE = "p_value"
    ADJUSTED_P_VALUE = "adjusted_p_value"
    Q_VALUE_FDR = "q_value_fdr"
    CONFIDENCE_INTERVAL = "confidence_interval"
    SAMPLE_SIZE = "sample_size"
    DISPERSION = "dispersion"  # SD / SEM / SE / error


# Label -> statistic classification. Order matters: the more specific adjusted/q
# forms are checked before the bare "p".
_STATISTIC_PATTERNS: tuple[tuple[re.Pattern[str], StatisticKind], ...] = (
    (
        re.compile(r"^(adj(usted)?[\s._-]*p([\s._-]*val(ue)?)?|p[\s._-]*adj)$"),
        StatisticKind.ADJUSTED_P_VALUE,
    ),
    (re.compile(r"^(q([\s._-]*val(ue)?)?|fdr)$"), StatisticKind.Q_VALUE_FDR),
    (re.compile(r"^p([\s._-]*val(ue)?)?$"), StatisticKind.P_VALUE),
    (
        re.compile(r"^((95%?[\s._-]*)?c\.?i\.?|confidence[\s._-]*interval)$"),
        StatisticKind.CONFIDENCE_INTERVAL,
    ),
    (re.compile(r"^(n|sample[\s._-]*size)$"), StatisticKind.SAMPLE_SIZE),
    (
        re.compile(
            r"^(s\.?d\.?|std(ev)?|standard[\s._-]*deviation|s\.?e\.?m?\.?|standard[\s._-]*error|error)$"
        ),
        StatisticKind.DISPERSION,
    ),
)


def classify_statistic(label: str | None) -> StatisticKind | None:
    """Classify a table label as a statistic column, or ``None`` if it is not one.

    Deliberately conservative and exact-ish: it matches well-known statistic column
    names only. It does not guess from a value, and it invents no biology.
    """
    text = (label or "").strip().lower()
    if not text:
        return None
    for pattern, kind in _STATISTIC_PATTERNS:
        if pattern.match(text):
            return kind
    return None


class ExtractionTask(BaseModel):
    """What to look for. Extraction is targeted, never "grab every number"."""

    target_measurements: list[str] = Field(default_factory=list)
    # RESERVED — not used for filtering. Matching free-text contexts against captions
    # or headers would either over-filter (a context like "bovine preadipocyte" rarely
    # appears verbatim in a results table) or require fuzzy/semantic matching, i.e.
    # inventing policy. Supplying it produces an explicit warning rather than being
    # silently ignored; a real context policy is future work.
    target_contexts: list[str] = Field(default_factory=list)
    # Per-*document* cap (kept name for compatibility) and a run-wide cap across all
    # documents and candidate buckets. The agent enforces both; the deterministic
    # extractor honours the per-document cap on its own output.
    max_candidates: int = Field(default=200, ge=1, le=2000)
    max_total_candidates: int = Field(default=1000, ge=1, le=10000)


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
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_UNCERTAINTY = re.compile(r"(?:±|\+/-|\+-)\s*([-+]?\d+(?:\.\d+)?)")
# "1,234" is ambiguous (thousands separator vs decimal comma). Rather than guess, a
# digit-comma-digit value stays UNPARSED with its raw text preserved.
_AMBIGUOUS_SEPARATOR = re.compile(r"\d,\d")
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
    bound, not a point estimate); ``increased`` / ``NS`` stay UNPARSED with no number;
    ``1,234`` stays UNPARSED because the separator is ambiguous.
    """
    raw = text.strip()
    if raw.lower() in _NON_NUMERIC_TOKENS:
        return ParsedValue(raw_value=raw)
    if _AMBIGUOUS_SEPARATOR.search(raw):
        # Thousands separator or decimal comma? Refuse to guess; keep the raw text.
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

    value = float(number.group(0))
    tail = rest[number.end() :]

    uncertainty = None
    unc = _UNCERTAINTY.search(tail)
    if unc:
        uncertainty = float(unc.group(1))
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
    if task.target_contexts:
        result.warnings.append(
            "target_contexts is reserved and does not filter extraction in this version; "
            f"ignored: {task.target_contexts}"
        )

    seen_statistic_columns: set[str] = set()
    seen_ambiguous: set[str] = set()
    for table in document.tables:
        for cell in table.cells:
            if len(result.measurements) >= task.max_candidates:
                result.warnings.append(f"stopped at max_candidates={task.max_candidates}")
                return result
            row_target = _match_target(cell.row_label, task.target_measurements)
            col_target = _match_target(cell.column_label, task.target_measurements)
            if row_target is not None and col_target is not None:
                # Both axes name a target: which is the measurement is ambiguous. Do
                # not guess an axis — skip and record it once per table position.
                key = f"{table.table_id}:{cell.row_index}:{cell.column_index}"
                if key not in seen_ambiguous:
                    seen_ambiguous.add(key)
                    result.warnings.append(
                        f"table {table.table_id}: cell at (row {cell.row_index}, column "
                        f"{cell.column_index}) matches a target on both axes; not extracted"
                    )
                continue
            if row_target is not None:
                target, group = row_target, cell.column_label
            elif col_target is not None:
                target, group = col_target, cell.row_label
            else:
                continue
            if not cell.text.strip():
                continue
            # Skip the label cell itself (its text is the row label, not a value).
            if _normalize(cell.text) == _normalize(cell.row_label) and cell.column_index == 0:
                continue

            # The opposite axis identifies the group/condition. If it is really a
            # statistic column (p-value, FDR, n, SD/SEM, CI), its number is a statistic
            # *about* the measurement, not the measurement — never extract it as one.
            group_statistic = classify_statistic(group)
            if group_statistic is not None:
                key = f"{table.table_id}:{group}"
                if key not in seen_statistic_columns:
                    seen_statistic_columns.add(key)
                    result.warnings.append(
                        f"table {table.table_id}: column {group!r} classified as "
                        f"{group_statistic.value}; not extracted as a "
                        f"{target!r} measurement"
                    )
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
                    # When the caller explicitly targeted a statistic, record it as such
                    # rather than passing it off as a biological measurement.
                    statistic=(k.value if (k := classify_statistic(target)) else None),
                    parse_status=parsed.parse_status,
                    extraction_method=ExtractionMethod.DETERMINISTIC_TABLE,
                    extraction_confidence=0.9 if parsed.parse_status is ParseStatus.PARSED else 0.4,
                    source_locator=SourceLocator(
                        article=document.article,
                        source_kind=SourceKind.TABLE,
                        table_id=table.table_id,
                        row_index=cell.row_index,
                        column_index=cell.column_index,
                        row_label=cell.row_label,
                        column_label=cell.column_label,
                        source_text=cell.text,
                    ),
                )
            )
    return result


# --- source anchoring (extraction integrity, NOT verification) ---------------


def _matched_table_cell(
    document: ArticleDocument, locator: SourceLocator
) -> tuple[TableCell | None, list[str]]:
    """Return the single cell that satisfies *all* the locator's table constraints.

    Checking text / row_label / column_label independently would accept a locator
    assembled from parts of different cells (cite TERT's 2.4 while claiming column B,
    whose real value is 9). Constraints are therefore applied per candidate cell.
    """
    table = next((t for t in document.tables if t.table_id == locator.table_id), None)
    if table is None:
        return None, [f"unknown table_id {locator.table_id!r}"]

    candidates = table.cells
    if locator.row_index is not None or locator.column_index is not None:
        if locator.row_index is None or locator.column_index is None:
            return None, ["a table locator must give both row_index and column_index, or neither"]
        cell = table.cell(locator.row_index, locator.column_index)
        if cell is None:
            return None, [
                f"no cell at (row {locator.row_index}, column {locator.column_index}) "
                f"in table {locator.table_id!r}"
            ]
        candidates = [cell]

    matches = [
        c
        for c in candidates
        if c.text == locator.source_text
        and (locator.row_label is None or c.row_label == locator.row_label)
        and (locator.column_label is None or c.column_label == locator.column_label)
    ]
    if not matches:
        return None, [
            f"no single cell in table {locator.table_id!r} satisfies the locator's "
            "coordinates, row/column labels and source_text together"
        ]
    return matches[0], []


def _table_locator_errors(document: ArticleDocument, locator: SourceLocator) -> list[str]:
    return _matched_table_cell(document, locator)[1]


def _prose_locator_errors(document: ArticleDocument, locator: SourceLocator) -> list[str]:
    """Anchor abstract/section text to the *specific* place it claims to come from."""
    if locator.source_kind is SourceKind.ABSTRACT:
        if not document.abstract or locator.source_text not in document.abstract:
            return ["source_text not found in the abstract"]
        return []
    # SECTION: must name a section, and the text must be in *that* section.
    if not locator.section_title:
        return ["a section locator must carry a section_title"]
    section = document.section(title=locator.section_title)
    if section is None:
        return [f"unknown section_title {locator.section_title!r}"]
    if locator.source_text not in section.text:
        return [f"source_text not found in section {locator.section_title!r}"]
    return []


def _locator_errors(document: ArticleDocument, locator: SourceLocator) -> list[str]:
    if locator.article != document.article:
        return [f"locator article {locator.article!r} does not match the document"]
    if locator.source_kind is SourceKind.TABLE:
        return _table_locator_errors(document, locator)
    if locator.source_kind in (SourceKind.ABSTRACT, SourceKind.SECTION):
        return _prose_locator_errors(document, locator)
    # Figures and supplementary files are not parsed, so a locator claiming one cannot
    # be checked against anything. Reject rather than appear to support it.
    return [
        f"source_kind {locator.source_kind.value!r} is not supported by the current "
        "parser and cannot be source-anchored"
    ]


def _floats_equal(a: float | None, b: float | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) < 1e-9


def _value_integrity_errors(candidate: ExtractedMeasurementCandidate) -> list[str]:
    """The value-parsing contract, enforced on *every* extractor (LLM included).

    ``raw_value`` must be the verbatim cited text, and re-running the conservative
    ``parse_value_text`` on it must reproduce the candidate's parsed_value /
    comparator / uncertainty / unit / parse_status. So an LLM cannot invent a raw
    value, turn an ambiguous ``1,234`` into a number, promote an uncertainty to the
    primary value, or ship a parse_status that contradicts its own value.
    """
    raw = candidate.raw_value
    if raw is None:
        return ["measurement has no raw_value to verify"]
    locator = candidate.source_locator
    errors: list[str] = []
    if locator.source_kind is SourceKind.TABLE:
        if raw.strip() != locator.source_text.strip():
            errors.append("raw_value does not equal the cited cell text")
    elif not _independent_span_exists(locator.source_text, raw):
        errors.append("raw_value is not an independent value span of the cited source text")

    reparse = parse_value_text(raw)
    if candidate.parse_status is not reparse.parse_status:
        errors.append("parse_status disagrees with a conservative re-parse of raw_value")
    if not _floats_equal(candidate.parsed_value, reparse.parsed_value):
        errors.append("parsed_value disagrees with a conservative re-parse of raw_value")
    if not _floats_equal(candidate.uncertainty, reparse.uncertainty):
        errors.append("uncertainty disagrees with a conservative re-parse of raw_value")
    if candidate.comparator != reparse.comparator:
        errors.append("comparator disagrees with a conservative re-parse of raw_value")
    if candidate.unit != reparse.unit:
        errors.append("unit disagrees with a conservative re-parse of raw_value")
    return errors


def _name_matches_label(name: str, label: str | None) -> bool:
    """Does a measurement name correspond to a cell axis label, the same way the
    deterministic extractor assigned it (target token contained in the label)?"""
    return _match_target(label, [name]) is not None


# A *complete* numeric token: optional sign, integer part (with digit-grouping
# commas), optional decimal, optional scientific-notation exponent. Kept in sync with
# ``parse_value_text``'s notion of a number (comma between digits stays UNPARSED). Used
# to reject a candidate raw value that slices through part of a source number.
_NUMERIC_TOKEN = re.compile(r"[-+]?\d+(?:,\d+)*(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _independent_span_exists(source_text: str, raw: str) -> bool:
    """Is ``raw`` present in ``source_text`` as a value span that does not slice
    through a numeric token?

    The source's *complete* numeric tokens are identified first; an occurrence of
    ``raw`` is independent only when neither boundary falls in the middle of one of
    those tokens. So a mantissa/exponent fragment (``4``/``-4`` inside ``1e-4``,
    ``10``/``e10`` inside ``2.4e10``), a decimal fragment (``.4`` inside ``12.4``), a
    truncation (``2.4`` inside ``2.40``) and a digit-embedded substring (``2.4`` inside
    ``12.4``, ``24`` inside ``1234``) are all rejected — while a whitespace/
    punctuation-bounded value, optionally wrapped in a comparator or paired with an
    uncertainty (``< 2.4``, ``2.4 ± 0.3``, ``-1.2e-4``), is accepted. One clean
    occurrence is enough even if another sits inside a larger number.
    """
    if not raw:
        return False
    tokens = [(m.start(), m.end()) for m in _NUMERIC_TOKEN.finditer(source_text)]
    start = 0
    while (idx := source_text.find(raw, start)) != -1:
        end = idx + len(raw)
        # A token straddling either boundary means ``raw`` covers only part of it.
        cuts = any(ts < idx < te or ts < end < te for ts, te in tokens)
        if not cuts:
            return True
        start = idx + 1
    return False


def _target_tokens(text: str) -> list[str]:
    """Case-folded, Unicode-preserving tokens of ``text``.

    Uses ``casefold`` (fuller Unicode case handling than ``lower``) and a Unicode
    ``\\w`` split, so Greek and other non-ASCII letters survive: ``γH2AX`` and ``H2AX``
    tokenize differently and are never conflated, and ``β-actin`` keeps its ``β`` token
    distinct from ``actin``. No transliteration, no synonymy — ``γ`` is not ``gamma``.
    """
    return re.findall(r"\w+", text.casefold())


def _target_in_text(target: str, text: str) -> bool:
    """Whole-token (or whole-phrase) lexical match of ``target`` in ``text``.

    Deterministic and conservative: the target's token(s) must appear as consecutive
    whole tokens. No fuzzy matching, no synonyms — ``TERT`` never matches inside
    ``XTERTY``, and ``γH2AX`` never matches a plain ``H2AX``.
    """
    tokens = _target_tokens(text)
    target_tokens = _target_tokens(target)
    if not target_tokens:
        return False
    n = len(target_tokens)
    return any(tokens[i : i + n] == target_tokens for i in range(len(tokens) - n + 1))


def _measurement_target_errors(
    document: ArticleDocument,
    candidate: ExtractedMeasurementCandidate,
    task: ExtractionTask,
) -> list[str]:
    """Extraction-integrity gate on the candidate's *meaning* — the same target
    boundary the deterministic extractor obeys, applied to every extractor.

    An LLM must not smuggle in an unrequested measurement, rename the cited cell, or
    invent a sample_group: the name must be a requested target and must match one of
    the cited cell's axis labels, and a stated group must match the *opposite* axis of
    the SAME cell. This is not verification — it does not judge whether the source
    supports the claim, only that the claim is about the cell it cites.
    """
    if _match_target(candidate.measurement_name, task.target_measurements) is None:
        return [
            f"measurement_name {candidate.measurement_name!r} is not a requested target "
            f"({task.target_measurements})"
        ]
    locator = candidate.source_locator
    if locator.source_kind is not SourceKind.TABLE:
        # Prose: bind the value to a requested target under Unicode-preserving
        # identity. The name must *exactly* (token-for-token) be a requested target —
        # so ``H2AX`` cannot stand in for a requested ``γH2AX`` — must actually appear
        # as a whole token in the cited span, and no *other* requested target may
        # co-occur, otherwise which target the value binds to is ambiguous.
        name_key = tuple(_target_tokens(candidate.measurement_name))
        if not any(tuple(_target_tokens(t)) == name_key for t in task.target_measurements):
            return ["measurement_name does not exactly match a requested target"]
        if not _target_in_text(candidate.measurement_name, locator.source_text):
            return ["measurement_name does not appear as a whole word in the cited source text"]
        distinct = {
            tuple(_target_tokens(t))
            for t in task.target_measurements
            if _target_in_text(t, locator.source_text)
        }
        if len(distinct) > 1:
            return ["multiple requested targets appear in the cited span; the binding is ambiguous"]
        return []
    cell, errors = _matched_table_cell(document, locator)
    if errors or cell is None:
        return []  # locator errors are reported by the locator check; avoid duplicates

    name_on_row = _name_matches_label(candidate.measurement_name, cell.row_label)
    name_on_col = _name_matches_label(candidate.measurement_name, cell.column_label)
    if name_on_row and name_on_col:
        return ["measurement axis is ambiguous (name matches both the row and column label)"]
    if not (name_on_row or name_on_col):
        return ["measurement_name does not match the cited cell's row or column label"]
    if candidate.sample_group is not None:
        # The group must be the label on the axis the measurement name did NOT match.
        opposite = cell.column_label if name_on_row else cell.row_label
        if _normalize(candidate.sample_group) != _normalize(opposite):
            return ["sample_group does not match the cited cell's opposite-axis label"]
    return []


def accept_candidates(
    document: ArticleDocument,
    result: LiteratureExtractionResult,
    task: ExtractionTask | None = None,
) -> tuple[LiteratureExtractionResult, list[str]]:
    """Keep only candidates whose source span really exists in ``document`` (and, when
    ``task`` is given, whose *meaning* matches the cited cell and the requested targets).

    This is the acceptance boundary every extractor (including an LLM) must pass: a
    fabricated locator, a number absent from the cited span, or a candidate about an
    unrequested/mismatched measurement is rejected here. Passing does NOT mean the
    candidate is verified — that is PR8d.
    """
    accepted = LiteratureExtractionResult(warnings=list(result.warnings))
    rejected: list[str] = []

    for measurement in result.measurements:
        errors = _locator_errors(document, measurement.source_locator)
        if not errors:
            errors = _value_integrity_errors(measurement)
        if not errors and task is not None:
            errors = _measurement_target_errors(document, measurement, task)
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
