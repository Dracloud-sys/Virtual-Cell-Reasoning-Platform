# Roadmap

The platform grows through 12 stages. Each stage extends or replaces existing
modules rather than rewriting the system. The guiding rule: prioritize decisions
that move the project closer to a full digital organism.

| Stage | Name | Status |
|------:|------|--------|
| 1 | Cellular Knowledge Base | **In progress (v0.1: working in-memory core)** |
| 2 | AI-assisted Literature Mining | Interface stub (Literature Agent) |
| 3 | Gene Regulatory Network Modeling | Planned |
| 4 | Cell Signaling Network | Interface stub (Signaling Agent) |
| 5 | Epigenetic Regulation | Planned |
| 6 | Metabolic Network | Interface stub (Metabolism Agent) |
| 7 | Protein Interaction Network | Interface stub (Protein Interaction Agent) |
| 8 | Cellular State Prediction | Planned |
| 9 | Digital Cell | Planned |
| 10 | Digital Tissue | Planned |
| 11 | Digital Organ | Planned |
| 12 | Digital Organism | Planned |

## Strategic positioning (decided 2026-07-06)

The platform's defensible identity is an **interpretable, evidence-graded
mechanistic reasoning layer** — *not* a data-driven perturbation predictor.

Rationale, informed by two reference works:

- **AlphaCell** (bioRxiv, 2026) — a data-driven "Virtual Cell World Model"
  trained on 220M cells / 1.2B params. State-of-the-art at predicting *what*
  changes (genome-wide expression under a perturbation), but a black box, unable
  to handle novel compounds, transcriptome-only, and infeasible to reproduce at
  small scale.
- **"How to build the virtual cell with AI"** (Bunne et al., *Cell* 2024) — the
  field's blueprint (Universal Representations + Virtual Instruments). It names
  **interpretability, mechanism, calibrated uncertainty, hypothesis-space
  narrowing, and non-expert agent interfaces** as the hardest, least-solved
  challenges.

Those unsolved challenges are precisely what this platform already designs for:
`EvidenceTier` + `confidence`, a provenance-tagged symbolic knowledge graph, and
an agent-first architecture. So we do **not** compete with predictors like
AlphaCell — we complement them: where a predictor says *what* changes, we explain
*why, through which pathways, and how confidently*, with citations.

### Capability stack for this identity (build order)

1. **Evidence-graded multi-hop reasoning primitive** — from a seed entity,
   traverse the graph and return affected entities with their path, the evidence
   tier of the weakest edge on the path, and a `combine_confidences`-composed
   score. (Buildable on the current gene→protein→pathway graph.)
2. **Edge enrichment** — protein–protein interactions (IntAct/STRING,
   `INTERACTS_WITH`) and gene-regulatory edges, to make propagation mechanistic.
3. **Compound layer** — drug–target data (ChEMBL) as the entry point for
   "substance → target → mechanism" reasoning.
4. **LLM agent interface** — natural-language question in, cited evidence-graded
   mechanistic hypothesis out (realizes the agent-first design).
5. **Biological benchmarks** — validate reasoning against known biology,
   answering the "how do we build trust?" question.

Persistence (JSON snapshot or the stubbed Neo4j backend) is folded in around
step 3, when the merged graph becomes worth keeping across sessions.

## Biological hierarchy respected across stages

```
Genome → Epigenome → Transcriptome → Proteome → Metabolome
       → Cell State → Cell Behavior → Tissue Dynamics
```

## v0.1 scope

- Working Stage 1 knowledge base (in-memory), with graph/vector backends as
  interfaces.
- Full architecture scaffold: agents, orchestration, simulation, API, CLI.
- Reference stub agent (Literature) demonstrating the query → evidence-tagged
  `Claim` flow.

## Near-term (post v0.1)

Reprioritized per the strategic positioning above.

- ✅ First real data-source ingestion: **Reactome** and **UniProt** connectors,
  with cross-source protein enrichment (`virtualcell ingest`).
- ✅ Evidence-graded multi-hop reasoning primitive (`virtualcell explain`,
  `GET /reasoning/explain/{id}`): direct edges are `established`, multi-hop
  inferences are downgraded to `hypothesis`/`speculative`, confidence decays with
  path length and is corroborated across paths.
- ✅ Natural-language Q&A grounded in the graph (`virtualcell qa`,
  `POST /reasoning/qa`): Claude backend + offline fallback.
- ✅ `explain` paths fed into the `qa` agent so natural-language answers cite
  directed, evidence-graded multi-hop mechanistic chains, not just direct facts.
- ✅ Persistence (JSON snapshot; Neo4j later): `ingest --save`/`--load` and a
  `--load` flag on the query commands, so an ingested graph survives across
  sessions and real genes (TERT, CDK4, ...) become queryable.
- ◐ Edge enrichment: **PPI done** (IntAct `INTERACTS_WITH`), so reasoning spans
  protein↔protein mechanistic chains. Gene-regulatory (TF→target) edges later.
- Compound (ChEMBL) layer for "substance → target → effect" reasoning (later).

## Cell-engineering vertical (near-term wedge)

The 12-stage roadmap remains the **north star**, but near-term development is
focused on a concrete, defensible wedge: an **immortalization candidate
assessment assistant** for cell engineering (bovine/cultured-meat context). The
generic Reactome/UniProt/IntAct graph is the horizontal *substrate*; this vertical
is where the platform earns its keep. See the plan behind this in the project's
strategy notes and the benchmark in [`../tests/benchmarks/`](../tests/benchmarks/).

Development is **benchmark-first**: fix the questions the platform must answer
*before* touching `core`, then let real failures justify any `core` change.

- ✅ **PR1 — Benchmark landed.** `tests/benchmarks/immortalization_v0.{md,yaml}`
  (10 questions, 3-status vocab, rubric) + a deterministic rule-based
  `baseline_status` (`agents/immortalization/baseline.py`) + a CI regression that
  freezes the baseline↔spec self-check (8/8 status questions).
- ▶ **PR2** — minimal domain ontology (`CellLine`, `Marker`, `AssayResult`,
  `Phenotype`, `Mechanism` + relations like `INDICATES`/`SUPPORTS`/`CONTRADICTS`).
- **PR3** — immortalization seed graph (TERT/CDK4/TP53/RB1/CDKN2A/CDKN1A/PGC1A +
  senescence markers), with the "P53-independent" spontaneous route seeded as
  `ASSOCIATED_WITH`/`SUGGESTS` (never `CAUSES`).
- **PR4** — `DecisionReport` contract (reuses `explain`'s `MechanisticLink` for
  the mechanistic chain).
- **PR5** — `ImmortalizationAssessmentAgent` v0 (rule-based first, LLM synthesis
  after).

Deliberately deferred: relevance/actionability axes on `Claim` (only after a
benchmark failure proves the need), time-series/trend modelling, free-form BYOD
CSV, broad ontology, and early Neo4j.
