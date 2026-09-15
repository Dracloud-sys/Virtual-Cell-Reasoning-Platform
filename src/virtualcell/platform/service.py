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

from virtualcell.core.consumption import ConsumptionReport
from virtualcell.core.evidence import Claim
from virtualcell.core.experiment import ExperimentRun
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.literature.contracts import DiscoveryRunStatus
from virtualcell.literature.providers.base import ProviderError, ProviderTimeoutError
from virtualcell.platform.contracts import (
    CanonicalIntake,
    LiteratureOutcome,
    LiteratureStatus,
    ReasoningQuery,
    ReasoningResponse,
    RunProvenance,
)
from virtualcell.platform.domains import (
    DomainRegistry,
    check_run_admissible,
    resolve_canonical_intake,
    validate_declared_outcome,
)
from virtualcell.reasoning.llm import LLMBackend

# Provider failures worth distinguishing from a generic error. TimeoutError is stdlib;
# ProviderError is the literature layer's typed transport failure.
_TIMEOUT_ERRORS = (TimeoutError,)

# One mapping from a discovery failure status to the platform status + wording, used for
# both search failures and per-document retrieval failures so the two cannot drift.
_FAILURE_STATUS: dict[str, tuple[LiteratureStatus, str]] = {
    DiscoveryRunStatus.PROVIDER_ERROR.value: (
        LiteratureStatus.PROVIDER_ERROR,
        "the literature provider reported an error",
    ),
    DiscoveryRunStatus.PROVIDER_TIMEOUT.value: (
        LiteratureStatus.TIMEOUT,
        "the literature provider did not respond in time",
    ),
}


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
        """Resolve the domain, run its pack, check its verdict, attach any literature."""
        pack = self.registry.resolve(request.domain, request.task)

        # A canonical run is converted *before* dispatch, so the pack's own `execute` sees
        # an ordinary experiment payload and everything below it - validation, the
        # consumption ledger, missing inputs - works unchanged. The conversion is the
        # pack's, because it is biology; the refusals are the platform's.
        run = request.experiment_run
        intake: CanonicalIntake | None = None
        if run is not None:
            check_run_admissible(run)
            intake = resolve_canonical_intake(pack, request, run)
            request = request.model_copy(
                update={"experiment": {**request.experiment, **intake.experiment}}
            )

        response = pack.execute(request, self.store)
        # Here rather than in each pack: a pack cannot skip its own check, and a fourth
        # domain inherits this without writing a line. The description comes from the same
        # pack that produced the response, so no vocabulary is merged or centralised.
        validate_declared_outcome(pack.describe(), response.decision_support)
        if intake is not None and run is not None:
            self._account_for_run(response, intake, run)
        response.literature = await self._literature(request)
        return response

    @staticmethod
    def _account_for_run(
        response: ReasoningResponse, intake: CanonicalIntake, run: ExperimentRun
    ) -> None:
        """Make the answer describe the submission that was actually made.

        The pack's ledger reports on the experiment dict it was handed, and part of that
        dict was synthesised here from the run - so left alone the answer would account
        for keys the caller never sent, while saying nothing about the measurements they
        did. Entries for the synthesised keys are replaced by the intake's own, which name
        canonical measurements and point at the observation each came from. Anything the
        caller put in `experiment` themselves is kept exactly as the pack reported it.

        The run's identity is recorded too, because otherwise a verdict and the export
        that produced it could only be reconnected by whoever happened to run the query.
        """
        synthesised = set(intake.experiment)
        response.measurement_consumption = ConsumptionReport(
            entries=[
                *intake.consumption.entries,
                *(
                    entry
                    for entry in response.measurement_consumption.entries
                    if entry.submitted_as not in synthesised
                ),
            ]
        )
        response.provenance = response.provenance.model_copy(
            update={
                "experiment_run": RunProvenance(
                    run_id=run.run_id,
                    schema_version=run.schema_version,
                    observations=len(run.observations),
                    # Repeating a claim, not making one: a declared checksum has already
                    # been verified by the contract, and an absent one is a missing claim
                    # rather than a failed check.
                    sealed=run.checksum is not None,
                )
            }
        )

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
        except (ProviderTimeoutError, *_TIMEOUT_ERRORS) as exc:
            # Ordered before ProviderError: ProviderTimeoutError subclasses it.
            return LiteratureOutcome(
                status=LiteratureStatus.TIMEOUT, provider=provider, detail=str(exc)
            )
        except ProviderError as exc:
            return LiteratureOutcome(
                status=LiteratureStatus.PROVIDER_ERROR, provider=provider, detail=str(exc)
            )

        # A provider failure that the discovery agent caught internally still surfaces as
        # a failure here — it must never be reported as "we looked and found nothing".
        # A timeout keeps its own status the whole way from UrllibTransport.
        search_failure = _FAILURE_STATUS.get(result.literature_run_status or "")
        if search_failure is not None:
            status, detail = search_failure
            return LiteratureOutcome(status=status, provider=provider, detail=detail)

        document_failure = _FAILURE_STATUS.get(result.literature_document_failure or "")
        if not result.literature_facts:
            # The *search* succeeded but nothing usable came back. Whether that is a
            # genuine negative or a retrieval failure depends on whether the documents
            # could be fetched at all: a run whose documents timed out is not a
            # zero-result run, and reporting it as one would hide a retryable outage.
            if document_failure is not None:
                status, detail = document_failure
                return LiteratureOutcome(
                    status=status,
                    provider=provider,
                    detail=f"{detail} while retrieving documents",
                )
            return LiteratureOutcome(
                status=LiteratureStatus.ZERO_RESULTS,
                provider=provider,
                detail="no machine-verified literature measurement was found",
            )

        # Evidence was produced. A document that failed alongside it is a *partial*
        # failure: keep the usable result and record the failure, never the reverse —
        # and the failure itself still never becomes evidence.
        detail = (
            f"partial retrieval: {document_failure[1]} for at least one document"
            if document_failure is not None
            else None
        )
        return LiteratureOutcome(
            status=LiteratureStatus.SUCCESS,
            provider=provider,
            detail=detail,
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
