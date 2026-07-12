# Architecture

The Virtual Cell Platform is a coordinated ecosystem of specialized agents,
biological knowledge bases, and simulation engines. It is deliberately **not** a
single model. This document describes the layers and how they fit together.

## Layered view

```
                         ┌─────────────────────────┐
                         │         API / CLI        │  interaction surface
                         └────────────┬────────────┘
                                      │
                         ┌────────────▼────────────┐
                         │      Orchestration       │  LangGraph: routes work
                         │      (agent graph)       │  between agents
                         └────────────┬────────────┘
                                      │
        ┌───────────────┬────────────┼────────────┬───────────────┐
        │               │            │            │               │
   ┌────▼────┐    ┌─────▼────┐  ┌────▼────┐  ┌────▼─────┐   ┌──────▼─────┐
   │ Genome  │    │Transcrip.│  │Metabol. │  │Signaling │   │ Literature │  specialized
   │  Agent  │    │  Agent   │  │  Agent  │  │  Agent   │   │   Agent    │  agents ...
   └────┬────┘    └─────┬────┘  └────┬────┘  └────┬─────┘   └──────┬─────┘
        └───────────────┴───────┬────┴────────────┴────────────────┘
                                │
              ┌─────────────────▼──────────────────┐
              │           Core abstractions          │  BaseAgent, contracts,
              │  (agent / evidence / confidence)     │  EvidenceTier, registry
              └─────────────────┬──────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
  ┌─────▼──────┐        ┌───────▼───────┐        ┌──────▼───────┐
  │ Knowledge  │        │  Simulation   │        │   Data       │
  │   Base     │        │   Engine      │        │  Sources     │
  │ (graph +   │        │ (dynamic,     │        │ (GO, KEGG,   │
  │  vector)   │        │  time-based)  │        │  UniProt...) │
  └────────────┘        └───────────────┘        └──────────────┘
```

## Core abstractions (`virtualcell.core`)

Everything shared lives here so modules never import each other directly.

- **`BaseAgent`** — the contract every specialized agent implements: a `name`,
  `responsibilities`, an async `run(inputs) -> AgentOutput`, and
  `estimate_confidence`. Memory is injected, not hard-wired.
- **`contracts`** — Pydantic models for inter-agent messages: `AgentInput`,
  `AgentOutput`, `Message`.
- **`evidence`** — `EvidenceTier` and `Claim`. Any biological statement carries a
  tier so established knowledge, hypotheses, and speculation are never conflated.
- **`registry`** — register and look up agents by name for the orchestrator.
- **`config`** — `Settings` loaded from environment via pydantic-settings.

## Knowledge Base (`virtualcell.knowledge`) — Stage 1

The first roadmap stage and the only fully working subsystem in v0.1.

- **`schema`** — biological entities: `Gene`, `Protein`, `Pathway`, plus typed
  relationships (`Interaction`).
- **`store`** — a `KnowledgeStore` protocol: `upsert`, `get`, `neighbors`, `search`.
- **`backends`** — swappable implementations:
  - `memory` — pure-Python, zero external dependencies; the default and what the
    test suite exercises.
  - `neo4j` — graph backend for relationship-heavy queries.
  - `qdrant` — vector backend for semantic/literature search.
- **`sources`** — connectors that ingest external datasets (Gene Ontology,
  Reactome, UniProt, ...) behind a common `DataSource` protocol.

## Reasoning (`virtualcell.reasoning`)

- **`explain`** — evidence-graded multi-hop mechanistic reach: direction-preserving
  traversal with a tier that is `weaker_of(hop-distance, weakest-edge ceiling)`, so
  weak associative relations never read as established.
- **`decision`** — the `DecisionReport` output contract (conclusion, candidate
  status, both-sided `Claim`s, `mechanistic_chain`, risks, next experiments).
- **`qa`** — natural-language answers grounded in the graph (Claude or offline).

## Cell-engineering vertical (`virtualcell.agents.immortalization`)

The functional domain agent. It recomputes nothing — status/flags/tiers/citations
come from the deterministic layers below and are packaged onto `AgentOutput.result`:

```
ImmortalizationAssessmentAgent
├── deterministic assessment builder   (baseline_status + evidence assembly)
├── passage trajectory engine          (PR7: extract_trajectory + reconcile_markers)
├── mechanism-rule grounding           (Q5/Q6: curated claims + explain paths)
└── hypothesis safety policy           (Q9: P53-independent, no causal overreach)
```

The trajectory engine (`trajectory.py`, `effective_markers.py`) is a *pre-processing*
stage, not a new judge: a raw `observations` series is classified into one of eight
trajectory states under explicit `TrajectoryThresholds`, and its derived PDL/DT trend
replaces the snapshot marker the assessment builder consumes (any material
disagreement is surfaced as an `input_conflict`, never applied silently).
`baseline_status` is unchanged; the `DecisionReport` carries the trajectory as a
plain dict so `reasoning.decision` stays free of any dependency on the agent. A
time series alone never confirms a candidate — the baseline still requires a
measured senescence axis.

## Orchestration (`virtualcell.orchestration`)

A LangGraph graph that routes a request through the relevant agents and merges
their evidence-tagged outputs. In v0.1 this is a minimal single-hop router.

## Simulation (`virtualcell.simulation`)

Defines `CellState`, `TimeStep`, and the `SimulationEngine` interface. The cell is
modeled dynamically over time; concrete engines arrive in later releases.

## API & CLI (`virtualcell.api`, `virtualcell.cli`)

FastAPI exposes `/health`, knowledge, reasoning (`/reasoning/qa`,
`/reasoning/explain`), and agent (`/agents`, `/agents/{name}/run`) endpoints;
registered agents — including `immortalization_assessment` — are reachable
generically, and bad assessment input returns `422`. The CLI mirrors this with
`search`/`neighbors`/`qa`/`explain`/`ingest`/`seed` and
`assess immortalization --input <json>`.

## Extension model

Add capability by (1) implementing a new `BaseAgent`, (2) adding a backend behind
an existing protocol, or (3) adding a `DataSource`. Modules depend only on `core`
protocols, so any piece can be replaced without touching the rest.
