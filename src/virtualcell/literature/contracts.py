"""Typed contracts for the literature pipeline.

Three epistemic levels are kept strictly separate, and this separation is the
whole point of the pipeline:

1. **Article metadata** (:class:`ArticleRecord`) — a paper exists and is described.
   This is *not* a biological claim and never carries an evidence tier.
2. **Extraction candidates** (:class:`ExtractedMeasurementCandidate`,
   :class:`ExtractedClaimCandidate`, :class:`AuthorInterpretationCandidate`) — what
   a paper *appears* to report, each anchored to a :class:`SourceLocator`. A
   candidate is a proposal, not a fact.
3. **Verification** (:class:`VerificationDecision`) — a deterministic gate that
   decides whether a candidate is confirmed against its source text.

``extraction_confidence`` (how sure the extractor is about the mapping),
``verification_status`` (whether the source confirms it), and a downstream
evidence tier (how strongly reasoning should weight it) are three independent axes.
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


class LiteratureQuery(BaseModel):
    """A research question plus structured filters. Unbounded search is disallowed."""

    query_text: str
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


def _deterministic_candidate_id(model: BaseModel) -> str:
    """A stable SHA-256 id over a candidate's *content* (excluding the id and the
    mutable verification status), so re-running extraction on the same source span
    yields the same id — an auditable, reproducible reference."""
    payload = model.model_dump(mode="json", exclude={"candidate_id", "verification_status"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:32]


class _Candidate(BaseModel):
    """Shared candidate behavior: a content-derived ``candidate_id`` and a
    proposal-time ``verification_status`` (authoritative status lives on the
    :class:`VerificationDecision`)."""

    candidate_id: str = ""
    extraction_method: ExtractionMethod
    extraction_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    verification_status: VerificationStatus = VerificationStatus.PENDING_REVIEW

    @model_validator(mode="after")
    def _ensure_candidate_id(self) -> _Candidate:
        if not self.candidate_id:
            self.candidate_id = _deterministic_candidate_id(self)
        return self


class ExtractedClaimCandidate(_Candidate):
    """A qualitative subject-predicate-object claim proposed from a source."""

    subject: str
    predicate: str
    object: str
    qualifiers: dict[str, str] = Field(default_factory=dict)
    source_locator: SourceLocator


class ExtractedMeasurementCandidate(_Candidate):
    """A quantitative observation proposed from a source. Only this — once
    verified — becomes a canonical measurement."""

    sample_group: str | None = None
    species: str | None = None
    cell_type: str | None = None
    time_point: str | None = None  # verbatim as written; interpreted at conversion
    measurement_name: str
    value: float | int | str | None = None
    unit: str | None = None
    normalization: str | None = None
    control: str | None = None
    assay: str | None = None
    statistic: str | None = None
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


class VerificationDecision(BaseModel):
    """The deterministic gate's decision about one candidate, referenced by id.

    ``VerificationDecision`` is the *authoritative* source of a candidate's verified
    status; a candidate carries only a proposal-time status, and the bundle rejects
    any disagreement (see :meth:`LiteratureEvidenceBundle._check_candidate_linkage`).
    """

    candidate_id: str
    candidate_kind: str  # "measurement" | "claim" | "author_interpretation"
    status: VerificationStatus
    reasons: list[str] = Field(default_factory=list)


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
    claims: list[ExtractedClaimCandidate] = Field(default_factory=list)
    measurements: list[ExtractedMeasurementCandidate] = Field(default_factory=list)
    author_interpretations: list[AuthorInterpretationCandidate] = Field(default_factory=list)
    verification_decisions: list[VerificationDecision] = Field(default_factory=list)
    canonical_runs: list[ExperimentRun] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_candidate_linkage(self) -> LiteratureEvidenceBundle:
        candidates = [*self.claims, *self.measurements, *self.author_interpretations]
        ids = [c.candidate_id for c in candidates]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate candidate_id(s): {duplicates}")
        status_by_id = {c.candidate_id: c.verification_status for c in candidates}
        for decision in self.verification_decisions:
            if decision.candidate_id not in status_by_id:
                raise ValueError(
                    f"verification decision references unknown candidate_id "
                    f"{decision.candidate_id!r}"
                )
            if status_by_id[decision.candidate_id] != decision.status:
                raise ValueError(
                    f"candidate {decision.candidate_id!r} verification_status disagrees with "
                    "its VerificationDecision (the decision is authoritative)"
                )
        return self
