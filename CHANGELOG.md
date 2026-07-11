# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **`DecisionReport` hardened + linked to `AgentOutput` (GPT review, pre-PR5).**
  `candidate_status` and `flags` are now enum-validated (`CandidateStatus` /
  `AssessmentFlag`, moved to `reasoning.decision` and reused by the deterministic
  baseline) so a typo can't slip through; added `missing_axes`,
  `conflict_explanation`, and `limitations` fields; relevance scores are bounded
  to `[0, 1]`. `AgentOutput` gained an optional `result: dict` so an agent can
  preserve a full structured `DecisionReport` (via `model_dump()`) instead of
  losing it to the `notes` string.

### Added
- **`ImmortalizationAssessmentAgent` + end-to-end benchmark (PR5c-3).** A single
  `input_from_scenario` adapter (`adapters.py`, maps the benchmark `construct` key to
  `construct_type`) and `ImmortalizationAssessmentAgent` (`agent.py`) that dispatches by
  intent to the deterministic builder (Q1-Q4/Q7/Q8/Q10), the Q5/Q6 mechanism grounding,
  or the Q9 hypothesis policy, and packages the `DecisionReport` onto `AgentOutput.result`
  (`model_dump(mode="json")`, conclusion in `notes`, claim-mean confidence). The agent
  recomputes nothing. All 10 benchmark questions now run end-to-end through
  `assess()`/`run()`, with status-source boundaries pinned and a forbidden-phrasing safety
  scan — **the deterministic immortalization prototype is complete** (LLM narrative is PR5d).
- **Q9 hypothesis policy (PR5c-2).** `agents/immortalization/hypotheses.py`
  (`build_hypothesis_report`) handles the PGC1A/TERT spontaneous-immortalization
  hypothesis: it separates the established TERT/PGC1A context from the weak reported
  route, keeps "P53-independent" exactly (never P53 loss/knockout/absence), never
  promotes `ASSOCIATED_WITH`/`SUGGESTS` to causation, keeps a required citation on the
  reported-route claim, and fixes `candidate_status` to `insufficient_evidence` by
  policy (not `baseline_status`). Grounding uses a per-target relation signature so the
  spontaneous route and the strong Q6 CDK4→G1/S path cannot cross-contaminate. A
  `validate_hypothesis_report` safety guard scans assertion fields for forbidden
  phrasing (excluding the curated safety-guidance fields that name those phrases to
  prohibit them).
