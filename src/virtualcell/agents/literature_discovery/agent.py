"""LiteratureDiscoveryAgent — external paper discovery as a typed bundle.

This agent turns a research question into a :class:`LiteratureEvidenceBundle` of
article *metadata* and search *relevance*. It deliberately returns **no biological
`Claim`s**: discovery is not evidence. Extraction/verification/canonical conversion
are later slices; until a candidate is verified it must not be presented as a fact,
and nothing here is written to the KnowledgeStore.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError

from virtualcell.core.agent import AgentContext, BaseAgent
from virtualcell.core.contracts import AgentInput, AgentOutput
from virtualcell.literature.contracts import (
    ArticleRecord,
    DiscoveryRunStatus,
    LiteratureEvidenceBundle,
    LiteratureQuery,
    ProviderProvenance,
)
from virtualcell.literature.discovery import discover
from virtualcell.literature.documents import (
    ArticleDocument,
    JatsParseError,
    document_from_abstract,
    parse_jats,
)
from virtualcell.literature.extraction import (
    ExtractionTask,
    LiteratureExtractionResult,
    StructuredLiteratureExtractor,
    accept_candidates,
    extract_deterministic,
)
from virtualcell.literature.providers.base import LiteratureProvider, ProviderError
from virtualcell.literature.providers.europe_pmc import EuropePmcProvider

_QUERY_FIELDS = (
    "query_mode",
    "species",
    "cell_types",
    "genes",
    "phenotypes",
    "assays",
    "year_from",
    "year_to",
    "open_access_only",
    "max_results",
)
_DEFAULT_EXTRACT_ARTICLES = 5
_MAX_EXTRACT_ARTICLES = 20
# The exception boundary for an optional third-party extractor. Deliberately explicit:
# a broad `except Exception` would also swallow MemoryError, and BaseException would
# swallow KeyboardInterrupt/SystemExit.
_EXTRACTOR_ERRORS = (ValueError, TypeError, KeyError, AttributeError, RuntimeError)


class LiteratureQueryError(ValueError):
    """Raised when an AgentInput does not carry a valid literature query."""


class LiteratureDiscoveryAgent(BaseAgent):
    name = "literature_discovery"
    responsibilities = "Discover external papers and return metadata + relevance (no claims)."

    def __init__(
        self,
        context: AgentContext | None = None,
        provider: LiteratureProvider | None = None,
        extractor: StructuredLiteratureExtractor | None = None,
    ) -> None:
        super().__init__(context)
        # A provider may be injected (tests) or supplied via services; otherwise the
        # default Europe PMC connector (real network) is used.
        self.provider = (
            provider or self.context.services.get("literature_provider") or EuropePmcProvider()
        )
        # An optional structured (e.g. LLM) extractor. None => deterministic only.
        self.extractor = extractor or self.context.services.get("literature_extractor")

    def build_query(self, inputs: AgentInput) -> LiteratureQuery:
        payload = {k: v for k, v in inputs.context.items() if k in _QUERY_FIELDS}
        try:
            return LiteratureQuery(query_text=inputs.query, **payload)
        except ValidationError as exc:
            raise LiteratureQueryError(f"invalid literature query: {exc}") from exc

    def build_task(self, inputs: AgentInput) -> ExtractionTask | None:
        """An extraction task, only when the caller asked for one with targets."""
        if not inputs.context.get("extract"):
            return None
        payload = {
            "target_measurements": inputs.context.get("target_measurements", []),
            "target_contexts": inputs.context.get("target_contexts", []),
        }
        if "max_candidates" in inputs.context:
            payload["max_candidates"] = inputs.context["max_candidates"]
        try:
            return ExtractionTask(**payload)
        except ValidationError as exc:
            raise LiteratureQueryError(f"invalid extraction task: {exc}") from exc

    @staticmethod
    def _extract_limit(inputs: AgentInput) -> int:
        """Bounded article count — an unbounded or nonsensical value is a caller error."""
        raw = inputs.context.get("max_extract_articles", _DEFAULT_EXTRACT_ARTICLES)
        try:
            limit = int(raw)
        except (TypeError, ValueError) as exc:
            raise LiteratureQueryError(f"max_extract_articles must be an integer: {raw!r}") from exc
        if not 1 <= limit <= _MAX_EXTRACT_ARTICLES:
            raise LiteratureQueryError(
                f"max_extract_articles must be within [1, {_MAX_EXTRACT_ARTICLES}], got {limit}"
            )
        return limit

    def _document_for(self, record: ArticleRecord) -> tuple[ArticleDocument | None, str | None]:
        """Fetch + parse a document, falling back to the abstract. Never raises.

        A fetch failure *or* a parse failure falls back to the abstract when the
        record has one — the original problem is preserved as a warning, and a
        malformed full text is never recorded as a successful full-text parse. Only a
        document with neither full text nor an abstract is skipped.
        """
        problem: str | None = None
        xml: str | None = None
        if record.is_open_access and record.has_full_text:
            try:
                xml = self.provider.fetch_open_full_text(record.identifiers)
            except ProviderError as exc:
                problem = f"full text unavailable ({exc})"
        if xml and problem is None:
            try:
                return (
                    parse_jats(
                        xml,
                        article=record.identifiers,
                        provider=record.provider,
                        source_url=record.source_url,
                        retrieved_at=record.retrieved_at,
                    ),
                    None,
                )
            except JatsParseError as exc:
                problem = f"could not parse full text ({exc})"
        if record.abstract:
            suffix = "; fell back to the abstract" if problem else None
            return document_from_abstract(record), f"{problem}{suffix}" if problem else None
        return None, problem or "no open-access full text and no abstract"

    def _extract(
        self, bundle: LiteratureEvidenceBundle, task: ExtractionTask, limit: int
    ) -> LiteratureEvidenceBundle:
        """Extract candidates from the top-ranked articles and rebuild the bundle.

        Every candidate is unverified: this never produces a VerificationDecision or a
        canonical run, and nothing is written to the KnowledgeStore.
        """
        # One shared identity policy (PMCID > PMID > DOI > provider-scoped id), the same
        # one dedup uses. Ranking by score avoids a lookup table whose keys could
        # collide (two DOI-only records previously collapsed onto one key, silently
        # dropping a paper and extracting the other twice).
        scores = {rel.article.stable_key(): rel.total_score for rel in bundle.relevance}
        ranked = sorted(
            bundle.articles,
            key=lambda a: scores.get(a.identifiers.stable_key(a.provider), 0.0),
            reverse=True,
        )[:limit]

        documents, warnings = [], list(bundle.warnings)
        measurements, claims, interpretations = [], [], []
        seen: set[str] = set()

        for record in ranked:
            label = record.identifiers.stable_key(record.provider)
            document, problem = self._document_for(record)
            if problem:
                warnings.append(f"{label}: {problem}")
            if document is None:
                continue

            result = extract_deterministic(document, task)
            if self.extractor is not None:
                # An optional extractor is untrusted *and* fallible: a failure is
                # isolated to this document, keeping deterministic results intact.
                try:
                    proposed = self.extractor.extract(document, task)
                except _EXTRACTOR_ERRORS as exc:
                    warnings.append(f"{label}: structured extractor failed ({exc})")
                    proposed = LiteratureExtractionResult()
                result = LiteratureExtractionResult(
                    measurements=[*result.measurements, *proposed.measurements],
                    claims=[*result.claims, *proposed.claims],
                    author_interpretations=[
                        *result.author_interpretations,
                        *proposed.author_interpretations,
                    ],
                    warnings=[*result.warnings, *proposed.warnings],
                )
            accepted, rejected = accept_candidates(document, result)
            documents.append(document.metadata())
            warnings.extend(accepted.warnings)
            warnings.extend(f"rejected candidate — {reason}" for reason in rejected)

            # Cap order (deterministic and documented): accept -> de-duplicate by
            # candidate_id -> apply the per-document cap. Deterministic candidates are
            # added before any LLM proposals, so the cap never silently prefers an LLM.
            kept = 0
            for bucket, items in (
                (measurements, accepted.measurements),
                (claims, accepted.claims),
                (interpretations, accepted.author_interpretations),
            ):
                for candidate in items:
                    if candidate.candidate_id in seen:
                        continue  # identical proposal from another pass
                    if kept >= task.max_candidates:
                        warnings.append(f"{label}: stopped at max_candidates={task.max_candidates}")
                        break
                    seen.add(candidate.candidate_id)
                    bucket.append(candidate)
                    kept += 1

        # Rebuilt (not mutated) so the bundle's linkage validation runs.
        return LiteratureEvidenceBundle(
            query=bundle.query,
            provider_provenance=bundle.provider_provenance,
            run_status=bundle.run_status,
            articles=bundle.articles,
            relevance=bundle.relevance,
            documents=documents,
            claims=claims,
            measurements=measurements,
            author_interpretations=interpretations,
            warnings=warnings,
        )

    async def run(self, inputs: AgentInput) -> AgentOutput:
        # Validate the whole request before doing any I/O, so a bad bound fails fast.
        query = self.build_query(inputs)
        task = self.build_task(inputs)
        limit = self._extract_limit(inputs) if task is not None else 0

        try:
            bundle = discover(query, self.provider)
        except ProviderError as exc:
            bundle = self._failure_bundle(query, exc)

        if task is not None and bundle.run_status is not DiscoveryRunStatus.PROVIDER_ERROR:
            bundle = self._extract(bundle, task, limit)

        # Run status — not the presence of warnings — is the authoritative signal.
        if bundle.run_status is DiscoveryRunStatus.PROVIDER_ERROR:
            notes = f"provider_error: {bundle.warnings[0] if bundle.warnings else 'unknown'}"
        elif bundle.run_status is DiscoveryRunStatus.ZERO_RESULTS:
            notes = "0 articles discovered"
        else:
            notes = f"{len(bundle.articles)} article(s) discovered"
            if task is not None:
                notes += (
                    f"; {len(bundle.measurements)} unverified measurement candidate(s) "
                    f"from {len(bundle.documents)} document(s)"
                )
        return AgentOutput(
            agent=self.name,
            claims=[],  # discovery yields metadata, never a biological claim
            confidence=0.0,  # no verified evidence; NOT the relevance score
            notes=notes,
            result=bundle.model_dump(mode="json"),
        )

    def _failure_bundle(
        self, query: LiteratureQuery, error: ProviderError
    ) -> LiteratureEvidenceBundle:
        # Provider-agnostic: use the context the ProviderError carries (or fall back
        # to the raw query text) rather than any provider-specific query builder.
        provenance = ProviderProvenance(
            provider=error.provider or getattr(self.provider, "name", "unknown"),
            query_sent=error.query_sent or query.query_text,
            retrieved_at=datetime.now(UTC),
        )
        return LiteratureEvidenceBundle(
            query=query,
            provider_provenance=provenance,
            run_status=DiscoveryRunStatus.PROVIDER_ERROR,
            warnings=[str(error)],
        )
