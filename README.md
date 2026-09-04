# Virtual Cell Reasoning Platform

> An AI-driven, modular, **explainable reasoning layer for cell biology** — it structures biological knowledge into a graph and lets agents answer questions with **evidence-graded, cited** explanations and hypotheses. It complements data-driven perturbation predictors rather than competing with them.

> **Scope:** VCRP is a **general biological experiment reasoning platform**. **Immortalization is its first validated reasoning vertical and reference implementation**, not the product's subject — since PR11 it is registered as a *domain pack* behind a domain-neutral query boundary (`POST /reasoning/query`, `virtualcell query`), and a new domain is added without touching the API or CLI. **Three domain packs ship today** — immortalization, adipogenesis and genome-edit validation — and adding the third changed **zero** lines of the reasoning kernel. Canonical Experiment Schema v1 (PR12), declared tabular ingestion/QC/normalization (PR13) and the generic reasoning kernel (PR14) sit underneath. The platform does **not** yet claim to interpret arbitrary raw assay files: ingestion is driven by a declared `DatasetSpec` over CSV/TSV/XLSX, and assay-specific readers (qPCR, FCS, imaging, omics) are not built.

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
- **Integrated query orchestrator** (PR9): `EvidenceQueryOrchestrator` answers from the curated knowledge base and, on a miss, reaches for literature (discovery → extraction → verification → canonical → weak ingestion), surfacing it as clearly **weak, pending-review** evidence. A separate layer over the QA and literature agents — never bolted onto `qa.py`; a `lit:` node is never treated as an established fact, and literature evidence surfacing alongside a curated answer is downgraded to `hypothesis`. It also formats the mechanism/hypothesis benchmark questions (Q5/Q6/Q9) into `DecisionReport`s from the KG-explain path, and resolves `lit:` markers onto curated ontology nodes (exact-name match only) so discovered evidence attaches to the known graph while staying weak.
- **Domain-neutral reasoning boundary** (PR11): `ReasoningService.query()` is the single entry point behind every surface — `POST /reasoning/query`, `GET /reasoning/domains`, `virtualcell query`. An unknown domain or unsupported task fails explicitly and never falls back to a vertical.
- **Canonical Experiment Schema v1** (PR12/PR13a): `schema_version` is mandatory; a newer *minor* is accepted and its unknown fields preserved, a different *major* is refused. Runs carry a `content_checksum` ("was this modified?") and a `dedup_key` ("do I already have this?") — deliberately two different hashes, and `dedup_key` refuses a newer minor rather than reporting "cannot decide" as "same".
- **Declared tabular ingestion, QC and normalization** (PR13b / PR13b-2): CSV/TSV and XLSX behind one versioned `DatasetSpec` — never column inference. `virtualcell experiment import`. QC judges *acquisition* quality only, never biology; a spreadsheet reader refuses rather than inventing a value (uncached formula, merged cell, Excel error, unnamed sheet in a multi-sheet workbook). Ingestion writes nothing to a knowledge base.
- **Generic reasoning kernel** (PR14a/PR14b): `virtualcell.reasoning.kernel` holds mechanistic grounding, assertion-safety scope, tier conventions, `missing_axes` and `ordered_unique`. Packs supply policy only. An AST test forbids the kernel importing `virtualcell.agents` — and it has needed **zero** changes across every vertical added since.
- **Three reasoning verticals**, all reachable through the same query boundary:
  - **immortalization** — candidate status from proliferation and senescence markers, passage-series trajectory, mechanism (TERT / TERT+CDK4) and a P53-independent-safe hypothesis policy; plus genomic-stability and differentiation-capacity axes that are *read back* when you measure them (PR16), and which may never move the candidate status.
  - **adipogenesis** (PR15) — six axes, five statuses, seven flags, its own 34-node seed graph. Its central rule is keeping *"we did not look"* apart from *"we looked and it was not there"*.
  - **genome-edit validation** (PR18) — four statuses, six flags, a 21-node seed graph. Its headline refusal: **a band is not a genotype** — the verdict turns on *how* a value was measured, not on the value.
- **Measurement-consumption transparency** (PR17): `ReasoningResponse.measurement_consumption` says, for every key you submitted, whether it reached the verdict (`used_for_status`), informed only flags/safety/next steps (`used_for_guidance`), had nothing to consult it for (`not_applicable`), was **not recognised at all** (`unsupported`), or was distrusted by QC (`quality_excluded`).
- **Domain self-description** (PR18): `DomainPack.describe()` returns tasks, per-task required/read axes, and each axis's canonical name, value type, vocabulary, kind, and the spelling for "no reading was taken". It is the single source — each pack's consumption ledger is *derived* from it, so a pack cannot advertise one thing and report another. Every categorical axis is strictly validated: `PPARG: "hgih"` is refused, not silently read as `unknown`.
- **Round-trippable missing inputs** (PR19): `ReasoningResponse.missing_inputs` carries the **canonical** key to resubmit (`SA_b_gal`) beside the human label (`SA-b-Gal`), with a stable id `{domain}.axis.{canonical_axis}`. Only gaps a caller can actually fill appear there — validation goals and next experiments keep their own fields, so the list needs no filtering before use.
- **MCP server**: three tools — `list_domains`, `describe_domain`, `reason` — over the same service the API and CLI use, so an LLM agent reaches the platform without a bespoke integration. `pip install "virtualcell[mcp]"`, then `python -m virtualcell.mcp`. The `reason` result is ordered so the status, the measurements it ignored, what is still missing, the limitations and the overinterpretation risks all come **before** the summary: a model that summarises the top of the payload cannot drop the caveats, because it reaches them first.
- FastAPI app exposing `/health`, knowledge, agent, and reasoning endpoints.
- `pytest` suite, `ruff`-clean (`ruff check` + `ruff format`) codebase, GitHub Actions CI, and a one-command local gate (`python scripts/verify.py`) that runs the suite, all four scorecards, lint and a kernel-unchanged check.

