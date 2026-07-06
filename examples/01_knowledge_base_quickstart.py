"""Quickstart: build a knowledge base and query it with the Literature Agent.

Run: ``python examples/01_knowledge_base_quickstart.py``
Requires no external services (uses the in-memory backend and bundled sample data).
"""

from __future__ import annotations

import asyncio

from virtualcell.agents.literature.agent import LiteratureAgent
from virtualcell.core.agent import AgentContext
from virtualcell.core.contracts import AgentInput
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.sample import SampleDataSource


async def main() -> None:
    # 1. Build an in-memory knowledge base from the bundled sample dataset.
    store = InMemoryKnowledgeStore()
    n_entities, n_interactions = load_into(SampleDataSource(), store)
    print(f"loaded {n_entities} entities, {n_interactions} interactions\n")

    # 2. Direct graph query: what does TP53 connect to?
    print("Neighbors of gene:TP53:")
    for entity in store.neighbors("gene:TP53"):
        print(f"  - {entity.id} ({entity.type.value}): {entity.name}")
    print()

    # 3. Agent query: ask the Literature Agent about p53.
    agent = LiteratureAgent(AgentContext(services={"knowledge_store": store}), store=store)
    output = await agent.run(AgentInput(query="p53"))
    print("Literature Agent claims for query 'p53':")
    for claim in output.claims:
        print(f"  [{claim.tier.value}] ({claim.confidence:.2f}) {claim.statement}")
    print(f"\noverall confidence: {output.confidence:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
