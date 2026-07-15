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

## Canonical experiment schema (`virtualcell.core.experiment`)

A **source-neutral data contract** that virtual-cell *simulation* output and
*experiment* data both converge to before any vertical reasoning. The pipeline the
platform is building toward is:

```
Canonical Experiment Schema   = source-neutral data contract  (core.experiment)
        │  (per-vertical adapter)
Immortalization adapter       = canonical data -> the first vertical's input
        │
Trajectory / reconciliation   = immortalization-specific deterministic reasoning
        │
DecisionReport                = reasoning output contract
        │
(optional) LLM narrative      = presentation only, never changes status/tier/citation
```

`core.experiment` is deliberately domain-agnostic (`OriginKind` ⟂ `AcquisitionMode`,
a discriminated `TimePoint`, scalar `Measurement` + `Provenance`, `Observation`,
`ExperimentRun`) and imports nothing from `agents`/`reasoning`. The immortalization
**adapter** (`agents/immortalization/adapters.py`,
`passage_observation_to_canonical` / `canonical_to_passage_observation` /
`passage_series_to_run` / `run_to_passage_series`) maps canonical runs to and from
`PassageObservation`; it only reshapes data and performs no trajectory extraction,
reconciliation, or status judgment.

Scope today: this is the *foundation contract plus the first adapter*. It does **not**
yet connect a real simulator, robot, or LIMS, and the existing immortalization
input/API/CLI are unchanged — the canonical schema is additive, not a migration.

## Literature discovery (`virtualcell.literature`)

Automated literature evidence, with one rule above all: **finding/reading a paper is
not the same as that paper being verified evidence.** The layers are kept distinct so
a discovery result — or an LLM's reading — can never leak into the graph as fact:

```
LiteratureAgent (existing)      = retrieval over already-ingested KnowledgeStore entities
LiteratureDiscoveryAgent (new)  = external paper discovery -> metadata + evidence *candidates*
Verification layer              = deterministic gate: does a candidate match its source text?
Canonical ExperimentRun         = verified quantitative observations only
Knowledge graph                 = reviewed / approved biological claims only
```

PR8c adds **source-grounded extraction**, still strictly upstream of evidence.
`literature.documents` parses open-access JATS safely (DOCTYPE/ENTITY declarations
refused, bounded size/sections/tables/cells, typed `JatsParseError`, no-body treated as
a warning), keeping the parsed body in-process — only `DocumentMetadata` (identifier,
`content_hash`, counts, warnings) enters a bundle, never the full text.
`literature.extraction` extracts only what an `ExtractionTask` asks for (a table cell
becomes a candidate only when an axis label matches a requested measurement), keeps
values split (`raw_value` / `parsed_value` / `comparator` / `uncertainty` / `unit` /
`parse_status`) so a bound is never a point estimate and qualitative text never gains a
number, and puts every extractor — including the optional `StructuredLiteratureExtractor`
(LLM) — behind `accept_candidates`, which re-checks each locator and number against the
real document. That is extraction *integrity*, not verification: **all PR8c candidates
are unverified**, `verification_decisions` and `canonical_runs` stay empty, and the
verification gate + canonical conversion are PR8d.

PR8b implements the discovery slice: `literature.contracts` (query, article metadata,
source-anchored candidates with deterministic ids, transparent relevance, verification
status, and the `LiteratureEvidenceBundle`); a bounded, injectable `EuropePmcProvider` over
the official public API (no scraping, no paywall circumvention); and deterministic query
building, deduplication, and relevance scoring. Dedup merges on strong ids (PMCID/PMID/DOI)
and only falls back to title when it does not contradict a strong id — distinct papers are
never merged away. `QueryMode` (default `terms` = AND of word tokens for recall; `phrase`
for exact-phrase precision) is recorded in provenance. A machine-readable `DiscoveryRunStatus`
(`success`/`zero_results`/`provider_error`) distinguishes an empty result from a failure — the
CLI exits non-zero only on `provider_error` — and `VerificationDecision` is the authoritative
status a candidate is checked against. `LiteratureDiscoveryAgent` returns the typed bundle
in `AgentOutput.result` and **no biological `Claim`s** — discovery metadata is not
evidence, and `AgentOutput.confidence` is not the relevance score. Nothing here writes to
the KnowledgeStore. Source-grounded extraction (JATS/tables + an optional structured LLM
extractor behind a strict schema), the deterministic verification gate, and conversion of
*verified* measurements to canonical runs are the next slices (PR8c/PR8d); their contracts
already exist in the bundle. A paper is never treated as true merely because it was read.

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
