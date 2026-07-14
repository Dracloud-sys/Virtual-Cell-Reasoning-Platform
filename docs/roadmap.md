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
- ✅ **PR2 — minimal domain ontology.** Five node types (`CellLine`, `Marker`,
  `AssayResult`, `Phenotype`, `Mechanism`) + relations (`HAS_RESULT`,
  `INDICATES`, `SUPPORTS`, `CONTRADICTS`, `ASSOCIATED_WITH`, `SUGGESTS`,
  `SUGGESTS_NEXT_TEST`); `explain` reasons over them and persistence round-trips.
- ✅ **PR3 — immortalization seed graph (biologist-reviewed).**
  `ImmortalizationSeedSource` / `virtualcell seed immortalization`: 26 nodes /
  28 edges over the ontology (TERT / CDK4 / p16-RB / p53-p21 / PGC1A axes +
  markers + safety next-tests incl. telomere-length & TERT-activity assays).
  Added `PROMOTES`/`INHIBITS` mechanistic relations. Review fixes applied: CDK4→p16
  documented as a *functional bypass* (not direct p16 inhibition); the
  differentiation edge redirected to `assay INDICATES loss_of_differentiation`;
  single-marker read confidences lowered; spontaneous route softened to a
  "recovery route" description and kept `ASSOCIATED_WITH`/`SUGGESTS`, P53-independent;
  p16/p21 given marker aliases.
  - **Discovered gap (benchmark-first working):** `explain` derives tier from hop
    distance only, so a 1-hop weak `ASSOCIATED_WITH`/`SUGGESTS` edge is mislabelled
    `established`. Fixed in PR4 (relation-aware tier ceiling).
- ✅ **PR4a — relation-aware tier ceiling.** A path's tier is now
  `weaker_of(hop_tier, weakest_edge_ceiling)`, where `ASSOCIATED_WITH`/`SUGGESTS`/
  `SUGGESTS_NEXT_TEST` cap at `hypothesis` and strong relations impose no ceiling;
  relation type stays independent of tier. Fixes the PR3 gap (the 1-hop spontaneous
  route now reads `hypothesis`, not `established`).
