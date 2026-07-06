# Virtual Cell Platform

> An AI-driven, modular, explainable **digital cell** — a coordinated ecosystem of specialized agents, biological models, and simulation engines that aims to predict cellular behavior *before* wet-lab validation.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/OWNER/virtual-cell-platform/actions/workflows/ci.yml/badge.svg)](../../actions)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)

---

## Vision

The Virtual Cell is **not a single AI model**. It is a coordinated ecosystem of specialized agents, biological knowledge bases, and simulation engines that together form a biologically realistic, extensible **digital twin** of the cell.

The platform grows through a 12-stage roadmap, from a Cellular Knowledge Base to a full Digital Organism. See [`docs/roadmap.md`](docs/roadmap.md).

## Design principles

- **Modular** — every module is independently replaceable; no monoliths.
- **Agent-first** — features are modeled as cooperating agents, each with defined responsibilities, inputs, outputs, memory, reasoning, and confidence.
- **Scientifically rigorous** — knowledge is separated into three tiers (`established` / `hypothesis` / `speculative`) and never mixed. This is enforced in code via `EvidenceTier`.
- **Dynamic** — the cell is simulated over time, environment, and state — never treated as static.
- **Reproducible & testable** — type hints, Pydantic contracts, unit tests, managed configuration.

## What v0.1 does today

This is the foundational scaffold. It provides the full architecture with working core pieces:

- Importable `virtualcell` package with core abstractions (`BaseAgent`, `Evidence`, `KnowledgeStore`).
- A working **in-memory Cellular Knowledge Base** (Stage 1) — insert genes/proteins/pathways and query neighbors/search with zero external dependencies.
- FastAPI app exposing `/health` and knowledge endpoints.
- A reference stub agent that queries the knowledge base and returns an evidence-tagged `Claim`.
- `pytest` suite, `ruff`-clean codebase, GitHub Actions CI.
- `docker-compose` for the API plus Postgres, Neo4j, and Qdrant (graph/vector backends are interface-ready; connection optional in v0.1).

Specialized agents, the simulation engine, and PyTorch models are present as **interfaces/stubs** and will be filled in subsequent releases.

## Quickstart

```bash
# Install (uv recommended)
uv sync

# or with pip
pip install -e ".[dev]"

# Run the knowledge-base example
python examples/01_knowledge_base_quickstart.py

# Run the API
uvicorn virtualcell.api.main:app --reload

# Tests & lint
pytest
ruff check .
```

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full design, [`docs/agents.md`](docs/agents.md) for the agent catalog, and [`docs/evidence-policy.md`](docs/evidence-policy.md) for the scientific-evidence policy.

```
src/virtualcell/
├── core/           # shared abstractions: BaseAgent, contracts, evidence, config
├── agents/         # specialized agents (stubs in v0.1)
├── orchestration/  # LangGraph orchestrator
├── knowledge/      # Stage 1: Cellular Knowledge Base (working)
├── simulation/     # dynamic simulation engine (interface)
├── api/            # FastAPI app
└── cli.py          # command-line entry point
```

## Tech stack

Python 3.12 · uv · Ruff · Pydantic v2 · FastAPI · LangGraph · Neo4j · Qdrant · PostgreSQL · Docker · PyTorch · MCP.

## Contributing

Contributions are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) and our [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## License

Licensed under the [Apache License 2.0](LICENSE).
