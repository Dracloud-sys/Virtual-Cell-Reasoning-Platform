# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
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
