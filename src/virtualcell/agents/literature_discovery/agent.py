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
from virtualcell.literature.canonical import experiment_runs_from_verified
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
from virtualcell.literature.ingestion import ingest_runs
from virtualcell.literature.providers.base import LiteratureProvider, ProviderError
from virtualcell.literature.providers.europe_pmc import EuropePmcProvider
from virtualcell.literature.verification import verify_candidates

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
        for field in ("max_candidates", "max_total_candidates"):
            if field in inputs.context:
                payload[field] = inputs.context[field]
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
        self,
        bundle: LiteratureEvidenceBundle,
        task: ExtractionTask,
        limit: int,
        *,
        verify: bool = False,
        convert: bool = False,
    ) -> LiteratureEvidenceBundle:
        """Extract candidates from the top-ranked articles and rebuild the bundle.

        When ``verify`` is off every candidate stays unverified: no VerificationDecision
        is produced. When it is on, each document's *retained* candidates (those that
        survived acceptance, de-duplication and the caps) are re-checked against that
        same in-memory ``ArticleDocument`` to produce deterministic decisions — an
        orphan decision for a capped-away candidate is never created. When ``convert`` is
        also on, each document's ``MACHINE_VERIFIED`` measurements become canonical
        ``ExperimentRun``s (only successful conversions land in ``canonical_runs``).
        Nothing here is ever written to the KnowledgeStore.
        """
        verified_at = datetime.now(UTC)
        decisions = []
        canonical_runs = []
        # One shared identity policy (PMCID > PMID > DOI > provider-scoped id), the same
        # one dedup uses, and — crucially — the same one the relevance score carries, so
        # a provider_id-only record resolves to its score instead of falling to 0.
        # Ranking sorts by score (Python's sort is stable, so equal scores keep the
        # discovery order) rather than a lookup table whose keys could collide.
        scores = {rel.stable_key(): rel.total_score for rel in bundle.relevance}
        ranked = sorted(
            bundle.articles,
            key=lambda a: scores.get(a.identifiers.stable_key(a.provider), 0.0),
            reverse=True,
        )[:limit]

        documents, warnings = [], list(bundle.warnings)
        measurements, claims, interpretations = [], [], []
        seen: set[str] = set()
        total_kept = 0
        global_capped = False

        for record in ranked:
            if global_capped:
                break
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
            # Task-aware acceptance: every candidate (deterministic OR LLM) must be
            # source-anchored AND about a requested target on the cell it cites.
            accepted, rejected = accept_candidates(document, result, task)
            documents.append(document.metadata())
            warnings.extend(accepted.warnings)
            warnings.extend(f"rejected candidate — {reason}" for reason in rejected)

            # Cap order (deterministic and documented): accept -> de-duplicate by
            # candidate_id -> per-document cap -> global run cap. Deterministic
            # candidates come before any LLM proposals, so a cap never prefers an LLM.
            kept = 0
            retained = LiteratureExtractionResult()
            for bucket, retained_bucket, items in (
                (measurements, retained.measurements, accepted.measurements),
                (claims, retained.claims, accepted.claims),
                (interpretations, retained.author_interpretations, accepted.author_interpretations),
            ):
                for candidate in items:
                    if candidate.candidate_id in seen:
                        continue  # identical proposal from another pass
                    if total_kept >= task.max_total_candidates:
                        warnings.append(
                            f"stopped at max_total_candidates={task.max_total_candidates}"
                        )
                        global_capped = True
                        break
                    if kept >= task.max_candidates:
                        warnings.append(f"{label}: stopped at max_candidates={task.max_candidates}")
                        break
                    seen.add(candidate.candidate_id)
                    bucket.append(candidate)
                    retained_bucket.append(candidate)
                    kept += 1
                    total_kept += 1
                if global_capped or kept >= task.max_candidates:
                    break

            # Verify only what this document actually retained (post-cap), against the
            # same in-memory document — so a decision never orphans a capped candidate.
            # Canonical conversion then draws only from those same retained candidates and
            # their decisions, so a run can never reference a capped-away measurement.
            if verify:
                doc_decisions = verify_candidates(document, retained, task, verified_at=verified_at)
                decisions.extend(doc_decisions)
                if convert:
                    canonical_runs.extend(
                        experiment_runs_from_verified(retained.measurements, doc_decisions)
                    )

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
            verification_decisions=decisions,
            canonical_runs=canonical_runs,
            warnings=warnings,
        )

    async def run(self, inputs: AgentInput) -> AgentOutput:
        # Validate the whole request before doing any I/O, so a bad bound fails fast.
        query = self.build_query(inputs)
        task = self.build_task(inputs)
        limit = self._extract_limit(inputs) if task is not None else 0
        # Verification is an explicit opt-in that *requires* extraction: it re-checks
        # extracted candidates, so there is nothing to verify without extract=true.
        # Canonical conversion is a further opt-in that requires verification: only a
        # MACHINE_VERIFIED measurement is converted, so it is meaningless without verify.
        verify = bool(inputs.context.get("verify", False))
        convert = bool(inputs.context.get("convert", False))
        # Reviewed ingestion is a final opt-in that requires conversion (only a canonical
        # run is ingested) and a knowledge_store service to write into.
        ingest = bool(inputs.context.get("ingest", False))
        store = self.context.services.get("knowledge_store")
        if verify and task is None:
            raise LiteratureQueryError("verify=true requires extract=true")
        if convert and not verify:
            raise LiteratureQueryError("convert=true requires verify=true")
        if ingest and not convert:
            raise LiteratureQueryError("ingest=true requires convert=true")
        if ingest and store is None:
            raise LiteratureQueryError("ingest=true requires a knowledge_store service")

        try:
            bundle = discover(query, self.provider)
        except ProviderError as exc:
            bundle = self._failure_bundle(query, exc)

        if task is not None and bundle.run_status is not DiscoveryRunStatus.PROVIDER_ERROR:
            bundle = self._extract(bundle, task, limit, verify=verify, convert=convert)

        # Ingest the (post-cap) canonical runs as weak, reviewable evidence. This is the
        # only path that writes to the KnowledgeStore, and only under an explicit opt-in.
        ingestion = None
        if ingest and bundle.canonical_runs:
            ingestion = ingest_runs(store, bundle.canonical_runs)

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
            if verify:
                notes += f"; {len(bundle.verification_decisions)} verification decision(s)"
            if convert:
                notes += f"; {len(bundle.canonical_runs)} canonical run(s)"
            if ingest:
                added = ingestion.interactions_added if ingestion is not None else 0
                notes += f"; ingested {added} weak evidence edge(s)"
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
