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
  `ground` (classify) and `synthesize` (render + call the backend) are separate, so
  evidence is tiered before any backend sees it.

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
`literature.extraction` extracts only what an `ExtractionTask` asks for and puts every
extractor — including the optional `StructuredLiteratureExtractor` (LLM) — behind the
same `accept_candidates(document, result, task)` gate. That is extraction *integrity*,
not verification: **all PR8c candidates are source-grounded but unverified** — finding
or reading a paper is never itself a biological fact. Canonical conversion (turning a
verified measurement into an `ExperimentRun`) remains PR8d-2.

Extraction policies (deterministic, and applied to every extractor):

- **Targeting.** A table cell becomes a measurement candidate only when an axis label
  matches a requested measurement; a candidate whose `measurement_name` is not a
  requested target, or does not match its cited cell's row/column label (with the
  `sample_group` on the opposite axis of the *same* cell), is rejected. "The paper has
  a number" is never sufficient.
- **Exact-cell anchoring.** `SourceLocator` carries `row_index`/`column_index`, and all
  of {coordinates, row/column label, source_text, and any parsed number} must hold on
  one and the same cell — a locator cannot be assembled from parts of different cells.
- **Statistical columns.** p-value / adjusted-p / q-value+FDR / CI / n / SD·SEM·error
  columns are recognised and never extracted as a biological measurement. A candidate
  that explicitly targets a statistic axis is kept but tagged `statistic` — it is *not*
  a biological measurement and is out of scope for PR8d canonical mapping.
- **Value discipline.** Values are split (`raw_value`/`parsed_value`/`comparator`/
  `uncertainty`/`unit`/`parse_status`): a bound (`<0.05`) keeps its comparator, an error
  (`2.4 ± 0.3`) is kept apart, qualitative text (`increased`/`NS`) stays UNPARSED, and
  `1,234` is left UNPARSED (ambiguous separator). No number is ever invented.
- **`target_contexts` is reserved** — it does not filter extraction in this version
  (supplying it emits a warning).
- **Source-kind anchoring.** Abstract locators check the abstract only; section locators
  must name a section and match its text; figure/supplementary locators are rejected as
  unsupported by the current parser.
- **Bounds.** `ExtractionTask.max_candidates` is a per-*document* cap and
  `max_total_candidates` a run-wide cap; the agent applies both in a fixed order
  (accept → de-duplicate by `candidate_id` → per-document cap → global cap), with an
  optional extractor's failure isolated to its own document.

**PR8d invariant.** A candidate tagged `statistic` is a statistic *about* a measurement,
not a measurement, and must never be converted to a canonical `ExperimentRun`.