- **Q5/Q6 mechanism graph grounding (PR5c-1).** `agents/immortalization/grounding.py`
  (`build_mechanism_report`) combines the catalog's curated claims with intent-scoped
  `explain` paths over the rule's `seed_entity_ids` into a mechanism `DecisionReport`
  (no candidate status). A target allowlist plus a weak-relation path filter keep the
  P53-independent spontaneous route (Q9's domain) from leaking into a Q5/Q6 chain via a
  shared target; a missing seed raises `GroundingError`. Catalog claim tiers/citations
  are preserved and paths are de-duplicated.
- **Q5/Q6 mechanism-rule catalog (PR5b).** A typed `ConstructType` on the input
  and `agents/immortalization/limitations.py`: curated, evidence-tiered supporting
  *and* limitation claims for the TERT-only and TERT+CDK4 constructs (the negative
  claims the graph cannot express, e.g. "TERT alone does not bypass p16/RB"; CDK4
  is a *functional* bypass, "does not directly inhibit p16"; safety caveats on
  genomic stability, differentiation, and non-tumorigenicity). `get_mechanism_rule`
  returns the rule with `seed_entity_ids` for PR5c to ground; mechanism rules carry
  no candidate status and only internal curated provenance. No graph/agent/LLM yet.
- **Deterministic immortalization assessment builder (PR5a).**
  `agents/immortalization/models.py` (enum-validated `ImmortalizationAssessmentInput`
  over the benchmark marker vocabulary; retention split into its own `RetentionValue`)
  and `rules.py` (`build_decision_report`). Status/flags come only from the
  deterministic `baseline_status`; the builder assembles both-sided evidence,
  missing axes, conflict explanation, overinterpretation risks, and the
  validation-axes vs next-experiments split, leaving relevance scores `None`.
  Mechanism/hypothesis intents raise `UnsupportedIntentError`. Benchmark
  Q1-Q4/Q7/Q8/Q10 are run through the builder as a regression.
- **`DecisionReport` output contract (PR4b).** `virtualcell.reasoning.decision`:
  the structured assessment output — conclusion, `candidate_status` + flags,
  supporting/contradicting `Claim`s, `mechanistic_chain` (reuses `explain`'s
  `MechanisticLink` via `DecisionReport.scaffold`), uncertainty,
  overinterpretation_risk, recommended_validation, next_experiment, and
  experimental relevance scores — shaped so every benchmark `required_output` is
  representable. Placed in `reasoning/` rather than `core/contracts` to keep
  `core` free of a `reasoning` dependency.
- **Immortalization seed graph — biologist-reviewed (PR3).** A curated
  `ImmortalizationSeedSource` (26 nodes / 28 edges) over the ontology, built with
  `virtualcell seed immortalization [--load ...] [--save ...]`. Added
  `PROMOTES`/`INHIBITS` mechanistic relations. Review fixes: CDK4→p16 documented as
  a functional bypass (not direct inhibition); differentiation edge redirected to
  `assay INDICATES loss_of_differentiation`; single-marker confidences lowered;
  telomere-length & TERT-activity added as next-tests; p16/p21 marker aliases; the
  spontaneous route softened to a "recovery route" and kept `ASSOCIATED_WITH`/
  `SUGGESTS`, explicitly **P53-independent** (never `CAUSES` / "P53 loss"). Surfaced
  a real gap for PR4: `explain`'s tier is hop-based only, so a 1-hop weak
  association is mislabelled `established`.
- **Cell-engineering ontology v0 (PR2).** Extended the schema with five vertical
  node types (`CellLine`, `Marker`, `AssayResult`, `Phenotype`, `Mechanism`) and
  relations (`HAS_RESULT`, `INDICATES`, `SUPPORTS`, `CONTRADICTS`,
  `ASSOCIATED_WITH`, `SUGGESTS`, `SUGGESTS_NEXT_TEST`). `ASSOCIATED_WITH` is
  symmetric; the rest are directed, so `explain` reasons causally over them.
  Persistence round-trips the new subclasses. The molecular substrate
  (gene/protein/pathway) is unchanged.
- **Cell-engineering vertical, benchmark-first (PR1).** Landed the immortalization
  assessment benchmark under `tests/benchmarks/` (`immortalization_v0.md` +
  machine-readable `immortalization_v0.yaml`: 10 questions, a 3-status vocabulary,
  and a scoring rubric) together with a deterministic rule-based
  `baseline_status` (`virtualcell.agents.immortalization.baseline`) and a CI
  regression that freezes the baseline↔spec self-check (8/8 status questions;
  mechanism questions Q5/Q6 excluded). This is the near-term wedge; the 12-stage
  roadmap stays the north star.

### Changed
- **`explain` tiers are now relation-aware (PR4a).** A path's tier is
  `weaker_of(hop-distance tier, weakest-edge ceiling)`: `ASSOCIATED_WITH`,
  `SUGGESTS`, and `SUGGESTS_NEXT_TEST` cap the tier at `hypothesis` no matter how
  few hops, while strong relations impose no ceiling. Relation type stays
  independent of tier. This fixes the gap the seed graph surfaced — a 1-hop weak
  association is no longer mislabelled `established` (e.g. the P53-independent
  spontaneous route now reads `hypothesis`), directly serving benchmark Q9.
- **Edge directionality is now preserved for reasoning.** The store records each
  edge's direction; `edges()`/`explain()` follow biological arrows by default
  (`direction="forward"`), so `explain` yields causal/downstream reach rather than
  mere graph reachability (e.g. TP53's forward reach no longer includes its
  upstream regulator MDM2). Symmetric relations (`INTERACTS_WITH`) traverse both
  ways; `neighbors()` stays undirected; pass `direction="any"` for reachability.
- Repositioned as the **Virtual Cell Reasoning Platform** — an interpretable,
  evidence-graded mechanistic reasoning layer, not a black-box simulator. Dynamic
  ML simulation is out of scope (delegated to external models). Updated README,
  API/CLI titles, and package metadata/URLs accordingly.

### Added
- **IntAct protein-protein interaction connector** (`IntActSource`,
  `virtualcell ingest intact`): parses an IntAct MITAB export into symmetric
  `INTERACTS_WITH` edges (UniProt accessions, isoforms collapsed, `--min-score`
  filter). It is edge-only and merges onto a protein-bearing graph; `load_into`
  now skips interactions whose endpoints are absent instead of raising. This adds
  the protein↔protein mechanistic wiring so `explain` finds real chains — e.g.
  TP53 now reaches MDM2 via `encodes` then a physical `interacts_with`.
- **JSON graph persistence** (`virtualcell.knowledge.persistence`): `save_store` /
  `load_store` snapshot an ingested graph to a portable JSON file and rebuild it
  losslessly (entity subclasses, directed edges). `virtualcell ingest --save`
  persists a graph, `ingest --load ... --save` merges sources into one file, and
  the query commands (`search`/`neighbors`/`ask`/`qa`/`explain`) take `--load` to
  work over it — so real ingested genes (TERT, CDK4, ...) survive across sessions
  instead of only the bundled sample. The API loads `VCELL_GRAPH_PATH` if set.
- **`explain` is now wired into natural-language Q&A.** Grounding traces directed,
  evidence-graded mechanistic paths from the retrieved entities (instead of shallow
  1-hop neighbours), so answers can cite multi-hop chains and honestly hedge them
  (a 2-hop inference is surfaced as `hypothesis`, not `established`).
- **Evidence-graded multi-hop reasoning primitive** (`virtualcell.reasoning.explain`,
  `virtualcell explain <id>`, `GET /reasoning/explain/{id}`): traverses the graph
  from a seed entity and ranks reachable entities by a path-decayed, multi-path
  corroborated confidence. Direct curated edges stay `established`; 2-hop
  inferences are downgraded to `hypothesis` and 3+-hop to `speculative`, so an
  inference is never presented as an established fact. Each result carries the
  path that justifies it. Backed by a new typed, weighted `Edge` on the store.
- **Natural-language reasoning layer** (`virtualcell.reasoning`): retrieves a
  relevant subgraph for a question and answers it, grounded strictly in cited,
  evidence-graded knowledge-base facts. Backed by **Anthropic Claude** (`llm`
  extra + `ANTHROPIC_API_KEY`) with a deterministic offline fallback so it runs
  with no key. Exposed via `virtualcell qa` and `POST /reasoning/qa`.
- Real **Reactome** data-source connector (`ReactomeSource`) that ingests the
  `UniProt2Reactome` export into the knowledge base as `Protein`/`Pathway`
  entities and `PARTICIPATES_IN` interactions, with species filtering and source
  provenance (roadmap Stage 1 → real data).
- Real **UniProt** data-source connector (`UniProtSource`) that ingests a
  UniProtKB TSV export as rich `Protein` and `Gene` entities plus `ENCODES`
  interactions, enriching skeletal proteins previously ingested from Reactome
  under the same `protein:<accession>` id.
- `virtualcell ingest {reactome,uniprot} --path <file>` CLI command.

## [0.1.0] - 2026-07-06

### Added
- Initial open-source scaffold for the Virtual Cell Platform.
- `core` abstractions: `BaseAgent`, data contracts, `EvidenceTier`/`Claim`,
  confidence utilities, agent registry, and configuration.
- Working in-memory **Cellular Knowledge Base** (roadmap Stage 1) with graph and
  vector backend interfaces (Neo4j, Qdrant).
- Specialized agent stubs: genome, transcription, protein interaction, metabolism,
  signaling, literature, validation.
- LangGraph orchestration skeleton.
- Simulation engine interface.
- FastAPI app with `/health` and knowledge endpoints; CLI entry point.
- pytest suite, Ruff configuration, GitHub Actions CI, Docker Compose.
