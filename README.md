# Virtual Cell Reasoning Platform

> An AI-driven, modular, **explainable reasoning layer for cell biology** — it structures biological knowledge into a graph and lets agents answer questions with **evidence-graded, cited** explanations and hypotheses. It complements data-driven perturbation predictors rather than competing with them.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/Dracloud-sys/Virtual-Cell-Reasoning-Platform/actions/workflows/ci.yml/badge.svg)](../../actions)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)

---

## Vision

The platform is **not** a black-box cell simulator. It is an *interpretable, evidence-graded mechanistic reasoning layer*: it ingests curated biology into a knowledge graph, and AI agents reason over that graph to explain **why**, **through which pathways**, and **how confidently** — every statement tagged with an evidence tier and a citation back to its source.

Where a data-driven model (e.g. AlphaCell, STATE) predicts *what* changes under a perturbation, this platform explains and contextualizes it. Dynamic ML simulation is deliberately **out of scope** — such models are integrated as external services. See [`docs/roadmap.md`](docs/roadmap.md) for the strategic positioning and capability stack.

## Design principles

- **Modular** — every module is independently replaceable; no monoliths.
- **Agent-first** — features are modeled as cooperating agents, each with defined responsibilities, inputs, outputs, memory, reasoning, and confidence.
- **Scientifically rigorous** — knowledge is separated into three tiers (`established` / `hypothesis` / `speculative`) and never mixed, enforced in code via `EvidenceTier`.
- **Grounded & auditable** — answers are synthesized *only* from retrieved knowledge-graph facts, each carrying a citation; the model never invents biology.
- **Reproducible & testable** — type hints, Pydantic contracts, unit tests, managed configuration.

## What works today

- Importable `virtualcell` package with core abstractions (`BaseAgent`, `Evidence`, `KnowledgeStore`).
- A working **in-memory knowledge graph** — genes/proteins/pathways with neighbor/search queries, zero external dependencies.
- **Real data ingestion**: `Reactome` and `UniProt` connectors, with cross-source protein enrichment (`virtualcell ingest`).
- **Natural-language Q&A** grounded in the graph (`virtualcell qa`, `POST /reasoning/qa`): retrieves relevant subgraph → answers via **Anthropic Claude**, with a deterministic **offline fallback** so it runs with no API key.
- **Evidence-graded `explain`** primitive (`virtualcell explain`, `GET /reasoning/explain/{id}`): relation-aware, direction-preserving multi-hop reach with tier downgrade.
- **Deterministic immortalization assessment** (cell-engineering vertical): the `ImmortalizationAssessmentAgent` turns normalized experiment markers into a structured, evidence-graded `DecisionReport` — candidate status, both-sided evidence, mechanism reports (TERT / TERT+CDK4), and a P53-independent-safe hypothesis policy. Runnable in Python, via the API (`POST /agents/immortalization_assessment/run`), and the CLI (`virtualcell assess immortalization`).
- **Passage-aware time-series trajectory** (PR7): an optional `observations` array of raw per-passage measurements (DT hours, cumulative PDL, …) is turned by a deterministic engine into a trajectory — `stable_growth`, `progressive_slowdown`, `plateau`, `transient_recovery`, `recovery_after_plateau`, `re_arrest`, `conflicting_trajectory`. A sufficient series' derived trend overrides a hand-written snapshot label and any disagreement is reported as an `input_conflict`; the trajectory is shown alongside, never as, the candidate status (a series alone never confirms immortalization).
- **Canonical experiment schema** (PR8a): a source-neutral `ExperimentRun`/`Observation`/`Measurement` contract that simulation and experiment data converge to, with an immortalization adapter to/from `PassageObservation` (additive — no existing path migrated).
- **Automated literature discovery** (PR8b): `virtualcell literature discover` finds external papers via the Europe PMC public API, deduplicates them, and returns metadata + a transparent relevance breakdown as a typed bundle — **not** biological claims. Discovery never writes to the knowledge graph.
- **Source-grounded extraction** (PR8c): every measurement/claim candidate is anchored to an exact table cell or text span and must pass one integrity gate (targeting, exact-cell binding, value discipline, a fixed numeric grammar); candidates are source-grounded but **unverified** — reading a paper is not itself a fact.
- **Deterministic verification gate** (PR8d-1): opt-in (`verify: true`, requires `extract: true`) re-checks retained candidates against the current document and records one decision each — only an exact, quantitative **table** measurement is machine-verified; prose, claims, author interpretations, statistics and unparsed values are pending human review; source-integrity failures are rejected.
- **Canonical conversion** (PR8d-2): opt-in (`convert: true`, requires `verify: true`) turns each machine-verified measurement into a source-neutral `ExperimentRun` with full provenance (article ids, exact locator, source hash, verification decision, raw value + comparator/uncertainty). Only machine-verified measurements convert; prose/claims/interpretations/statistics never do.
- **Reviewed ingestion** (PR8e): opt-in (`ingest: true`, requires `convert: true` and a `knowledge_store` service) writes each canonical run into the knowledge graph as **weak, reviewable** evidence — `lit:`-namespaced `Marker`/`AssayResult` nodes tagged `pending_review`, linked by the weak `ASSOCIATED_WITH` relation (never a causal/established edge), with full provenance. Deterministic and idempotent; it is the only path that writes to the store.
- **Integrated query orchestrator** (PR9): `EvidenceQueryOrchestrator` answers from the curated knowledge base and, on a miss, reaches for literature (discovery → extraction → verification → canonical → weak ingestion), surfacing it as clearly **weak, pending-review** evidence. A separate layer over the QA and literature agents — never bolted onto `qa.py`; a `lit:` node is never treated as an established fact, and literature evidence surfacing alongside a curated answer is downgraded to `hypothesis`.
- FastAPI app exposing `/health`, knowledge, agent, and reasoning endpoints.
- `pytest` suite, `ruff`-clean (`ruff check` + `ruff format`) codebase, GitHub Actions CI.

