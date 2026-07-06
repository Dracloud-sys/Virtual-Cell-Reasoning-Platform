"""Literature Agent — the reference working agent for v0.1.

It queries the knowledge base for entities matching a request and returns each hit
as an evidence-tagged :class:`Claim`. Because the sample knowledge is curated (not
mined), hits are reported at the ``ESTABLISHED`` tier with a source citation; when
no match is found it returns a single ``SPECULATIVE`` claim so the output is never
silently empty.

This demonstrates the full flow: query -> knowledge base -> evidence-tagged claims.
"""

from __future__ import annotations

from virtualcell.core.agent import AgentContext, BaseAgent
from virtualcell.core.confidence import mean_confidence
from virtualcell.core.contracts import AgentInput, AgentOutput
from virtualcell.core.evidence import Claim, EvidenceTier
from virtualcell.knowledge.store import KnowledgeStore, get_store


class LiteratureAgent(BaseAgent):
    name = "literature"
    responsibilities = "Query the knowledge base for evidence supporting a request."

    def __init__(
        self,
        context: AgentContext | None = None,
        store: KnowledgeStore | None = None,
    ) -> None:
        super().__init__(context)
        # Allow a store to be injected (tests); otherwise use the configured one,
        # or one passed through the agent context's services.
        self.store = store or self.context.services.get("knowledge_store") or get_store()

    async def run(self, inputs: AgentInput) -> AgentOutput:
        hits = self.store.search(inputs.query, k=inputs.context.get("k", 5))

        if not hits:
            claim = Claim(
                statement=f"No knowledge-base entity matched query {inputs.query!r}.",
                tier=EvidenceTier.SPECULATIVE,
                confidence=0.0,
                assumptions=["query may reference an entity not yet ingested"],
            )
            return AgentOutput(agent=self.name, claims=[claim], confidence=0.0)

        claims = [
            Claim(
                statement=(
                    f"{entity.type.value.capitalize()} '{entity.name}' "
                    f"(id={entity.id}) is present in the knowledge base."
                ),
                tier=EvidenceTier.ESTABLISHED,
                confidence=0.8,
                citations=[f"kb:{entity.id}"],
            )
            for entity in hits
        ]
        return AgentOutput(
            agent=self.name,
            claims=claims,
            confidence=mean_confidence(c.confidence for c in claims),
            notes=f"{len(claims)} knowledge-base hit(s)",
        )
