"""Typed contracts for the literature pipeline.

Three epistemic levels are kept strictly separate, and this separation is the
whole point of the pipeline:

1. **Article metadata** (:class:`ArticleRecord`) — a paper exists and is described.
   This is *not* a biological claim and never carries an evidence tier.
2. **Extraction candidates** (:class:`ExtractedMeasurementCandidate`,
   :class:`ExtractedClaimCandidate`, :class:`AuthorInterpretationCandidate`) — what
   a paper *appears* to report, each anchored to a :class:`SourceLocator`. A
   candidate is a proposal, not a fact.
3. **Verification** (:class:`VerificationDecision`) — a gate that decides whether a
   candidate is confirmed against its source text. This is the **single
   authoritative home of verification status**: a candidate carries none of its own,
   and one with no decision is implicitly unverified.

``extraction_confidence`` (how sure the extractor is about the mapping),
``VerificationDecision.status`` (whether the source confirms it), and a downstream
evidence tier (how strongly reasoning should weight it) are three independent axes.
A candidate's ``candidate_id`` is derived from its asserted content and source — it
is never assigned, so a decision can never be pinned to a forged or drifted proposal.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from virtualcell.core.experiment import ExperimentRun

# --- query -------------------------------------------------------------------

_MAX_RESULTS_CAP = 200
_MIN_YEAR = 1500
_MAX_YEAR = 2100


class QueryMode(StrEnum):
    """How ``query_text`` is turned into a provider query.

    ``terms`` (default) ANDs the sanitized word tokens — robust recall for a
    natural-language research question. ``phrase`` searches the exact phrase — high
    precision for a deliberate keyword phrase but low recall on prose. Neither mode
    invents synonyms, and both are deterministic for a given input.
    """

    TERMS = "terms"
    PHRASE = "phrase"


class LiteratureQuery(BaseModel):
    """A research question plus structured filters. Unbounded search is disallowed."""

    query_text: str
    query_mode: QueryMode = QueryMode.TERMS
    species: list[str] = Field(default_factory=list)
    cell_types: list[str] = Field(default_factory=list)
    genes: list[str] = Field(default_factory=list)
    phenotypes: list[str] = Field(default_factory=list)
    assays: list[str] = Field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None
    open_access_only: bool = False
    max_results: int = Field(default=25, ge=1, le=_MAX_RESULTS_CAP)

    @field_validator("query_text")
    @classmethod
    def _query_text_has_content(cls, v: str) -> str:
        # A query that sanitizes to nothing searchable (e.g. '""') is rejected here,
        # not turned into an empty provider query downstream.
        if not any(ch.isalnum() for ch in v):
            raise ValueError("query_text must contain searchable characters")
        return v

    @field_validator("species", "cell_types", "genes", "phenotypes", "assays")
    @classmethod
    def _drop_blank_terms(cls, v: list[str]) -> list[str]:
        return [t for t in v if t and t.strip()]

    @model_validator(mode="after")
    def _validate_years(self) -> LiteratureQuery:
        for year in (self.year_from, self.year_to):
            if year is not None and not (_MIN_YEAR <= year <= _MAX_YEAR):
                raise ValueError(f"year must be within [{_MIN_YEAR}, {_MAX_YEAR}]")
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("year_from must be <= year_to")
        return self


# --- article identity & metadata --------------------------------------------


def normalize_doi(doi: str | None) -> str | None:
    """Lower-case, strip a URL/`doi:` prefix and surrounding space — for comparison."""
    if doi is None:
        return None
    text = doi.strip().lower()
    text = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", text)
    return text or None


def normalize_title(title: str | None) -> str | None:
    """Collapse to lower-case alphanumerics — a last-resort dedup fallback only."""
    if title is None:
        return None
    text = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return text or None


class ArticleIdentifier(BaseModel):
    """Cross-provider identifiers. The DOI is stored as given; use
    :attr:`normalized_doi` for comparison so the original string is never lost."""

    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    provider_id: str | None = None

    @property
    def normalized_doi(self) -> str | None:
        return normalize_doi(self.doi)

    @model_validator(mode="after")
    def _require_one_identifier(self) -> ArticleIdentifier:
        if not any([self.doi, self.pmid, self.pmcid, self.provider_id]):
            raise ValueError(
                "ArticleIdentifier requires at least one of doi/pmid/pmcid/provider_id"
            )
        return self


class PublicationNoticeKind(StrEnum):
    """A publication-integrity notice. A correction/erratum/EoC is NOT a retraction."""

    RETRACTION = "retraction"
    CORRECTION = "correction"
    ERRATUM = "erratum"
    EXPRESSION_OF_CONCERN = "expression_of_concern"


class PublicationNotice(BaseModel):
    """A minimal typed record of a correction/retraction notice (not the full payload)."""

    kind: PublicationNoticeKind
    reference: str | None = None  # e.g. the corrective article's id, if given


class ArticleRecord(BaseModel):
    """Bibliographic metadata for one article. NOT a biological claim.

    A record with no abstract or no authors is still a valid record; the pipeline
    must not fabricate content to fill gaps. Retraction/correction signals from the
    provider are preserved (``notices``) so downstream review can see them, and a
    correction is never conflated with a retraction (``is_retracted``).
    """

    identifiers: ArticleIdentifier
    title: str | None = None
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    publication_year: int | None = None
    publication_types: list[str] = Field(default_factory=list)
    publication_status: str | None = None
    is_open_access: bool = False
    has_full_text: bool = False
    has_supplementary: bool = False
    is_retracted: bool = False
    notices: list[PublicationNotice] = Field(default_factory=list)
    provider: str | None = None
    source_url: str | None = None
    retrieved_at: datetime | None = None


class ProviderProvenance(BaseModel):
    """Auditable record of *how* a search was run."""

    provider: str
    query_sent: str
    query_mode: str | None = None
    # Which query_text tokens were searched and which were dropped (e.g. stopwords),
    # so a surprising result set can be explained from the audit trail alone.
    query_tokens_kept: list[str] = Field(default_factory=list)
    query_tokens_dropped: list[str] = Field(default_factory=list)
    retrieved_at: datetime
    hit_count: int | None = None
    page_size: int | None = None
    pages_fetched: int = 0

    @field_validator("retrieved_at")
    @classmethod
    def _require_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return v


class LiteratureSearchResult(BaseModel):
    """The raw (pre-dedup) result a provider returns for one query.

    ``warnings`` carries non-fatal issues (e.g. a malformed row skipped rather than
    failing the whole search); a hard provider failure raises instead.
    """

    provenance: ProviderProvenance
    articles: list[ArticleRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --- source anchoring & extraction candidates -------------------------------


class SourceKind(StrEnum):
    ABSTRACT = "abstract"
    SECTION = "section"
    TABLE = "table"
    FIGURE = "figure"
    SUPPLEMENTARY = "supplementary"


class ExtractionMethod(StrEnum):
    DETERMINISTIC_TEXT = "deterministic_text"
    DETERMINISTIC_TABLE = "deterministic_table"
    LLM_STRUCTURED = "llm_structured"


class VerificationStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    MACHINE_VERIFIED = "machine_verified"
    HUMAN_VERIFIED = "human_verified"
    REJECTED = "rejected"


def hash_source_text(text: str) -> str:
    """A stable SHA-256 content hash so a later verifier can detect source drift."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SourceLocator(BaseModel):
    """Where a candidate came from — every candidate must carry one, anchored to an
    auditable article identifier.

    ``source_text`` holds only the short span needed to verify the candidate; the
    full article is never copied. ``source_text_hash`` (SHA-256) is populated
    automatically from ``source_text``; a caller-supplied hash that disagrees with
    the text is rejected, so a stale hash can never accompany changed text.
    """

    article: ArticleIdentifier
    source_kind: SourceKind
    section_title: str | None = None
    table_id: str | None = None
    figure_id: str | None = None
    row_label: str | None = None
    column_label: str | None = None
    source_text: str
    source_text_hash: str | None = None

    @field_validator("source_text")
    @classmethod
    def _source_text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source_text must not be empty")
        return v

    @model_validator(mode="after")
    def _sync_hash(self) -> SourceLocator:
        expected = hash_source_text(self.source_text)
        if self.source_text_hash is None:
            self.source_text_hash = expected
        elif self.source_text_hash != expected:
            raise ValueError("source_text_hash does not match source_text")
        return self


