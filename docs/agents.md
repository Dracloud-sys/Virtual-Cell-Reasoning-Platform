# Agent Catalog

Every capability in the platform is modeled as a cooperating agent. Each agent
declares the same contract (see `virtualcell.core.agent.BaseAgent`):

- **responsibilities** — what it is accountable for
- **inputs** — an `AgentInput`
- **outputs** — an `AgentOutput` carrying evidence-tagged `Claim`s
- **memory** — injected `MemoryStore` (optional)
- **reasoning** — implemented in `run()`
- **confidence** — `estimate_confidence()`

## Agents in v0.1

All except Literature are interface stubs; Literature is wired to the knowledge base
as the reference implementation.

| Agent | Responsibility (summary) | Roadmap stage |
|-------|--------------------------|---------------|
| Genome | Sequence, gene models, variant context | 1, 3 |
| Transcription | Transcription & RNA-level regulation | 3 |
| Protein Interaction | Protein–protein interaction reasoning | 7 |
| Metabolism | Metabolic network and flux reasoning | 6 |
| Signaling | Cell signaling cascade reasoning | 4 |
| Literature | Mine/query knowledge base for supporting evidence | 2 |
| Validation | Check consistency and evidence tiers of outputs | cross-cutting |

## Planned agents (later releases)

Epigenetic, Chromatin, RNA Processing, Translation, Protein Folding, Cell Cycle,
DNA Repair, Mutation, Stress Response, Differentiation, Environment, Physics
Simulation, Experiment Planner.

## Adding an agent

1. Subclass `BaseAgent` in `virtualcell/agents/<name>/agent.py`.
2. Declare `name` and `responsibilities`.
3. Implement `run()` returning an `AgentOutput` whose claims carry an
   `EvidenceTier`.
4. Register it via `virtualcell.core.registry`.
5. Add unit tests using the in-memory knowledge backend.
