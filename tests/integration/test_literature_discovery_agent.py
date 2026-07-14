"""Agent + CLI tests for literature discovery (PR8b). No network, no LLM."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from virtualcell.agents.literature.agent import LiteratureAgent
from virtualcell.agents.literature_discovery.agent import LiteratureDiscoveryAgent
from virtualcell.core.agent import AgentContext
from virtualcell.core.contracts import AgentInput
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.literature.contracts import (
    ArticleIdentifier,
    ArticleRecord,
    LiteratureEvidenceBundle,
    LiteratureSearchResult,
    ProviderProvenance,
)
from virtualcell.literature.providers.base import ProviderError


class _FakeProvider:
    name = "fake"

    def __init__(self, articles=None, error: Exception | None = None) -> None:
        self._articles = articles or []
        self._error = error

    def search(self, query) -> LiteratureSearchResult:
        if self._error:
            raise self._error
        return LiteratureSearchResult(
            provenance=ProviderProvenance(
                provider=self.name,
                query_sent="q",
                retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
                hit_count=len(self._articles),
            ),
            articles=self._articles,
        )

    def fetch_record(self, identifier):  # pragma: no cover - unused here
        raise NotImplementedError

    def fetch_open_full_text(self, identifier):  # pragma: no cover - unused here
        return None


def _article() -> ArticleRecord:
    return ArticleRecord(
        identifiers=ArticleIdentifier(pmid="1", pmcid="PMC1", doi="10.1/a"),
        title="TERT in bovine preadipocyte senescence",
        abstract="bovine preadipocyte TERT escape",
        has_full_text=True,
    )


def _agent(provider) -> LiteratureDiscoveryAgent:
    return LiteratureDiscoveryAgent(AgentContext(services={"literature_provider": provider}))


async def test_agent_returns_typed_bundle_not_claims() -> None:
    agent = _agent(_FakeProvider([_article()]))
    out = await agent.run(
        AgentInput(
            query="spontaneous immortalization",
            context={"species": ["Bos taurus"], "genes": ["TERT"], "max_results": 10},
        )
    )
    assert out.agent == "literature_discovery"
    assert out.claims == []  # discovery is not evidence
    assert out.confidence == 0.0  # not the relevance score
    bundle = LiteratureEvidenceBundle.model_validate(out.result)  # round-trips
    assert len(bundle.articles) == 1
    assert bundle.relevance[0].total_score > 0
    assert bundle.measurements == [] and bundle.canonical_runs == []


async def test_agent_distinguishes_provider_failure_from_zero_results() -> None:
    # Provider failure: a warning is present and notes flag the provider error.
    failed = await _agent(_FakeProvider(error=ProviderError("boom"))).run(AgentInput(query="x"))
    assert failed.result["warnings"]
    assert failed.notes.startswith("provider_error")
    # Zero results: a clean empty bundle, no warning.
    empty = await _agent(_FakeProvider([])).run(AgentInput(query="x"))
    assert empty.result["warnings"] == []
    assert empty.result["articles"] == []
    assert "0 article" in empty.notes


async def test_existing_literature_agent_is_unchanged() -> None:
    # The retrieval agent still answers from the KnowledgeStore and is untouched.
    store = InMemoryKnowledgeStore()
    agent = LiteratureAgent(AgentContext(services={"knowledge_store": store}), store=store)
    out = await agent.run(AgentInput(query="nothing here"))
    assert out.agent == "literature"
    assert out.claims and out.claims[0].tier.value == "speculative"


def test_cli_literature_discover_writes_bundle(tmp_path, capsys, monkeypatch) -> None:
    # Patch the agent's default provider so the CLI runs offline.
    monkeypatch.setattr(
        "virtualcell.agents.literature_discovery.agent.EuropePmcProvider",
        lambda: _FakeProvider([_article()]),
    )
    from virtualcell.cli import main

    out_path = tmp_path / "bundle.json"
    rc = main(
        [
            "literature",
            "discover",
            "--query",
            "spontaneous immortalization",
            "--species",
            "Bos taurus",
            "--gene",
            "TERT",
            "--max-results",
            "5",
            "--output",
            str(out_path),
        ]
    )
    assert rc == 0
    bundle = LiteratureEvidenceBundle.model_validate(
        json.loads(out_path.read_text(encoding="utf-8"))
    )
    assert len(bundle.articles) == 1


def test_cli_literature_discover_text_output(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "virtualcell.agents.literature_discovery.agent.EuropePmcProvider",
        lambda: _FakeProvider([_article()]),
    )
    from virtualcell.cli import main

    rc = main(["literature", "discover", "--query", "TERT senescence"])
    assert rc == 0
    assert "provider: fake" in capsys.readouterr().out


def test_agent_is_registered() -> None:
    import virtualcell.agents  # noqa: F401  (registers agents)
    from virtualcell.core.registry import registry

    assert "literature_discovery" in registry
    assert "literature" in registry  # existing agent still registered
