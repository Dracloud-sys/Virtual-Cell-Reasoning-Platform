# Roadmap

The platform grows through 12 stages. Each stage extends or replaces existing
modules rather than rewriting the system. The guiding rule: prioritize decisions
that move the project closer to a full digital organism.

> **Scope.** VCRP is a **general biological experiment reasoning platform**:
> data in → assay-aware QC and normalization → canonical representation → reasoning over
> experimental, biological and literature evidence → explained research decisions.
> **Immortalization is the first validated reasoning vertical and reference
> implementation**, not the product's subject. As of PR11 it is registered as the first
> *domain pack* behind a domain-neutral query boundary; PR12–PR14 add the canonical
> schema, raw-data ingestion/QC, and the generic reasoning kernel. Adipogenesis then lands
> as the second domain pack — partly *before* PR14b, because shared decision assembly needs
> a second implementation to be extracted from — and a third domain tests cross-domain
> generality. Knowledge-learning and non-expert explanation are later platform layers.

| Stage | Name | Status |
|------:|------|--------|
| 1 | Cellular Knowledge Base | **In progress** — working in-memory graph, Reactome/UniProt/IntAct connectors, JSON-snapshot persistence, three curated domain seed graphs. Neo4j/Qdrant remain interface skeletons. |
| 2 | AI-assisted Literature Mining | **Functional pipeline** (PR8b–PR9c) — Europe PMC discovery → source-anchored extraction → deterministic verification → canonical conversion → reviewed weak ingestion → entity resolution. Everything it writes stays `pending_review` and weak. |
| 3 | Gene Regulatory Network Modeling | Planned (TF→target edges in the backlog) |
| 4 | Cell Signaling Network | Interface stub (Signaling Agent) |
| 5 | Epigenetic Regulation | Planned |
| 6 | Metabolic Network | Interface stub (Metabolism Agent) |
| 7 | Protein Interaction Network | **Partial** — IntAct `INTERACTS_WITH` edges are ingested and traversed; the dedicated Protein Interaction Agent is still an interface stub |
| 8 | Cellular State Prediction | Planned |
| 9 | Digital Cell | Planned |
| 10 | Digital Tissue | Planned |
| 11 | Digital Organ | Planned |
| 12 | Digital Organism | Planned |

