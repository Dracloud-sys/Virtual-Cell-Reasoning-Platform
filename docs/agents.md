# Agent Catalog

Agents are one of the two ways a capability reaches users; domain packs are the
other, and the newer one. Each agent declares the same contract (see
`virtualcell.core.agent.BaseAgent`):

- **responsibilities** — what it is accountable for
- **inputs** — an `AgentInput`
- **outputs** — an `AgentOutput` carrying evidence-tagged `Claim`s
- **memory** — injected `MemoryStore` (optional)
- **reasoning** — implemented in `run()`
- **confidence** — `estimate_confidence()`

## Two registries, and they do not hold the same things

Since PR11 a capability can reach users through either of two independent
registries, and conflating them is the single most common way this document has
drifted from the code:

| Registry | Surface | What it holds |
|---|---|---|
| `virtualcell.core.registry` | `virtualcell agents`, `POST /agents/{name}/run` | `BaseAgent` implementations — the catalog below |
| `virtualcell.platform.domains.DomainRegistry` | `virtualcell query`, `POST /reasoning/query`, `GET /reasoning/domains` | `DomainPack` implementations — see [Domain packs](#domain-packs) |

A vertical does **not** have to be a `BaseAgent`. Immortalization is both (for
historical reasons — it predates the platform seam); adipogenesis and
genome-edit validation are domain packs only, and do not appear in
`virtualcell agents`.

## Agents

Four of the nine registered agents are functional; the remaining five are
interface stubs sharing `agents/base_stub.py`, which returns a single honest
`speculative` placeholder claim so the orchestration flow stays exercisable.

| Agent (registry name) | Responsibility (summary) | Status |
|-------|--------------------------|--------|
| Immortalization Assessment (`immortalization_assessment`) | Turn normalized experiment markers into an evidence-graded `DecisionReport` | **functional** |
| Literature (`literature`) | Query the knowledge base and return each hit as an evidence-tagged `Claim` | **functional** |
| Literature Discovery (`literature_discovery`) | Discover external papers via Europe PMC, and optionally extract → verify → convert → weakly ingest them | **functional** |
| Validation (`validation`) | Check evidence-tier hygiene of other agents' claims (speculative needs assumptions, established needs citations) | **functional** |
| Genome (`genome`) | Sequence, gene models, variant context | interface stub |
| Transcription (`transcription`) | Transcription & RNA-level regulation | interface stub |
| Protein Interaction (`protein_interaction`) | Protein–protein interaction reasoning | interface stub |
| Metabolism (`metabolism`) | Metabolic network and flux reasoning | interface stub |
| Signaling (`signaling`) | Cell signaling cascade reasoning | interface stub |

## Domain packs

Reached through the domain-neutral query boundary, never by name in the API or
CLI. Each declares itself via `describe()`, so the axes below are the pack's own
declaration rather than a copy maintained here.

| Domain | Tasks | Decides | Status |
|---|---|---|---|
| `immortalization` | `assess_state`, `explain_mechanism`, `handle_hypothesis` | Whether a line is an immortalization *candidate* — never whether it is safe, stable or functional | **functional** |
| `adipogenesis` | `assess_state`, `explain_mechanism` | How far an adipogenic differentiation program has run, keeping "we did not look" apart from "we looked and it was not there" | **functional** |
| `genome_editing` | `assess_state`, `explain_mechanism` | Whether a clone carries the intended edit — and refuses when the assay cannot read an allele ("a band is not a genotype") | **functional** |

Run `virtualcell query --input <ReasoningQuery json>` or
`GET /reasoning/domains` for the live list; nothing here is hard-coded into a
surface.

### Immortalization Assessment agent

`ImmortalizationAssessmentAgent` dispatches by intent and recomputes nothing —
status/flags/tiers/citations come from the layers below:

```
ImmortalizationAssessmentAgent
├── deterministic assessment builder   (baseline_status + evidence assembly)
├── passage trajectory engine          (extract_trajectory + reconcile_markers)
├── mechanism-rule grounding           (Q5/Q6: curated claims + graph paths)
└── hypothesis safety policy           (Q9: P53-independent, no causal overreach)
```

Run it in Python (`agent.assess(...)` / `agent.run(...)`), via the API
(`POST /agents/immortalization_assessment/run`), or the CLI
(`virtualcell assess immortalization --input assessment.json`). The optional LLM
narrative layer is out of scope here (it may never change status/tier/citation).

When the input carries an `observations` array (raw per-passage DT/PDL series),
the trajectory engine derives the trend deterministically, classifies the
proliferation course (`stable_growth` … `re_arrest` / `conflicting_trajectory`),
and — if the derived trend disagrees with a provided snapshot label — uses the
series value and records the disagreement in `input_conflicts`. The trajectory is
reported alongside, never as, the candidate status. See
`examples/03_passage_trajectory_assessment.py`.

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

## Adding a reasoning vertical

For a new biological domain, add a **domain pack**, not an agent — that is the
path the API and CLI already reach without change:

1. Write the benchmark first: `tests/benchmarks/eval_<domain>_v0.py` plus its
   question set. `scripts/verify.py` discovers scorecards by glob, so it needs
   no registration.
2. Put the scientific rules in `virtualcell/agents/<domain>/` and the curated
   seed graph in `virtualcell/knowledge/sources/<domain>_seed.py`.
3. Implement the `DomainPack` protocol in
   `virtualcell/platform/packs/<domain>.py`: `domain`, `supported_tasks`,
   `describe()`, `validate_experiment()`, `execute()`. Derive the consumption
   ledger and the missing-input list from your `DomainDescription` rather than
   hand-maintaining a second list.
4. Add one line to `SHIPPED_DOMAINS` in `virtualcell/platform/bootstrap.py`.
   That is the whole composition change — no API, CLI or kernel edit.
5. Expect the reasoning kernel to need **zero** changes. It needed none for the
   second or third vertical; if yours forces one, that is a finding about the
   boundary, not a routine edit.