- ✅ **PR4b — `DecisionReport` contract.** `reasoning/decision.py`: conclusion,
  candidate_status + flags, supporting/contradicting `Claim`s, `mechanistic_chain`
  (reuses `explain`'s `MechanisticLink` via `DecisionReport.scaffold`), uncertainty,
  overinterpretation_risk, recommended_validation, next_experiment, and
  experimental relevance scores. Shaped so every benchmark `required_output` is
  representable. **Placed in `reasoning/` (not `core/contracts`) to keep `core`
  free of a `reasoning` dependency — flagged for GPT review.**
- ✅ **PR4b-hardening (GPT review).** `DecisionReport` typed: `candidate_status`
  and `flags` are enum-validated (`CandidateStatus` / `AssessmentFlag`, moved to
  `reasoning.decision` and reused by the baseline); added `missing_axes`,
  `conflict_explanation`, `limitations`; relevance scores bounded `[0,1]` and left
  `None`. `AgentOutput` gained an optional `result: dict` so an agent preserves a
  structured `DecisionReport` instead of losing it to `notes`.
- ▶ **PR5 (split per GPT review) — deterministic-first, LLM = presentation only.**
  - ✅ **PR5a** — normalized input model (`ImmortalizationAssessmentInput`,
    benchmark marker vocabulary only) + deterministic `build_decision_report`.
    Status/flags come **only** from `baseline_status`; the builder adds both-sided
    evidence, missing axes, conflict explanation, overinterpretation risk, and the
    validation-axes vs next-experiments split. Mechanism/hypothesis intents are
    rejected explicitly. Benchmark Q1-Q4/Q7/Q8/Q10 run through the builder as a
    regression. (Retention needed its own `RetentionValue` vocab — `MarkerValue`
    can't express `lost`; flagged for GPT review.)
  - ✅ **PR5b** — typed `ConstructType` + Q5/Q6 mechanism-rule catalog
    (`limitations.py`): curated, evidence-tiered supporting *and* limitation claims
    (e.g. Q5 "TERT alone does not bypass p16/RB"; Q6 both arms + genomic-stability /
    differentiation / non-tumorigenicity caveats). Negative claims the graph cannot
    hold live here, not in the graph. Carries `seed_entity_ids` for PR5c to ground,
    internal provenance only (no fabricated citations), and no candidate status.
    (Field named `construct_type`, not `construct`, to avoid a pydantic shadow —
    flagged for GPT review.)
  - ✅ **PR5c-1** — Q5/Q6 graph grounding (`grounding.py`,
    `build_mechanism_report`): combines the catalog's curated claims with
    intent-scoped `explain` paths over the rule `seed_entity_ids` into a mechanism
    `DecisionReport` (no candidate status). Uses a target allowlist **and** a
    weak-relation path filter so the P53-independent spontaneous route (Q9's domain)
    cannot leak into a Q5/Q6 chain via a shared target; missing seed → `GroundingError`.
    (Target-only allowlisting proved insufficient — found by running the demo;
    flagged for GPT review.)
  - ✅ **PR5c-2** — Q9 hypothesis policy (`hypotheses.py`, `build_hypothesis_report`):
    separates the established TERT/PGC1A supporting context from the weak reported
    spontaneous route, preserves "P53-independent" (never P53 loss/knockout/absence),
    never promotes `ASSOCIATED_WITH`/`SUGGESTS` to causation, keeps a required citation
    on the reported-route claim, and fixes status to `insufficient_evidence` **by
    policy** (not baseline). Grounding uses a per-target relation signature (not just a
    target allowlist) so unrelated suggestions and the strong Q6 CDK4→G1/S→proliferation
    path stay out. A `validate_hypothesis_report` guard scans assertion fields for
    forbidden phrasing — it excludes the curated safety-guidance fields, which *name*
    the forbidden phrases to prohibit them (spec conflict resolved; flagged for GPT).
  - ✅ **PR5c-3** — `ImmortalizationAssessmentAgent` (`agent.py`) dispatches by
    intent to the deterministic builder / mechanism grounding / hypothesis policy and
    packages the `DecisionReport` onto `AgentOutput.result` (`model_dump(mode="json")`,
    conclusion in `notes`, claim-mean confidence); a single `input_from_scenario`
    adapter maps the benchmark `construct` key to `construct_type`. The agent
    recomputes nothing. Full Q1-Q10 run end-to-end through `assess()`/`run()` as a
    regression, with status-source boundaries pinned (baseline for assessments, `None`
    for mechanism, policy `insufficient_evidence` for Q9) and a forbidden-phrasing
    safety scan over assertion fields. **The deterministic immortalization prototype
    is complete.**
  - **PR5d** — optional grounded LLM narrative that never changes status/tier/citation.
- ✅ **PR6 — Product-surface integration.** The `ImmortalizationAssessmentAgent` is
  registered (`immortalization_assessment`), reachable via the API
  (`POST /agents/immortalization_assessment/run`, bad input → `422`) and the CLI
  (`virtualcell assess immortalization --input <json>`), with the API/CLI seeding the
  immortalization graph so mechanism/hypothesis reports ground. Docs synced to the
  implemented capabilities and CI normalized (`ruff format`).
- ✅ **PR7 — Passage-aware time-series assessment.** Typed `PassageObservation`
  series (raw DT hours, cumulative PDL, proliferation/viability fraction, endogenous
  TERT/CDK4) feed a deterministic `extract_trajectory` that classifies the
  proliferation course into 8 states (`stable_growth`, `progressive_slowdown`,
  `plateau`, `transient_recovery`, `recovery_after_plateau`, `re_arrest`,
  `conflicting_trajectory`, `insufficient_series`) via explicit `TrajectoryThresholds`.
  A sufficient series' derived PDL/DT trend overrides the snapshot label — surfacing
  any material disagreement as an `input_conflict` — and the `DecisionReport` carries
  the trajectory alongside (never as) the candidate status. Time-series benchmark
  `immortalization_timeseries_v1.{md,yaml}` (TS01–TS12) + the `REALISTIC-IMM-V01`
  representative case. A series alone never confirms immortalization. Reachable
  unchanged through the existing API/CLI (they just accept an `observations` array).
- ✅ **PR7 hardening (real long-culture validation).** Axis-specific quality gating:
  `usable_PDL_timepoints` / `usable_DT_timepoints` are counted separately, a derived
  trend is produced only when its own axis has enough usable points, and low-quality
  axes (`non_monotonic_pdl`, `sparse_passage_sampling`) are blocked from overriding
  the snapshot — the reason is surfaced in `blocked_overrides`. Classification is
  terminal-anchored (`re_arrest` only when the series *ends* arrested; `plateau_interval`
  is the terminal flat run only). The DT trend uses the full stable band, with an
  explicit `unknown` zone (1.25–1.50) instead of rounding to stable, and threshold
  ordering is validated. A single-terminal-point `terminal_dt_spike` signal surfaces
  a late DT spike a whole-series median would dilute. Conflict explanations name
  only the markers that actually contributed. `LONGSERIES-IMM-V01` adversarial fixture
  added. `baseline_status` unchanged.
- ✅ **PR8a — Canonical experiment schema + immortalization adapter (additive).**
  A source-neutral `core.experiment` contract (`ExperimentRun`/`Observation`/scalar
  `Measurement`/`Provenance`, a discriminated `TimePoint`, orthogonal
  `OriginKind` ⟂ `AcquisitionMode`) that simulation and experiment data converge to,
  plus an immortalization adapter to/from `PassageObservation`. No path migrated.
- ✅ **PR8b — Automated literature discovery (first slice).** `virtualcell.literature`:
  contracts (query, article metadata, source-anchored candidates, transparent relevance,
  verification status, `LiteratureEvidenceBundle`); a bounded, injectable `EuropePmcProvider`
  over the official public API; deterministic query building / dedup / relevance; and a
  `LiteratureDiscoveryAgent` (+ `virtualcell literature discover` CLI) returning the typed
  bundle — **no biological claims, no KnowledgeStore writes**. Discovery is not evidence.
- ▶ **PR8c/PR8d — extraction + verification + canonical conversion.** Source-grounded
  JATS/table extraction with an optional strict-schema LLM extractor; a deterministic
  verification gate; conversion of *verified* measurements to canonical `ExperimentRun`s;
  reviewed ingestion. Contracts already exist in the bundle.
- ▶ **PR7+ / later** — remaining marker axes used only for *presentation* today
  (proliferation fraction, endogenous TERT/CDK4, quantitative p16/p21/γH2AX) still
  need assay-aware normalization before they can move status; and the optional
  grounded **PR5d** LLM narrative (never changes status/tier/citation) is still open.

Deferred to a later provenance PR (PR6+): per-edge `evidence_tier` on `Edge`
(so a single-paper `PROMOTES` isn't treated as strong as a textbook one) — it
touches persistence and every connector, so it waits until benchmarks demand it.

Deliberately deferred: relevance/actionability axes on `Claim` (only after a
benchmark failure proves the need), free-form BYOD CSV / arbitrary column mapping,
broad ontology, and early Neo4j. (Deterministic passage-series trend modelling
landed in PR7; ML change-point detection and multi-condition comparison remain out.)