The 12 stages are the north star and describe the *biological* ladder. They do
not track the platform work that actually ships week to week — the domain-neutral
reasoning boundary, the canonical experiment schema, ingestion/QC, the reasoning
kernel and the verticals built on it. That sequence is recorded in
[Platform sequence after PR11](#platform-sequence-after-pr11) below, and it is
the list to read for current status.

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

## v0.1 scope (historical — what the first release set out to do)

- Working Stage 1 knowledge base (in-memory), with graph/vector backends as
  interfaces.
- Full architecture scaffold: agents, orchestration, simulation, API, CLI.
- Reference agent (Literature) demonstrating the query → evidence-tagged
  `Claim` flow. *(Written when it was the only working agent; it has since been
  joined by Literature Discovery, Validation and Immortalization Assessment, and
  by three domain packs behind the platform seam. See
  [`agents.md`](agents.md) for current status.)*

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
- ✅ **PR8c — Source-grounded extraction.** Deterministic JATS/table extraction plus an
  optional strict-schema LLM extractor, every candidate behind one `accept_candidates`
  integrity gate (targeting, exact-cell anchoring, value discipline, statistic tagging,
  fixed numeric grammar). All candidates are source-grounded but **unverified**.
- ✅ **PR8d-1 — Deterministic verification gate.** `literature.verification` re-checks
  retained candidates against the current document and emits one `VerificationDecision`
  each. Only an exact, quantitative **table** measurement is `MACHINE_VERIFIED`; prose,
  claims, author interpretations, statistics and unparsed values are `PENDING_REVIEW`;
  source-integrity failures are `REJECTED`. Opt-in via `verify: true` (requires
  `extract: true`); `canonical_runs` stays empty and nothing is written to the graph.
- ✅ **PR8d-2 — Canonical conversion.** `literature.canonical` turns each
  `MACHINE_VERIFIED` measurement into a source-neutral `ExperimentRun` (full provenance:
  article ids, exact locator, source hash, the verification decision, raw value +
  comparator/uncertainty). Only machine-verified measurements convert — prose, claims,
  author interpretations and statistics never do. Opt-in via `convert: true` (requires
  `verify: true`); only successful conversions land in `canonical_runs`, and nothing is
  written to the graph.
- ✅ **PR8e — Reviewed ingestion.** `literature.ingestion` writes each canonical run into
  a `KnowledgeStore` as **weak, reviewable** evidence: `lit:`-namespaced `Marker`/
  `AssayResult` nodes tagged `review_status = "pending_review"`, linked by the weak,
  symmetric `ASSOCIATED_WITH` relation (never `PROMOTES`/`INHIBITS`/`ESTABLISHED`), with
  full provenance on node and edge. Deterministic and idempotent. Opt-in via `ingest:
  true` (requires `convert: true` and a `knowledge_store` service); it is the only path
  that writes to the store, and only under that opt-in.
- ✅ **Benchmark-first re-evaluation (post-PR8).** `tests/benchmarks/eval_immortalization_v0`
  runs all 10 fixed questions through the real `DecisionReport` pipeline and scores the
  machine-decidable rubric axes (0/1/2, pass ≥ 9/12), pinned by
  `test_immortalization_eval`. Result: the **7 assessment questions all pass** (Q1/Q4
  score 11 — a clear senescence case has no "supporting immortalization" side; Q8 scores
  11 — its overinterpretation caveat is generic, not question-specific); the **3
  mechanism/hypothesis questions (Q5/Q6/Q9) are correctly deferred** — the deterministic
  builder refuses them by design and their knowledge (incl. Q9's weak
  `ASSOCIATED_WITH`/`SUGGESTS` edges) already lives in the seed graph, awaiting PR9
  formatting. No status is ever over-called. PR8 left the vertical unchanged (no
  regression).
- ✅ **PR9-a — Integrated query orchestrator (core).** `orchestration.query`
  (`EvidenceQueryOrchestrator`) answers from the curated KB and, on a **miss**, reaches
  for literature — discovery → extraction → verification → canonical conversion →
  weak-evidence ingestion — then surfaces it as clearly **weak, pending-review** facts.
  A separate layer over `QuestionAnswerer` + `LiteratureDiscoveryAgent` (not bolted onto
  `qa.py`); a `lit:` node is never treated as an established KB hit, and any literature
  fact that surfaces alongside a curated answer is downgraded to `HYPOTHESIS`. Ingestion
  is deterministic/idempotent; a repeat query re-surfaces prior evidence without
  re-discovering, still weak.
- ✅ **PR9-b — Mechanism/hypothesis DecisionReports.** The previously deferred Q5/Q6/Q9
  intents are answered as `DecisionReport`s: the mechanistic chain is derived from the
  seed graph with `explain` (auditable, tier-graded, weak edges capped at `hypothesis`),
  and the domain limitations/caveats/claim-decomposition are curated tier-tagged
  statements. TERT alone is not sufficient, immortalization is never conflated with
  safety/function, and Q9's spontaneous route stays a hypothesis stated as
  *P53-independent* — never a P53-negative reduction, never `CAUSES`. The re-eval harness
  scores **all 10/10 questions** (Q5/Q6/Q9 at 12/12), pinned by `test_immortalization_eval`.
  *(Superseded by PR10b: the implementation it originally added was a duplicate of the
  shipped policies and has been removed — see below.)*
- ✅ **PR9-c — Entity resolution.** `literature.resolution` (`resolve_literature_markers`)
  bridges a `lit:marker` onto the curated ontology node carrying the same
  name/symbol/alias, via a weak, reviewable `ASSOCIATED_WITH` edge — so discovered
  evidence is reachable from the known graph without being merged into it or upgraded past
  `hypothesis`. Only an **exact normalized** match resolves (no fuzzy/synonym); an ambiguous
  match is left unresolved. Deterministic and idempotent. The orchestrator runs it after
  ingestion, and a later curated hit reaching the bridged evidence keeps it weak.
- ✅ **PR10a — Epistemic-safe answers.** Fixes a PR9 integrity gap: literature facts were
  downgraded only *after* `QuestionAnswerer` had already synthesized the user-facing
  answer, so `lit:` evidence could still be rendered as `established` inside `answer`
  (and handed to an LLM backend that way) even though the structured facts were correct.
  `qa` now separates `ground` (classify) from `synthesize` (render + backend) and caps
  provisional evidence at grounding time; the orchestrator grounds, partitions, and only
  then synthesizes. One shared predicate, `core.evidence.is_unreviewed`, decides what is
  provisional from **either** an explicit `review_status = "pending_review"` property
  **or** a reserved `lit:` id/citation namespace — either signal alone suffices, so a
  `lit:` node that reaches the store without the property (fixture, migration, hand-built
  graph) is still capped. Every anchor of a fact is checked (node, both path endpoints,
  composed citation). The answer and the structured facts share one classification, and
  the rule protects direct `/reasoning/qa` and CLI callers too. Literature evidence stays
  visible and labelled, never hidden. Verified by a spying backend and by re-running the
  new tests against the pre-fix sources.
- ✅ **PR10b — Benchmark runs the product path.** Fixes a measurement-validity gap: the
  benchmark called `rules.build_decision_report` and a *second* Q5/Q6/Q9 implementation
  directly, while the shipped agent dispatches Q5/Q6 through `grounding.py` and Q9 through
  `hypotheses.py` — so 10/10 did not prove 10/10 through the product. All ten questions now
  run through `ImmortalizationAssessmentAgent.assess`, the API/CLI entry point; the harness
  no longer selects builders by intent (pinned by a call-counting spy and an import guard).
  The duplicate `agents.immortalization.mechanism` was **removed** in favour of the
  production policies, which are stricter (target allowlists, relation signatures,
  validation, conditional CDK4 wording). Adds `assess()`↔`run()` parity tests for Q5/Q6/Q9.
  **Q6 rubric correction:** the key point `non_oncogenic_reliable` rewarded an unsupported
  safety claim and was replaced by `distinct_from_viral_oncogene_approaches` +
  `non_tumorigenicity_requires_separate_validation`; the pass threshold is unchanged.
  **Scorer correction:** forbidden-phrase checks now scan assertion fields only
  (`hypotheses.assertion_texts`), so guidance that quotes a phrase to forbid it — "P53-
  independent does not mean P53 loss" — is no longer a false positive.
- ✅ **PR11 — Generic reasoning query and domain dispatch boundary.** Establishes the
  domain-neutral platform seam: `platform.contracts` (`ReasoningQuery` /
  `ReasoningResponse`), `platform.domains` (`DomainPack` + `DomainRegistry`),
  `platform.service` (`ReasoningService` — one application entry point for API *and* CLI),
  and `platform.packs.immortalization`, the **first domain pack**, wired to the real
  `ImmortalizationAssessmentAgent` path without duplicating any scientific rule. Adds
  `POST /reasoning/query`, `GET /reasoning/domains` and `virtualcell query`. Unknown
  domains and unsupported tasks fail explicitly and never fall back to immortalization;
  literature states (`not_requested` / `unavailable` / `success` / `zero_results` /
  `provider_error` / `timeout`) are distinguishable and a failure never becomes evidence.
  PR10's epistemic safeguards and the 10/10 benchmark are unchanged.

### Platform sequence after PR11

VCRP is a general biological experiment reasoning platform; immortalization is its first
reference domain pack. The remaining platform layers, in order:

- ✅ **PR12 — Canonical Experiment Schema v1.** The PR8a `ExperimentRun` contract is now
  explicitly **versioned**: `schema_version` is *mandatory* on every run — an unversioned
  payload is refused rather than assumed to be v1 forever, and pre-versioning payloads load
  only through the explicit `load_legacy_run` migration. The `MAJOR.MINOR` policy is
  documented and enforced: a newer *minor* is accepted (minors are additive) and its
  unknown fields are **preserved** through validate → bundle → serialize rather than
  silently dropped, while a different *major* is refused (`SchemaVersionError`) rather than
  misread. The real producers and consumers are wired to it, not just the contract:
  `literature.canonical` and `passage_series_to_run` emit the version explicitly,
  `run_to_passage_series` validates before reading field meanings out of a structure it did
  not build, `LiteratureEvidenceBundle` refuses an incompatible run at the
  storage/transmission boundary, and `literature.ingestion` skips and reports one. Three v1
  decisions land with it, ahead of PR13: **namespaced run identity** (`<namespace>:<local>`,
  so two minting systems cannot collide), **typed measurement values** (numeric /
  categorical / boolean, so a numeric assay cannot silently hold a string, read through
  `Measurement.numeric_value()`), and **condition precedence** (observation-level keys
  override run-level, resolved by the single `ExperimentRun.effective_conditions` helper).
  Run checksums / content-hash dedup were deferred to PR13a, where they landed.
- ✅ **PR13a — Run integrity and identity.** Closes PR12's checksum/dedup deferral. Two
  hashes, because "was this modified?" and "do I already have this?" are different
  questions: `content_checksum` covers everything the run says (and works at any declared
  version, since hashing bytes needs no understanding of the fields), while `dedup_key`
  covers only what the run *observed* and **refuses a newer minor** — the hash spans the
  field set this reader knows, and a newer minor may have added the very field that tells
  two runs apart, so "cannot decide" is never reported as "same". Ordering is stated rather
  than inherited from the serializer: observation order is significant (it is the
  trajectory), while measurements within an observation, quality flags and condition keys
  are sets and are normalized. `deduplicate_runs` keeps the first of each group, names every
  collapse, and reports a structured `DedupCollision` whenever two collapsed runs do not
  serialize identically. Adds the optional, self-verifying `ExperimentRun.checksum`, which
  is additive and therefore the schema's first **minor** bump: **1.0 → 1.1**.
- ✅ **PR13b — Declared tabular ingestion, QC and normalization.** **CSV/TSV only.** Driven
  by a declared, versioned `DatasetSpec`, never by column inference — free-form BYOD CSV
  with arbitrary column mapping stays deferred. Keeps the literature layer's three-layer
  separation (parsed cell candidate → QC decision as the sole authority → canonical
  conversion), reuses the PR8c numeric grammar — moved to `core.values` so both pipelines
  share one implementation rather than forking a second set of edge cases — treats QC as
  *acquisition* quality only (never a biological verdict), and performs no unit conversion
  without a declared rule, recording the factor and the pre-conversion value so
  normalization is reversible. Runs are grouped by declared identifiers, sealed with their
  PR13a checksum and deduplicated on the PR13a identity. `virtualcell experiment import` is
  the CLI surface; ingestion writes nothing to a knowledge base. Acceptance is a benchmark
  case running raw CSV → QC → canonical → `run_to_passage_series` →
  `ImmortalizationAssessmentAgent.assess`, proving raw data drives the shipped path end to
  end. One consequence reached back into the vertical: a non-`valid` reading is now left
  *absent* from a passage series rather than read, because `PassageObservation` has no field
  for a quality flag and a flagged value would otherwise be indistinguishable from a clean
  one.
- ✅ **PR13b-2 — XLSX behind the same `DatasetSpec`.** The container changed, the meaning did
  not: a workbook and its CSV export produce the same `dedup_key`, and every reader funnels
  through one `build_table` so the header contract is stated once. The first non-pydantic
  parsing dependency lands as the optional `virtualcell[xlsx]` extra. Because a spreadsheet
  is typed, formula-bearing and multi-sheet, the reader **refuses** rather than inventing a
  value: an unnamed sheet in a multi-sheet workbook, a formula with no cached value (which
  would read blank and be recorded as *missing*), a merged cell (no single locator), and an
  Excel error value. Cells are read as stored rather than displayed. Excel stores no
  timezone, so `ColumnSpec.timestamp_offset` lets a human declare the zone rather than have
  a reader infer one — additive, hence spec `1.0 → 1.1`.
- ▶ **Assay-specific readers** (qPCR Ct, FCS, imaging, targeted genotyping, omics).
  Deliberately *not* in PR13: they need vendor/binary parsers and per-assay QC science, and
  should wait until a second domain pack has proven the QC boundary generalizes — which it
  now has. Still unbuilt, and still gated on a *candidate comparison* before any code: the
  first reader must connect to a real decision axis in one of the three shipped verticals.
  **The platform deliberately does not claim arbitrary raw-data interpretation.**
  *(Originally labelled "PR15+" here; PR15 was subsequently used for the adipogenesis
  expansion, so the label is dropped rather than left pointing at unrelated work.)*
- ✅ **PR14a — Reasoning kernel: grounding, assertion safety, tier conventions.** The first
  and largest slice of the kernel extraction, chosen because each piece was already
  duplicated or already domain-independent. Mechanistic grounding existed **twice** inside
  the vertical — once for mechanism questions, once for hypothesis questions, identical
  apart from the admission test — so ordering, deduplication and the missing-seed refusal
  had two places to drift and a second domain would have made a third. The PR10b assertion
  scope and the measurement/interpretation tier conventions were domain-independent facts
  living inside one vertical. All three now live in `reasoning.kernel`; packs supply only
  policy (which targets, which relations, which phrases). **Behaviour is unchanged** — same
  suite, same scorecard, same per-question scores. An AST test forbids any kernel import
  from `virtualcell.agents`, and the acceptance test grounds and validates a report for a
  domain that does not exist in this repository.
- ✅ **Minimal adipogenesis vertical.** Deliberately **before** PR14b, not after. Decision
  assembly currently has exactly one implementation, and extracting a single instance
  produces an abstraction shaped entirely by its only caller — which is how a "generic"
  kernel ends up encoding one domain's assumptions under a neutral name. A second
  assembly has to exist before anyone can see which parts are actually shared. Minimal on
  purpose: enough of a pack to build a real `DecisionReport`, not a full vertical, since
  its job at this point is to be a second data point. Landed with three findings for the
  comparison: the shared `DecisionReport.candidate_status` carries **immortalization's**
  status vocabulary, so a second domain's verdict has to travel on the envelope instead;
  dispatch was domain-neutral but the **store** was not (interfaces seeded one vertical by
  name, so a second domain routed correctly and then grounded nothing — now a composition
  decision); and the **kernel needed no changes at all**, which is the first real evidence
  the PR14a boundary sits in the right place.
- ✅ **Compare the two assemblies.** Read the immortalization and adipogenesis report
  builders side by side and record what is common (and what only looked common). The
  comparison must cover the *shape of the shared contract*, not only the builders, because
  the second vertical already showed `DecisionReport` carrying first-vertical residue.
  Candidates to examine as **residue** (present because immortalization needed them, not
  because a report needs them): `candidate_status` — whose vocabulary a second domain
  cannot use — plus `flags`, `trajectory`, `derived_input`, `input_conflicts` and
  `blocked_overrides`. Candidates to examine as a genuine **cross-domain core**:
  `conclusion`, `supporting_evidence`, `contradicting_evidence`, `mechanistic_chain`,
  `uncertainty`, `missing_axes`, `conflict_explanation`, `limitations`,
  `overinterpretation_risk`, `recommended_validation`, `next_experiment`. Nothing is
  extracted or re-typed at this step: the output is a recorded reading, and PR14b acts on
  it.
- ✅ **PR14b — Shared decision assembly.** The comparison decided the scope, and the answer
  was *small*: the two builders share almost no procedure, only a report shape. Extracted
  `missing_axes` and `ordered_unique` — the one subtraction and the one list mechanic both
  verticals were doing — and nothing else. Conflict explanation, uncertainty, limitations,
  risks and next-assay choice stayed in the packs, because each exists in one vertical only
  or gives a different answer for a different biology. `candidate_status`/`flags` were
  confirmed as residue but **not migrated**: adipogenesis routes around them at no cost via
  the already-neutral `DecisionSupport`, so the migration would be paid in churn against the
  benchmark scorer for a tidiness no caller wants. The trigger to do it is the third domain,
  not discomfort.
- ✅ **PR15 — Expand the adipogenesis pack.** Grown into a full second vertical on the
  extracted kernel: six axes, five statuses, seven flags, its own 34-node seed graph, and a
  ten-question reasoning scorecard run through the product path. **Kernel changes: zero** —
  the extraction held, and the acceptance criterion held with it (the kernel still knows no
  biology; the AST guard that forbids it importing `virtualcell.agents` never had to move).
  Three findings worth carrying forward. (1) The expansion's real work was not adding axes
  but keeping *"we did not look"* separate from *"we looked and it was not there"* — an
  unmeasured completion panel is a gap, a measured-negative one is a stage, and two early
  drafts collapsed that distinction before the tests caught it. (2) Time stayed a
  **modifier**, not a series: the induction day changes what absent completion markers mean
  and nothing else, so the trajectory quartet PR14b declined to migrate was not needed and
  was not forced. (3) The benchmark's soft axes earned their keep on the first run —
  `maturation_unverified` was being suppressed when ADIPOQ and PLIN1 were high, which implies
  marker positivity verifies maturity; the caveat is now unconditional on a positive call.
  See [`adipogenesis_vertical.md`](adipogenesis_vertical.md).
- ✅ **PR16 — Close the immortalization validation loop.** Inserted ahead of third-domain
  validation because driving the shipped product turned up a gap that no test had: the vertical
  told researchers to verify genomic stability and differentiation capacity, and could not read
  the answer back. Measure what it asked for, hand the result in, and the report was
  byte-identical to never having measured it. Genomic stability is now a typed axis, both axes
  follow one rule (`unknown` → a gap and the assay that closes it; answered → silence; adverse →
  a follow-up that asks the *next* question, never the same assay again), and neither may move
  `CandidateStatus` — a line can proliferate indefinitely *and* be genomically unstable.
  Closing the loop opened the opposite failure, so a clearance-claim guard closes that too:
  measured is not cleared. Kernel changes: zero. Four findings recorded rather than fixed,
  the load-bearing one being **measurement-consumption transparency** — nothing in a response
  distinguishes a measurement that was used from one that was ignored. See
  [`immortalization_validation_axes.md`](immortalization_validation_axes.md).
- ✅ **PR17 — Measurement-consumption transparency.** The PR16 follow-up, and a platform
  contract rather than an immortalization fix: `ReasoningResponse.measurement_consumption`
  reports, for every key the caller submitted, whether it reached the verdict
  (`used_for_status`), was consulted for flags/safety/next steps only (`used_for_guidance`),
  had nothing to consult it for (`not_applicable`), was not recognised at all (`unsupported`),
  or was distrusted by QC (`quality_excluded`) — with the reason, the purposes, and the
  provenance. The vocabulary lives in `core.consumption` and imports nothing from
  `virtualcell`; *which* measurement is in which state is declared per pack, and the two packs
  genuinely disagree (adipogenesis counts inhibition and viability as status axes;
  immortalization treats every flag-raising axis as guidance, per PR16). Strictly additive:
  no status, tier, citation, confidence or benchmark score moved. Two findings surfaced that a
  caller could not previously have discovered — `handle_hypothesis` reads *no* submitted
  value, and `species`/`cell_type` steer nothing. See
  [`measurement_consumption.md`](measurement_consumption.md).
- ✅ **PR18 — Third-domain validation + domain self-description.** Genome-edit validation
  lands as the third vertical, chosen for the *shape* of its decision rather than its subject:
  it judges a molecular claim about a construct, and it must know **how** a value was measured
  before it can say what the value means (a PCR band is not a genotype, in either direction).
  Neither existing vertical had any notion that evidence strength varies by instrument, which
  made it the sharpest available probe. **Kernel changes: zero**; one line in the composition
  root; benchmark 10/10, written before the implementation. Alongside it, `DomainPack.describe()`
  returns a `DomainDescription` — tasks, purposes, per-task required and read axes, and every
  axis with its vocabulary, value type, kind and unmeasured spelling. That declaration is now
  the **single source**: PR17's private `_STATUS_AXES` / `_GUIDANCE_AXES` are gone and each
  pack's consumption ledger is *derived* from `AxisKind`, so a pack cannot advertise one thing
  and report another. Three findings recorded rather than fixed — `candidate_status` is still
  immortalization's (the third domain routed around it rather than being blocked),
  `missing_information` is not round-trippable as an axis name, and adipogenesis does not
  enum-validate its markers. See [`genome_editing_vertical.md`](genome_editing_vertical.md)
  and [`third_domain_selection.md`](third_domain_selection.md).
- ✅ **PR19 — Round-trippable missing inputs.** Closes the second of PR18's three findings,
  and the last **blocking** MCP prerequisite. The loop an automated caller runs is short —
  read what is missing → measure it → send it back under the name you were given — and
  immortalization broke it: `missing_information` reported `SA-b-Gal` for an axis a caller
  must send as `SA_b_gal`, so an agent echoing the platform's own string was told its
  correct measurement was an unrecognised key. That is a contract failure, not a caller
  mistake. `AxisDescription` now separates three names that had been one — `name` (the
  public query key), `canonical_name` (the internal model field) and `display_label`
  (prose) — and `ReasoningResponse.missing_inputs` carries typed `MissingInput` entries
  with the canonical key, a stable `{domain}.axis.{canonical_axis}` id, and the
  `value_type` / `vocabulary` / bounds / `unmeasured_value` needed to build a valid value
  without a second round trip. Resolution is **exact lookup** against each pack's own
  declaration, never punctuation normalisation, because identity is the one thing that must
  not be guessed; a pack reporting a gap its description does not declare raises rather
  than shipping a keyless requirement. Scoped deliberately to **resubmittable axes only** —
  an early draft also listed validation goals and next experiments, which forced every
  consumer to filter the list before acting and gave advisory entries list-position ids
  that reordering would reassign. Strictly additive: `missing_information` keeps its exact
  values and order, and all four scorecards hold with identical per-question scores.
- ✅ **Dev harness (`CLAUDE.md`, `scripts/verify.py`).** Not a feature — the local gate that
  makes the rules above checkable in one command: full suite, benchmarks, every scorecard
  (discovered by glob, so a new vertical needs no registration), `ruff check`,
  `ruff format --check`, and a kernel-unchanged diff against `origin/main`. Uses a
  scratch `--basetemp` outside the repository, because a basetemp *inside* it once fed
  fixture files to `ruff check .` and produced phantom lint errors.
- ▶ **MCP server.** Designed, not built — [`mcp_server_design.md`](mcp_server_design.md).
  Three tools (`list_domains`, `describe_domain`, `reason`) over `src/virtualcell/mcp/`, using
  `platform` only and naming no vertical. The order was deliberate: an MCP tool schema built on
  an unvalidated abstraction breaks when the abstraction moves, and the abstraction is now
  validated. The load-bearing risk it must mitigate is that every safety boundary this platform
  has built lives *inside* the report as text, and nothing forces a summarising model to relay
  it.
### What comes next, in order

Nothing below is implemented. Each is an independent PR, and none starts before the
previous one is merged with main CI green.

1. **MCP server** — implement [`mcp_server_design.md`](mcp_server_design.md): three tools
   (`list_domains`, `describe_domain`, `reason`) under `src/virtualcell/mcp/`, using the
   `platform` public surface only, naming no vertical, behind an optional dependency extra
   so a default install gains no new requirement. Both blocking prerequisites are now
   closed (PR18 strict categorical validation, PR19 canonical round trip).
2. **Neutral decision status** — decide what to do about the residue PR14b recorded and
   PR18 confirmed: the shared `DecisionReport.candidate_status` owns *immortalization's*
   vocabulary, and the two newer verticals route around it via `DecisionSupport.status`.
   The third domain was the stated trigger and it has arrived. An investigation-first
   item: writing an ADR that explains why the current structure stays is an acceptable
   outcome if the migration costs more churn than it returns.
3. **Canonical `ExperimentRun` query integration** — connect the ingestion path to the
   reasoning path. Today raw data reaches `ExperimentRun` and a domain adapter, and the
   handoff into `ReasoningService` is manual. Until this lands, `quality_excluded` is not
   reachable from the query surface at all.
4. **First assay-specific reader** — compare candidates before writing one (see
   [Assay-specific readers](#platform-sequence-after-pr11) above); the winner must connect
   to a real decision axis in a shipped vertical.
5. **Explanation layer** — make `explanation_level` actually change the explanation, so a
   non-expert can learn the concepts, interpret raw data, and follow the basis of a
   research judgment. Until then the level is carried as provenance only. The deterministic
   report is generated first and the narrative is presentation-only: status, evidence tier,
   citations and confidence never move, and limitations and overinterpretation risks are
   never omitted.
6. **Evidence provenance** — per-edge `evidence_tier` and source provenance, so a single
   paper's `PROMOTES` is not treated as strongly as a textbook edge (see the deferral note
   below, which this supersedes when it starts).
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