### Agent and domain-pack status

Two different registries, and they do not hold the same things:

| Registry | What it holds | Members |
|---|---|---|
| `virtualcell.core.registry` (`virtualcell agents`) | `BaseAgent` implementations | `immortalization_assessment`, `literature`, `literature_discovery`, `validation` — **functional**; `genome`, `transcription`, `protein_interaction`, `metabolism`, `signaling` — **interface stubs** |
| `DomainRegistry` (`virtualcell query`, `GET /reasoning/domains`) | `DomainPack` implementations | `immortalization`, `adipogenesis`, `genome_editing` — all **functional** |

The adipogenesis and genome-editing verticals are domain packs, **not** registry agents: they are reached through `virtualcell query` and `POST /reasoning/query`, and they do not appear in `virtualcell agents`. `virtualcell assess` remains immortalization-only.

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

# Domain-neutral query — the same service the API uses. The domain is named in
# the request file, so a new domain needs no CLI change.
virtualcell query --input query.json --format text
virtualcell query --input query.json                                  # JSON (default)

# Run the API, tests, lint, format check
uvicorn virtualcell.api.main:app --reload
pytest
ruff check .
ruff format --check .

# One-command local gate: suite + benchmarks + all four scorecards + lint + kernel diff
python scripts/verify.py
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

`query.json` names the domain and task, so the same command reaches any pack:

```json
{
  "domain": "genome_editing",
  "task": "assess_state",
  "experiment": {
    "species": "Bos taurus", "cell_type": "preadipocyte",
    "edit_detected": "present", "edit_assay": "pcr", "parental_control": "matched"
  }
}
```

```
status: insufficient_evidence
flags: weak_assay
summary: The locus was screened by a method that cannot read an allele, so neither the
         presence nor the absence of the intended edit is established; a band is not a genotype.
```

The response also tells you what it did with each key you sent, and what it still
needs — under the name you can send back. Submit `gamaH2AX` by mistake against
`immortalization` and the report says so rather than quietly ignoring it:

```
measurements:
  ! not recognised (ignored): gamaH2AX
  used for the status: PDL_trend, DT_trend, p16, p21
  not used here: species, cell_type

missing inputs:
  - gammaH2AX
  - SA-b-Gal (send as: SA_b_gal)
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
├── core/           # shared abstractions: BaseAgent, contracts, evidence, experiment,
│                   #   values, consumption vocabulary, config
├── knowledge/      # knowledge graph: store, schema, backends, data-source connectors,
│                   #   curated per-domain seed graphs
├── reasoning/      # graph-grounded Q&A and explain, DecisionReport, and
│   └── kernel/     #   the domain-independent reasoning kernel (knows no biology)
├── platform/       # the domain-neutral seam: contracts, DomainPack + DomainRegistry,
│   └── packs/      #   ReasoningService, self-description — and one pack per vertical
├── agents/         # per-vertical scientific rules (immortalization, adipogenesis,
│                   #   genome_editing) + BaseAgent registry agents and stubs
├── ingestion/      # declared tabular ingestion: DatasetSpec, QC, normalization
├── literature/     # discovery → extraction → verification → canonical → weak ingestion
├── orchestration/  # multi-agent orchestrator and the evidence query orchestrator
├── simulation/     # interface only: CellState / TimeStep / SimulationEngine protocol,
│                   #   no concrete engine (dynamic ML simulation is out of scope)
├── mcp/            # MCP adapter: three tools over the platform surface, no biology
├── api/            # FastAPI app
└── cli.py          # command-line entry point
```

Every surface funnels through one path — `API / CLI / MCP → ReasoningService.query()
→ DomainRegistry → DomainPack → agent` — which is why adding a domain touches
neither the API, the CLI, the MCP adapter, nor the kernel.

## Tech stack

Python 3.12 · uv · Ruff · Pydantic v2 · pytest.

Optional extras, installed only when used: `api` (FastAPI + uvicorn) · `llm`
(Anthropic Claude, with a deterministic offline fallback so nothing requires a
key) · `xlsx` (openpyxl) · `mcp` (the official MCP Python SDK) · `orchestration`
(LangGraph) · `graph` (Neo4j) · `vector` (Qdrant).

The Neo4j and Qdrant backends are **interface skeletons** — the classes and the
extras exist, the methods raise `NotImplementedError`; the working knowledge
store is in-memory with a JSON snapshot for persistence. PostgreSQL appears only
as a configuration setting and is not yet used by any code path, and the
repository ships no Dockerfile.

## Contributing

Contributions are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) and our [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## License

Licensed under the [Apache License 2.0](LICENSE).
