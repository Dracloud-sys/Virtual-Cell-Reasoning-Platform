"""Tests for agents and orchestration."""

from __future__ import annotations

import pytest

from virtualcell.agents.literature.agent import LiteratureAgent
from virtualcell.agents.validation.agent import ValidationAgent
from virtualcell.core.agent import AgentContext
from virtualcell.core.contracts import AgentInput
from virtualcell.core.evidence import Claim, EvidenceTier
from virtualcell.core.registry import AgentRegistry
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.sample import SampleDataSource
from virtualcell.orchestration.graph import Orchestrator


@pytest.fixture
def store() -> InMemoryKnowledgeStore:
    s = InMemoryKnowledgeStore()
    load_into(SampleDataSource(), s)
    return s


async def test_literature_agent_returns_established_claims(store: InMemoryKnowledgeStore) -> None:
    agent = LiteratureAgent(store=store)
    out = await agent.run(AgentInput(query="p53"))
    assert out.claims
    assert all(c.tier == EvidenceTier.ESTABLISHED for c in out.claims)
    assert out.confidence > 0


async def test_literature_agent_no_match_is_speculative(store: InMemoryKnowledgeStore) -> None:
    agent = LiteratureAgent(store=store)
    out = await agent.run(AgentInput(query="zzz-nonexistent"))
    assert len(out.claims) == 1
    assert out.claims[0].tier == EvidenceTier.SPECULATIVE


async def test_validation_agent_flags_speculative_without_assumptions() -> None:
    agent = ValidationAgent()
    bad = Claim(statement="guess", tier=EvidenceTier.SPECULATIVE)  # no assumptions
    out = await agent.run(AgentInput(query="validate", context={"claims": [bad.model_dump()]}))
    assert out.confidence < 1.0


async def test_orchestrator_runs_registered_agent(store: InMemoryKnowledgeStore) -> None:
    reg = AgentRegistry()
    reg.register("literature", lambda ctx: LiteratureAgent(ctx, store=store))
    orch = Orchestrator(registry=reg, context=AgentContext(services={"knowledge_store": store}))
    out = await orch.run("literature", AgentInput(query="MDM2"))
    assert out.claims