The Literature and Immortalization Assessment agents are functional; other specialized domain agents remain interface stubs.

## Quickstart

```bash
# Install (uv recommended)
uv sync
# or with pip
pip install -e ".[dev]"

# Ask a grounded natural-language question (works offline with no key)
virtualcell qa "What is TP53 and what pathway is it involved in?"

# For LLM-synthesized answers, install the extra and set your key
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=...        # never commit this

# Ingest real data and persist a merged graph, then query it across sessions
virtualcell ingest reactome --path data/UniProt2Reactome.txt --save graph.json
virtualcell ingest uniprot  --path data/uniprot_human_reviewed.tsv --load graph.json --save graph.json
virtualcell ingest intact   --path data/intact.txt --min-score 0.5 --load graph.json --save graph.json
virtualcell explain gene:TERT --load graph.json
virtualcell qa "What does TERT do?" --load graph.json

# Deterministic immortalization assessment from a JSON input
virtualcell assess immortalization --input assessment.json            # human-readable
virtualcell assess immortalization --input assessment.json --format json

# Run the API, tests, lint, format check
uvicorn virtualcell.api.main:app --reload
pytest
ruff check .
ruff format --check .
```

`assessment.json` is a normalized marker payload, e.g.:

```json
{
  "intent": "immortalization_assessment",
  "species": "Bos taurus", "cell_type": "preadipocyte",
  "PDL_trend": "increasing", "DT_trend": "worsening",
  "p16": "high", "p21": "high", "gammaH2AX": "normal", "SA_b_gal": "normal"
}
```

Or supply a **raw passage series** (PR7) and let the platform derive the trend —
the report then carries a `trajectory` and, if a snapshot label disagrees, an
`input_conflict`:

```json
{
  "intent": "immortalization_assessment",
  "species": "Bos taurus", "cell_type": "preadipocyte",
  "observations": [
    {"passage": 25, "cumulative_PDL": 22.0, "DT_hours": 42},
    {"passage": 30, "cumulative_PDL": 25.5, "DT_hours": 80},
    {"passage": 35, "cumulative_PDL": 27.0, "DT_hours": 100}
  ]
}
```

### Notebooks / Kaggle

The package uses a `src/` layout, so install it rather than relying on the working
directory (this avoids `ModuleNotFoundError: No module named 'virtualcell'`):

```python
%pip install -e .           # from the repo root
# or, without installing:
import sys; sys.path.append("/kaggle/working/Virtual-Cell-Reasoning-Platform/src")
```

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full design, [`docs/agents.md`](docs/agents.md) for the agent catalog, and [`docs/evidence-policy.md`](docs/evidence-policy.md) for the evidence policy.

```
src/virtualcell/
├── core/           # shared abstractions: BaseAgent, contracts, evidence, config
├── knowledge/      # knowledge graph: store, schema, backends, data-source connectors
├── reasoning/      # natural-language Q&A grounded in the graph (LLM + offline backend)
├── agents/         # specialized agents (Literature works; others are stubs)
├── orchestration/  # multi-agent orchestrator
├── api/            # FastAPI app
└── cli.py          # command-line entry point
```

## Tech stack

Python 3.12 · uv · Ruff · Pydantic v2 · FastAPI · Anthropic Claude · Neo4j · Qdrant · PostgreSQL · Docker.

## Contributing

Contributions are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) and our [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## License

Licensed under the [Apache License 2.0](LICENSE).