# Operational fields excluded from the identity hash: they describe *how sure* an
# extractor was, not *what was claimed*, so they must not fork a candidate's identity.
_ID_EXCLUDED_FIELDS = frozenset({"candidate_id", "extraction_confidence"})


def _deterministic_candidate_id(model: BaseModel) -> str:
    """A stable SHA-256 id over a candidate's asserted content + source identity.

    ``extraction_confidence`` is excluded (re-scoring the same proposal must not
    change its id). ``extraction_method`` is **included**: a deterministic parse and
    an LLM proposal of the same fact are different *proposals* with different trust
    characteristics, and verification must be able to accept one and reject the other
    independently — merging them would hide which extractor produced what.
    """
    payload = model.model_dump(mode="json", exclude=set(_ID_EXCLUDED_FIELDS))
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:32]


class _Candidate(BaseModel):
    """Shared candidate behavior: an extraction *proposal* with a content-derived id.

    A candidate deliberately carries **no verification status** — status has exactly
    one authoritative home, :class:`VerificationDecision`. A candidate with no
    decision is implicitly unverified.
    """

    candidate_id: str = ""
    extraction_method: ExtractionMethod
    extraction_confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ensure_candidate_id(self) -> _Candidate:
        expected = _deterministic_candidate_id(self)
        if not self.candidate_id:
            self.candidate_id = expected
        elif self.candidate_id != expected:
            # Ids are derived, never assigned: a forged/stale id is rejected.
            raise ValueError("candidate_id does not match the candidate's content")
        return self


