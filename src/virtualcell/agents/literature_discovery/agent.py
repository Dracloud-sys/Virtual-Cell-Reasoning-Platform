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
    LiteratureEvidenceBundle,
    LiteratureQuery,
    ProviderProvenance,
)
from virtualcell.literature.discovery import build_europe_pmc_query, discover
from virtualcell.literature.providers.base import LiteratureProvider, ProviderError
from virtualcell.literature.providers.europe_pmc import EuropePmcProvider

_QUERY_FIELDS = (
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


class LiteratureQueryError(ValueError):
    """Raised when an AgentInput does not carry a valid literature query."""


class LiteratureDiscoveryAgent(BaseAgent):
    name = "literature_discovery"
    responsibilities = "Discover external papers and return metadata + relevance (no claims)."

    def __init__(
        self,
        context: AgentContext | None = None,
        provider: LiteratureProvider | None = None,
    ) -> None:
        super().__init__(context)
        # A provider may be injected (tests) or supplied via services; otherwise the
        # default Europe PMC connector (real network) is used.
        self.provider = (
            provider or self.context.services.get("literature_provider") or EuropePmcProvider()
        )

    def build_query(self, inputs: AgentInput) -> LiteratureQuery:
        payload = {k: v for k, v in inputs.context.items() if k in _QUERY_FIELDS}
        try:
            return LiteratureQuery(query_text=inputs.query, **payload)
        except ValidationError as exc:
            raise LiteratureQueryError(f"invalid literature query: {exc}") from exc

    async def run(self, inputs: AgentInput) -> AgentOutput:
        query = self.build_query(inputs)
        try:
            bundle = discover(query, self.provider)
        except ProviderError as exc:
            bundle = self._failure_bundle(query, exc)

        provider_failed = bool(bundle.warnings)
        if provider_failed:
            notes = f"provider_error: {bundle.warnings[0]}"
        else:
            notes = f"{len(bundle.articles)} article(s) discovered"
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
        built = build_europe_pmc_query(query)
        provenance = ProviderProvenance(
            provider=getattr(self.provider, "name", "unknown"),
            query_sent=built.query_string,
            retrieved_at=datetime.now(UTC),
        )
        return LiteratureEvidenceBundle(
            query=query, provider_provenance=provenance, warnings=[str(error)]
        )
