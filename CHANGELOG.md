# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- Repositioned as the **Virtual Cell Reasoning Platform** — an interpretable,
  evidence-graded mechanistic reasoning layer, not a black-box simulator. Dynamic
  ML simulation is out of scope (delegated to external models). Updated README,
  API/CLI titles, and package metadata/URLs accordingly.

### Added
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