PR8d-1 adds the **deterministic verification gate** (`literature.verification`), a
separate layer between extraction and canonical conversion. `verify_candidates(document,
result, task)` re-checks each candidate against the *current* document — reusing the same
PR8c `accept_candidates` boundary, so there is one rulebook — and emits exactly one
`VerificationDecision` per candidate (deterministic, input never mutated, `verified_at`
injectable and timezone-aware, the judged source span's hash recorded). It is
conservative: only an exact, re-verified, quantitative **table cell** measurement
(`parse_status == parsed`, a `parsed_value`, `statistic is None`) is `MACHINE_VERIFIED`.
Abstract/section **prose**, qualitative/unparsed values, statistic-tagged measurements,
every claim and every author interpretation are `PENDING_REVIEW` (their meaning is a
semantic judgement a machine must not make). Anything whose source integrity no longer
holds — drift, wrong coordinates or labels, a value or target mismatch, unsupported
numeric notation — is `REJECTED`, never softened to pending. A candidate still carries no
status of its own; `VerificationDecision` is the sole authority. Verification is an
explicit opt-in on the agent (`verify: true`, which requires `extract: true`): a run
verifies only the candidates it *retained* after the caps (no orphan decisions),
`canonical_runs` stays empty, and nothing is written to the KnowledgeStore.

PR8d-2 adds **canonical conversion** (`literature.canonical`), the step between a
verified measurement and evidence storage. `experiment_runs_from_verified(measurements,
decisions)` links each decision to its candidate by `candidate_id` and turns **only** a
`MACHINE_VERIFIED` measurement into a source-neutral `core.experiment.ExperimentRun` — a
`PENDING_REVIEW`/`REJECTED` decision, a claim, an author interpretation and a
`statistic`-tagged candidate are all skipped (defensively re-checked, so a statistic can
never become a run). The run carries full provenance (`origin_kind=experiment`,
`acquisition_mode=imported`, article ids, exact locator, source-text hash, the
verification decision, and the raw value with its comparator/uncertainty preserved as
measurement quality flags); units/comparators/uncertainty/target/conditions map onto the
canonical contract. Conversion is deterministic — the same verified measurement always
yields the same `run_id`, and duplicate inputs collapse to one run — and a run only ever
references a *retained* (post-cap) candidate. It is a further opt-in (`convert: true`,
which requires `verify: true`); only successful conversions land in `canonical_runs`, and
this module still writes nothing.

PR8e adds **reviewed ingestion** (`literature.ingestion`), the first and only path that
writes literature evidence into a `KnowledgeStore` — and it does so *cautiously*, because
a single machine-verified number is not a mechanism. `ingest_runs(store, runs)` writes,
per canonical run, a `lit:`-namespaced `Marker` (the measured target) and `AssayResult`
(the measurement, carrying the full canonical provenance verbatim), linked by the **weak,
symmetric** `ASSOCIATED_WITH` relation at a fixed conservative confidence. No
`PROMOTES`/`INHIBITS`/`REGULATES`/`INDICATES` or any causal/established edge is ever
created here, every node and edge is tagged `review_status = "pending_review"` so it is
never silently merged into curated truth and can always be re-reviewed, and ingestion is
deterministic and idempotent (re-ingesting the same run upserts the same nodes and does
not duplicate the edge). It is a final opt-in on the agent (`ingest: true`, which requires
`convert: true` **and** an injected `knowledge_store` service): every earlier stage
(discovery, extraction, verification, conversion) still leaves the store untouched.

PR9 adds the **integrated evidence-query orchestrator** (`orchestration.query`), one
entry point that unifies the two evidence sources while keeping their epistemic status
distinct. `EvidenceQueryOrchestrator.answer` first grounds the question in the curated KB
(the unchanged `QuestionAnswerer` path); on a **miss** it consults literature —
discovery → extraction → verification → canonical conversion → weak-evidence ingestion —
and surfaces what survives as clearly **weak, pending-review** facts, never synthesized
into a confident answer (so a possibility is never phrased as a conclusion). It is a
*separate* layer over the existing pieces, not a fallback bolted into `qa.py`, and it
enforces the tier boundary the store cannot: a `lit:` node is never an established KB hit,
a literature fact surfacing alongside a curated answer is downgraded to `HYPOTHESIS`, and
a repeat query re-surfaces previously ingested evidence (still weak) instead of
re-discovering it.

**Classification precedes synthesis (PR10a).** Because the curated graph and ingested
literature share one store, a retrieval can return both — so `qa.ground` assigns tiers
*before* `qa.synthesize` renders the evidence block for a backend. Evidence is capped
below `ESTABLISHED` and explicitly labelled at grounding time, so no backend — offline
template or LLM — can ever be handed unreviewed evidence dressed as curated truth, and the
natural-language answer carries exactly the tiers the structured facts report.

What counts as provisional is decided by **one shared predicate**,
`core.evidence.is_unreviewed`, which lives in domain-neutral `core` so no layer
re-implements it and `reasoning` needs no dependency on the literature pipeline. It treats
two *independent* signals as sufficient on their own:

1. an explicit `review_status = "pending_review"` property on a node, and
2. an entity id or citation in a namespace reserved for unreviewed evidence (`lit:`).

Either alone caps the fact, because neither reliably accompanies the other — a fixture,
migration, or hand-built graph can create a `lit:` node with no review property, while a
future non-`lit:` source may carry the property alone. Grounding passes every anchor a
fact rests on (the node, both endpoints of a mechanistic path, the composed citation), so
a path is only as strong as the weakest node beneath it. The predicate can only ever
weaken a tier, never strengthen one, and it protects every caller — the orchestrator,
`/reasoning/qa`, and the CLI alike. The orchestrator's split of curated from literature
facts uses the same predicate purely for *reporting*; it never re-tiers. Literature
evidence is *never hidden* to achieve any of this: it stays in the answer, visible and
labelled, just never established.

PR9-b closes the last benchmark gap: `agents.immortalization.mechanism.build_mechanism_report`
formats the mechanism (Q5/Q6) and hypothesis (Q9) intents — which the assessment builder
refuses — into `DecisionReport`s. The mechanistic chain is derived from the seed graph with
`explain` (auditable, tier-graded, weak edges capped at `hypothesis`) and the domain
limitations/caveats/claim-decomposition are curated tier-tagged statements. It respects the
benchmark guardrails: TERT alone is not sufficient, immortalization is never conflated with
safety or function, and Q9's spontaneous route stays a hypothesis stated as *P53-independent*
— never a P53-negative reduction, never `CAUSES`. The re-eval harness now scores all ten
questions (Q5/Q6/Q9 at 12/12).

PR9-c adds **entity resolution** (`literature.resolution.resolve_literature_markers`): a
`lit:marker` is bridged onto the curated ontology node carrying the same
name/symbol/alias, by a weak, reviewable `ASSOCIATED_WITH` edge, so discovered evidence
becomes reachable from the known graph without being merged into it or upgraded past
`hypothesis`. Matching is conservative — an exact normalized name/symbol/alias only (no
fuzzy matching, no synonyms) — and an ambiguous match (several curated candidates) is left
unresolved rather than guessed; resolution is deterministic and idempotent. The
orchestrator runs it right after ingestion, and because `explain` caps a weak-edge path at
`hypothesis` and the orchestrator downgrades any `lit:`-citing fact, a later curated hit
that reaches the bridged literature evidence still surfaces it as weak.

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
evidence, and `AgentOutput.confidence` is not the relevance score. By default nothing
here writes to the KnowledgeStore — only the explicit `ingest: true` opt-in does.
Source-grounded extraction (PR8c), the deterministic verification gate (PR8d-1), canonical
conversion of verified measurements (PR8d-2), reviewed weak-evidence ingestion (PR8e) and
the integrated KB→discovery→evidence query orchestrator (PR9) are now in place. A paper is
never treated as true merely because it was read.

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
