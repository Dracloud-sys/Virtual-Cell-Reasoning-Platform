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
        try:
            return ExtractionTask(
                target_measurements=inputs.context.get("target_measurements", []),
                target_contexts=inputs.context.get("target_contexts", []),
            )
        except ValidationError as exc:
            raise LiteratureQueryError(f"invalid extraction task: {exc}") from exc

    def _document_for(self, record: ArticleRecord) -> tuple[ArticleDocument | None, str | None]:
        """Fetch + parse a document, falling back to the abstract. Never raises."""
        xml = None
        if record.is_open_access and record.has_full_text:
            try:
                xml = self.provider.fetch_open_full_text(record.identifiers)
            except ProviderError as exc:
                return None, f"full text unavailable ({exc})"
        if xml:
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
                return None, f"could not parse full text ({exc})"
        return document_from_abstract(record), None

    def _extract(
        self, bundle: LiteratureEvidenceBundle, task: ExtractionTask, limit: int
    ) -> LiteratureEvidenceBundle:
        """Extract candidates from the top-ranked articles and rebuild the bundle.

        Every candidate is unverified: this never produces a VerificationDecision or a
        canonical run, and nothing is written to the KnowledgeStore.
        """
        by_id = {a.identifiers.provider_id or a.identifiers.pmid: a for a in bundle.articles}
        ranked = [
            by_id[key]
            for rel in bundle.relevance
            if (key := rel.article.provider_id or rel.article.pmid) in by_id
        ][:limit]

        documents, warnings = [], list(bundle.warnings)
        measurements, claims, interpretations = [], [], []
        seen: set[str] = set()

        for record in ranked:
            document, problem = self._document_for(record)
            if document is None:
                warnings.append(f"{record.identifiers.pmid or record.identifiers.doi}: {problem}")
                continue
            result = extract_deterministic(document, task)
            if self.extractor is not None:
                proposed = self.extractor.extract(document, task)
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
            for bucket, items in (
                (measurements, accepted.measurements),
                (claims, accepted.claims),
                (interpretations, accepted.author_interpretations),
            ):
                for candidate in items:
                    if candidate.candidate_id in seen:
                        continue  # identical proposal from another pass
                    seen.add(candidate.candidate_id)
                    bucket.append(candidate)

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
        query = self.build_query(inputs)
        task = self.build_task(inputs)
        try:
            bundle = discover(query, self.provider)
        except ProviderError as exc:
            bundle = self._failure_bundle(query, exc)

        if task is not None and bundle.run_status is not DiscoveryRunStatus.PROVIDER_ERROR:
            limit = int(inputs.context.get("max_extract_articles", _DEFAULT_EXTRACT_ARTICLES))
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
