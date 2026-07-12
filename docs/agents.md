# Agent Catalog

Every capability in the platform is modeled as a cooperating agent. Each agent
declares the same contract (see `virtualcell.core.agent.BaseAgent`):

- **responsibilities** — what it is accountable for
- **inputs** — an `AgentInput`
- **outputs** — an `AgentOutput` carrying evidence-tagged `Claim`s
- **memory** — injected `MemoryStore` (optional)
- **reasoning** — implemented in `run()`
- **confidence** — `estimate_confidence()`

## Agents

**Literature** and **Immortalization Assessment** are functional; the other domain
agents are interface stubs.

| Agent | Responsibility (summary) | Status |
|-------|--------------------------|--------|
| Immortalization Assessment | Turn normalized experiment markers into an evidence-graded `DecisionReport` | **functional** |
| Literature | Mine/query knowledge base for supporting evidence | **functional** |
| Genome | Sequence, gene models, variant context | stub |
| Transcription | Transcription & RNA-level regulation | stub |
| Protein Interaction | Protein–protein interaction reasoning | stub |
| Metabolism | Metabolic network and flux reasoning | stub |
| Signaling | Cell signaling cascade reasoning | stub |
| Validation | Check consistency and evidence tiers of outputs | stub |

### Immortalization Assessment agent

`ImmortalizationAssessmentAgent` dispatches by intent and recomputes nothing —
status/flags/tiers/citations come from the layers below:

```
ImmortalizationAssessmentAgent
├── deterministic assessment builder   (baseline_status + evidence assembly)
├── mechanism-rule grounding           (Q5/Q6: curated claims + graph paths)
└── hypothesis safety policy           (Q9: P53-independent, no causal overreach)
```

Run it in Python (`agent.assess(...)` / `agent.run(...)`), via the API
(`POST /agents/immortalization_assessment/run`), or the CLI
(`virtualcell assess immortalization --input assessment.json`). The optional LLM
narrative layer is out of scope here (it may never change status/tier/citation).

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
