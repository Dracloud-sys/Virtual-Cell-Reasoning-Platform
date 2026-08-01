"""The unified reasoning query service (PR11).

One application-level entry point behind every interface:

    API / CLI -> ReasoningService.query() -> DomainRegistry -> DomainPack -> agent

The service owns *platform* concerns — domain resolution, task dispatch, optional
literature orchestration, provider outcome mapping, provenance assembly. It owns **no**
biological rules; every scientific statement in a response came from a domain pack's
product path.

Literature policy is enforced here, once, for all domains:

* ``allow_literature=False`` performs **no** external retrieval at all;
* a requested-but-unwired provider is reported as ``UNAVAILABLE`` rather than silently
  skipped;
* timeout, provider error, zero results and success are distinguishable states;
* **a failure never becomes evidence** — literature claims are attached only on success,
  are kept separate from the domain's own evidence, and retain the weak, pending-review
  tier and citations that :mod:`virtualcell.orchestration.query` assigned them.
"""

from __future__ import annotations

from virtualcell.core.evidence import Claim
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.literature.providers.base import ProviderError
from virtualcell.platform.contracts import (
    LiteratureOutcome,
    LiteratureStatus,
    ReasoningQuery,
    ReasoningResponse,
)
from virtualcell.platform.domains import DomainRegistry
from virtualcell.reasoning.llm import LLMBackend

# Provider failures worth distinguishing from a generic error. TimeoutError is stdlib;
# ProviderError is the literature layer's typed transport failure.
_TIMEOUT_ERRORS = (TimeoutError,)


class ReasoningService:
    """Executes a domain-neutral query against a registered domain pack."""

    def __init__(
        self,
        store: KnowledgeStore,
        registry: DomainRegistry,
        *,
        literature_agent: object | None = None,
        backend: LLMBackend | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        # Optional, pre-wired LiteratureDiscoveryAgent. None => literature is unavailable
        # (reported explicitly, never silently treated as "nothing found").
        self.literature_agent = literature_agent
        self.backend = backend

    async def query(self, request: ReasoningQuery) -> ReasoningResponse:
        """Resolve the domain, run its pack, then attach any literature outcome."""
        pack = self.registry.resolve(request.domain, request.task)
        response = pack.execute(request, self.store)
        response.literature = await self._literature(request)
        return response

    async def _literature(self, request: ReasoningQuery) -> LiteratureOutcome:
        if not request.allow_literature:
            # The deterministic local path: nothing external is contacted.
            return LiteratureOutcome(status=LiteratureStatus.NOT_REQUESTED)
        if self.literature_agent is None:
            return LiteratureOutcome(
                status=LiteratureStatus.UNAVAILABLE,
                detail="literature retrieval was requested but no provider is configured",
            )

        # Reuse the existing evidence orchestrator wholesale, so PR9/PR10a semantics
        # (weak ingestion, resolution, and the never-established downgrade) apply
        # unchanged rather than being re-implemented here. Enter through the direct
        # augmentation path, not `answer()`: the caller asked for literature explicitly,
        # so a knowledge-base hit must not silently skip the request.
        from virtualcell.orchestration.query import EvidenceQueryOrchestrator

        orchestrator = EvidenceQueryOrchestrator(
            self.store, literature_agent=self.literature_agent, backend=self.backend
        )
        provider = getattr(getattr(self.literature_agent, "provider", None), "name", None)
        question = self._literature_question(request)
        try:
            result = await orchestrator.augment_with_literature(
                question, target_measurements=request.target_measurements or None
            )
        except _TIMEOUT_ERRORS as exc:
            return LiteratureOutcome(
                status=LiteratureStatus.TIMEOUT, provider=provider, detail=str(exc)
            )
        except ProviderError as exc:
            return LiteratureOutcome(
                status=LiteratureStatus.PROVIDER_ERROR, provider=provider, detail=str(exc)
            )

        # A provider failure that the discovery agent caught internally still surfaces as
        # a failure here — it must never be reported as "we looked and found nothing".
        if result.literature_run_status == "provider_error":
            return LiteratureOutcome(
                status=LiteratureStatus.PROVIDER_ERROR,
                provider=provider,
                detail="the literature provider reported an error",
            )
        if not result.literature_facts:
            return LiteratureOutcome(
                status=LiteratureStatus.ZERO_RESULTS,
                provider=provider,
                detail="no machine-verified literature measurement was found",
            )
        return LiteratureOutcome(
            status=LiteratureStatus.SUCCESS,
            provider=provider,
            evidence=[
                # Tier and citation are carried across verbatim; nothing is upgraded.
                Claim(
                    statement=fact.statement,
                    tier=fact.tier,
                    confidence=fact.confidence,
                    citations=[fact.citation],
                )
                for fact in result.literature_facts
            ],
        )

    @staticmethod
    def _literature_question(request: ReasoningQuery) -> str:
        """A deterministic search question when the caller did not supply one."""
        if request.question:
            return request.question
        if request.target_measurements:
            return " ".join(request.target_measurements)
        return request.domain