class ExtractedClaimCandidate(_Candidate):
    """A qualitative subject-predicate-object claim proposed from a source."""

    subject: str
    predicate: str
    object: str
    qualifiers: dict[str, str] = Field(default_factory=dict)
    source_locator: SourceLocator


class ParseStatus(StrEnum):
    """Whether a numeric value could be taken from the raw source text."""

    PARSED = "parsed"
    UNPARSED = "unparsed"


class ExtractedMeasurementCandidate(_Candidate):
    """A quantitative observation proposed from a source. Only this — once
    verified — becomes a canonical measurement.

    The value is kept *split*: ``raw_value`` is always the verbatim source text, and
    a number is only promoted to ``parsed_value`` when it is unambiguous. A
    comparator (``<0.05``) and an uncertainty (``2.4 ± 0.3``) are separate fields, so
    a bound is never stored as a point estimate and an error is never lost. Text with
    no number (``increased``, ``NS``) stays ``UNPARSED`` — a number is never invented.
    """

    sample_group: str | None = None
    species: str | None = None
    cell_type: str | None = None
    time_point: str | None = None  # verbatim as written; interpreted at conversion
    measurement_name: str
    raw_value: str | None = None
    parsed_value: float | None = None
    comparator: str | None = None  # "<", ">", "<=", ">=", "~"
    uncertainty: float | None = None
    unit: str | None = None
    normalization: str | None = None
    control: str | None = None
    assay: str | None = None
    statistic: str | None = None
    parse_status: ParseStatus = ParseStatus.UNPARSED
    source_locator: SourceLocator


class AuthorInterpretationCandidate(_Candidate):
    """An author's interpretation (Discussion/Conclusion) — kept apart from raw
    observation so a narrative ("cells escaped senescence") is never stored as data."""

    statement: str
    source_locator: SourceLocator


# --- relevance (search relevance only, NOT scientific strength) --------------


class RelevanceComponent(BaseModel):
    name: str
    matched: list[str] = Field(default_factory=list)
    weight: float
    score: float


class RelevanceResult(BaseModel):
    """Transparent, component-wise search relevance. This is retrieval relevance
    only — never reused as evidence strength or claim confidence."""

    article: ArticleIdentifier
    total_score: float
    matched_terms: list[str] = Field(default_factory=list)
    missing_critical_filters: list[str] = Field(default_factory=list)
    breakdown: list[RelevanceComponent] = Field(default_factory=list)


# --- verification & bundle ---------------------------------------------------


class CandidateKind(StrEnum):
    """Which candidate collection a decision refers to."""

    CLAIM = "claim"
    MEASUREMENT = "measurement"
    AUTHOR_INTERPRETATION = "author_interpretation"


