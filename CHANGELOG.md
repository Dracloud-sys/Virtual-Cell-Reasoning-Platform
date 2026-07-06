# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