class VerificationDecision(BaseModel):
    """The gate's decision about one candidate — the *only* home of verified status.

    A candidate carries no status of its own; one with no decision is implicitly
    unverified. At most one decision may exist per candidate.
    """

    candidate_id: str
    candidate_kind: CandidateKind
    status: VerificationStatus
    reasons: list[str] = Field(default_factory=list)
    verifier: str  # who/what decided, e.g. "deterministic_source_match" or "human:alice"
    method: str | None = None
    verified_at: datetime
    source_text_hash: str | None = None  # the source span the decision was made against

    @field_validator("verified_at")
    @classmethod
    def _require_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("verified_at must be timezone-aware")
        return v


class SourceFormat(StrEnum):
    """What a fetched document was parsed from."""

    JATS_XML = "jats_xml"
    ABSTRACT = "abstract"


class DocumentMetadata(BaseModel):
    """Auditable *metadata* about a fetched document — never its body.

    The bundle carries this, not the parsed text: the full article is never copied
    into an agent output. ``content_hash`` lets a later run detect that the source
    changed since extraction.
    """

    article: ArticleIdentifier
    source_format: SourceFormat
    content_hash: str
    provider: str | None = None
    source_url: str | None = None
    retrieved_at: datetime
    license: str | None = None
    section_count: int = 0
    table_count: int = 0
    warnings: list[str] = Field(default_factory=list)

    @field_validator("retrieved_at")
    @classmethod
    def _require_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return v


class DiscoveryRunStatus(StrEnum):
    """Machine-readable run outcome so a zero-result run is not confused with failure."""

    SUCCESS = "success"
    ZERO_RESULTS = "zero_results"
    PROVIDER_ERROR = "provider_error"


class LiteratureEvidenceBundle(BaseModel):
    """The full, auditable output of a literature run.

    Discovery fields (query/provenance/articles/relevance) are populated in PR8b;
    the extraction/verification/canonical fields have stable contracts and are
    filled by later slices. This bundle is never auto-written to the KnowledgeStore.
    ``run_status`` is the authoritative success/failure signal — callers must not
    infer failure from the presence of ``warnings``.
    """

    query: LiteratureQuery
    provider_provenance: ProviderProvenance
    run_status: DiscoveryRunStatus = DiscoveryRunStatus.SUCCESS
    articles: list[ArticleRecord] = Field(default_factory=list)
    relevance: list[RelevanceResult] = Field(default_factory=list)
    documents: list[DocumentMetadata] = Field(default_factory=list)
    claims: list[ExtractedClaimCandidate] = Field(default_factory=list)
    measurements: list[ExtractedMeasurementCandidate] = Field(default_factory=list)
    author_interpretations: list[AuthorInterpretationCandidate] = Field(default_factory=list)
    verification_decisions: list[VerificationDecision] = Field(default_factory=list)
    canonical_runs: list[ExperimentRun] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_candidate_linkage(self) -> LiteratureEvidenceBundle:
        kind_of: dict[str, CandidateKind] = {}
        for kind, items in (
            (CandidateKind.CLAIM, self.claims),
            (CandidateKind.MEASUREMENT, self.measurements),
            (CandidateKind.AUTHOR_INTERPRETATION, self.author_interpretations),
        ):
            for candidate in items:
                if candidate.candidate_id in kind_of:
                    raise ValueError(f"duplicate candidate_id: {candidate.candidate_id!r}")
                kind_of[candidate.candidate_id] = kind

        decided: set[str] = set()
        for decision in self.verification_decisions:
            if decision.candidate_id not in kind_of:
                raise ValueError(
                    f"verification decision references unknown candidate_id "
                    f"{decision.candidate_id!r}"
                )
            if kind_of[decision.candidate_id] is not decision.candidate_kind:
                raise ValueError(
                    f"decision candidate_kind {decision.candidate_kind.value!r} does not match "
                    f"candidate {decision.candidate_id!r}"
                )
            if decision.candidate_id in decided:
                raise ValueError(
                    f"more than one verification decision for candidate {decision.candidate_id!r}"
                )
            decided.add(decision.candidate_id)
        return self
