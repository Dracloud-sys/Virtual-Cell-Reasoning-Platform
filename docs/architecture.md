# Architecture

The Virtual Cell Platform is a coordinated ecosystem of specialized agents,
biological knowledge bases, and simulation engines. It is deliberately **not** a
single model. This document describes the layers and how they fit together.

## What this platform is

VCRP is a **general biological experiment reasoning platform**. Its long-term job is to
accept experimental data, apply assay-aware QC and normalization, convert results into a
canonical experimental representation, combine those observations with biological and
literature evidence, support mechanistic reasoning and research decisions, and explain
that reasoning at different levels of expertise.

**Immortalization is the first validated reasoning vertical and the reference
implementation — not the product's subject.** It exists to prove the pipeline end to end
against a fixed benchmark; every other domain is meant to arrive the same way.

PR11 establishes the boundary that makes that claim structural rather than aspirational:
a domain-neutral query and dispatch layer through which immortalization is registered as
the *first domain pack*. See [Platform boundary](#platform-boundary-virtualcellplatform).

### What is not claimed yet

PR11 accepts a **normalised** experiment payload — the shape existing agents already
consume. It does **not** claim to interpret arbitrary raw assay files. Structured raw-data
ingestion (CSV/XLSX, qPCR Ct, FCS, imaging, omics), QC and normalization are PR13 work,
and non-expert knowledge-learning explanations are a later platform layer still. The
roadmap records the sequence.

## Layered view

```
                         ┌─────────────────────────┐
                         │         API / CLI        │  interaction surface
                         └────────────┬────────────┘
                                      │
                         ┌────────────▼────────────┐
                         │      Orchestration       │  LangGraph: routes work
                         │      (agent graph)       │  between agents
                         └────────────┬────────────┘
                                      │
        ┌───────────────┬────────────┼────────────┬───────────────┐
        │               │            │            │               │
   ┌────▼────┐    ┌─────▼────┐  ┌────▼────┐  ┌────▼─────┐   ┌──────▼─────┐
   │ Genome  │    │Transcrip.│  │Metabol. │  │Signaling │   │ Literature │  specialized
   │  Agent  │    │  Agent   │  │  Agent  │  │  Agent   │   │   Agent    │  agents ...
   └────┬────┘    └─────┬────┘  └────┬────┘  └────┬─────┘   └──────┬─────┘
        └───────────────┴───────┬────┴────────────┴────────────────┘
                                │
              ┌─────────────────▼──────────────────┐
              │           Core abstractions          │  BaseAgent, contracts,
              │  (agent / evidence / confidence)     │  EvidenceTier, registry
              └─────────────────┬──────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
  ┌─────▼──────┐        ┌───────▼───────┐        ┌──────▼───────┐
  │ Knowledge  │        │  Simulation   │        │   Data       │
  │   Base     │        │   Engine      │        │  Sources     │
  │ (graph +   │        │ (dynamic,     │        │ (GO, KEGG,   │
  │  vector)   │        │  time-based)  │        │  UniProt...) │
  └────────────┘        └───────────────┘        └──────────────┘
```

## Core abstractions (`virtualcell.core`)

Everything shared lives here so modules never import each other directly.

- **`BaseAgent`** — the contract every specialized agent implements: a `name`,
  `responsibilities`, an async `run(inputs) -> AgentOutput`, and
  `estimate_confidence`. Memory is injected, not hard-wired.
- **`contracts`** — Pydantic models for inter-agent messages: `AgentInput`,
  `AgentOutput`, `Message`.
- **`evidence`** — `EvidenceTier` and `Claim`. Any biological statement carries a
  tier so established knowledge, hypotheses, and speculation are never conflated.
- **`registry`** — register and look up agents by name for the orchestrator.
- **`config`** — `Settings` loaded from environment via pydantic-settings.

## Knowledge Base (`virtualcell.knowledge`) — Stage 1

The first roadmap stage and the only fully working subsystem in v0.1.

- **`schema`** — biological entities: `Gene`, `Protein`, `Pathway`, plus typed
  relationships (`Interaction`).
- **`store`** — a `KnowledgeStore` protocol: `upsert`, `get`, `neighbors`, `search`.
- **`backends`** — swappable implementations:
  - `memory` — pure-Python, zero external dependencies; the default and what the
    test suite exercises.
  - `neo4j` — graph backend for relationship-heavy queries.
  - `qdrant` — vector backend for semantic/literature search.
- **`sources`** — connectors that ingest external datasets (Gene Ontology,
  Reactome, UniProt, ...) behind a common `DataSource` protocol.

## Reasoning (`virtualcell.reasoning`)

- **`explain`** — evidence-graded multi-hop mechanistic reach: direction-preserving
  traversal with a tier that is `weaker_of(hop-distance, weakest-edge ceiling)`, so
  weak associative relations never read as established.
- **`decision`** — the `DecisionReport` output contract (conclusion, candidate
  status, both-sided `Claim`s, `mechanistic_chain`, risks, next experiments).
- **`qa`** — natural-language answers grounded in the graph (Claude or offline).
  `ground` (classify) and `synthesize` (render + call the backend) are separate, so
  evidence is tiered before any backend sees it.

## Generic reasoning kernel (`virtualcell.reasoning.kernel`)

The domain-independent machinery a vertical reasons *with*, lifted out of the vertical that
first needed it (PR14a). The dividing line is one question: **would a different biology
answer this differently?**

| in the kernel | in the pack |
|---|---|
| how to walk the graph, deduplicate, and order what it finds | *which* links a claim may rest on |
| where in a report a phrase counts as an assertion | *which* phrasings are forbidden |
| that an observation is established and a conclusion from it is a hypothesis | what was observed |

**`grounding`** - `ground_links(store, seeds, admits)`. Deterministic in three ways a
decision report depends on: seed order first, so every seed's arm surfaces rather than one
seed's shorter paths crowding out another's; then fewer hops, because a closer path is the
stronger explanation; then target id, so equally close links never swap between runs. The
same `(target, path)` reached twice is listed once - two seeds finding one path is one piece
of reasoning, and repeating it would read as corroboration it is not. An absent seed raises
rather than grounding nothing, because an empty chain would present as a graph that was
consulted and had nothing to say. Policy arrives as an `admits` predicate; `targets_in`,
`excludes_weak_relations` and `all_of` cover what the current verticals need. Weak-relation
step tokens are *derived* from `RelationType`, so a renamed relation cannot leave a policy
silently matching nothing.

**`safety`** - the PR10b scope rule, made shareable. A forbidden-phrase check scans the
conclusion and the evidence claims only. It must **not** scan `limitations` /
`overinterpretation_risk` / `uncertainty`, because those name the forbidden phrases in order
to prohibit them: "P53-independent does not mean P53 loss" is correct guidance, and a scanner
that flags it has punished the report for being careful. A pack supplies the phrase list and
may supply its own error type so a failure stays attributable to the domain.

**`claims`** - two constructors, and the most consequential thing in the package. A
*measurement* is established at 0.9 with its quality assumption attached; an
*interpretation* is a hypothesis at 0.7, lower because reading meaning into an observation
adds a step that can be wrong even when the observation is right. Left per-vertical those
conventions drift, and a drifting tier is a report that overclaims while every individual
file still looks reasonable.

Nothing under `kernel/` imports from `virtualcell.agents`, and an AST test enforces it - that
is what makes "domain-independent" checkable rather than an intention. The acceptance test
grounds and validates a report for a domain (adipogenesis) that does not exist in this
repository, using nothing but the kernel.

## Cell-engineering vertical (`virtualcell.agents.immortalization`)

The functional domain agent. It recomputes nothing — status/flags/tiers/citations
come from the deterministic layers below and are packaged onto `AgentOutput.result`:

```
ImmortalizationAssessmentAgent
├── deterministic assessment builder   (baseline_status + evidence assembly)
├── passage trajectory engine          (PR7: extract_trajectory + reconcile_markers)
├── mechanism-rule grounding           (Q5/Q6: curated claims + explain paths)
└── hypothesis safety policy           (Q9: P53-independent, no causal overreach)
```

The trajectory engine (`trajectory.py`, `effective_markers.py`) is a *pre-processing*
stage, not a new judge: a raw `observations` series is classified into one of eight
trajectory states under explicit `TrajectoryThresholds`, and its derived PDL/DT trend
replaces the snapshot marker the assessment builder consumes (any material
disagreement is surfaced as an `input_conflict`, never applied silently).
`baseline_status` is unchanged; the `DecisionReport` carries the trajectory as a
plain dict so `reasoning.decision` stays free of any dependency on the agent. A
time series alone never confirms a candidate — the baseline still requires a
measured senescence axis.

## Canonical experiment schema (`virtualcell.core.experiment`)

A **source-neutral data contract** that virtual-cell *simulation* output and
*experiment* data both converge to before any vertical reasoning. The pipeline the
platform is building toward is:

```
Canonical Experiment Schema   = source-neutral data contract  (core.experiment)
        │  (per-vertical adapter)
Immortalization adapter       = canonical data -> the first vertical's input
        │
Trajectory / reconciliation   = immortalization-specific deterministic reasoning
        │
DecisionReport                = reasoning output contract
        │
(optional) LLM narrative      = presentation only, never changes status/tier/citation
```

`core.experiment` is deliberately domain-agnostic (`OriginKind` ⟂ `AcquisitionMode`,
a discriminated `TimePoint`, scalar `Measurement` + `Provenance`, `Observation`,
`ExperimentRun`) and imports nothing from `agents`/`reasoning`. The immortalization
**adapter** (`agents/immortalization/adapters.py`,
`passage_observation_to_canonical` / `canonical_to_passage_observation` /
`passage_series_to_run` / `run_to_passage_series`) maps canonical runs to and from
`PassageObservation`; it only reshapes data and performs no trajectory extraction,
reconciliation, or status judgment.

### Canonical Experiment Schema v1 (PR12)

Every run declares the contract it was written against — `ExperimentRun.schema_version`,
serialized as the *leading* key so a reader can see what it is looking at before
interpreting anything else. This matters because the schema is the convergence point:
literature evidence, domain packs, and (from PR13) raw-assay ingestion all produce or
consume it, and a silent shape change would corrupt data that no single module owns.

**The version is mandatory.** It has no default: an unversioned payload arriving at a
storage or transmission boundary is refused rather than assumed to be v1 forever. Payloads
written before versioning existed load through one explicit path — `load_legacy_run` /
`migrate_legacy_payload` — which injects `LEGACY_SCHEMA_VERSION` for exactly that case and
refuses a payload that already declares a version, so migration can never paper over a
version that failed a compatibility check.

**Compatibility policy** (`MAJOR.MINOR`):

| change | version | reader behaviour |
|---|---|---|
| new optional fields | MINOR | **accepted**, including a newer minor than the reader's own |
| renamed / removed / re-typed fields | MAJOR | **refused** with `SchemaVersionError` |

Accepting a newer minor is deliberate: minors are additive, so every field the reader knows
is still present and correctly typed, and refusing structurally valid data would be the
more damaging failure. Refusing a different major is equally deliberate — silently reading
a v2 payload as v1 would corrupt the meaning of the data.

**Forward compatibility is preservation, not tolerance.** Accepting a newer minor is only
honest if the unknown fields survive it. Every canonical model sets `extra="allow"`, so a
v1.0 reader can validate a v1.1 payload, bundle it, serialize it and hand it on with the
v1.1 additions intact — instead of dropping them while still declaring
`schema_version="1.1"`. The run is the version-bearing unit, so the strictness check lives
there: at a version this reader *fully* implements there are no additive fields left to
carry, so an unknown key anywhere in the run is a typo and is refused (`metadata` is the
field for arbitrary keys). Unknown fields are preserved without complaint only when the run
declares a newer minor.

**Mixed-minor collections are legal.** A version belongs to a run, not to its container, so
a bundle may carry runs at different minors of the same major (older stored runs alongside
newly produced ones). Containers validate each run individually.

The policy is enforced where it matters rather than only declared:

* `literature.canonical` and `immortalization.adapters.passage_series_to_run` **emit** the
  version explicitly at the construction site;
* `immortalization.adapters.run_to_passage_series` **validates before reading** — it pulls
  passage numbers, PDL and doubling times out of a structure it did not build, where an
  incompatible major could yield a plausible-looking but wrong trajectory;
* `LiteratureEvidenceBundle` **refuses** an incompatible canonical run, because a bundle is
  the unit that gets stored, transmitted and re-read;
* `literature.ingestion` **skips and reports** an incompatible run rather than raising, so
  one unreadable run cannot abort ingestion of the rest.

### Identity, value typing and conditions

Three v1 decisions that are far cheaper to make before PR13 ingestion and a second domain
pack start minting runs:

* **Run identity is namespaced** — `run_id` is `<namespace>:<local_id>` (`make_run_id` /
  `parse_run_id`). The namespace names the minting system, so an ingestion run and a
  literature run cannot collide. Only the first separator delimits, so a DOI-keyed local id
  keeps its own colons.
* **Measurement values are typed** — `MeasurementValueType` distinguishes `numeric`,
  `categorical` and `boolean`. The type is inferred when a producer does not state it and
  *verified* when it does, so a numeric assay whose value arrived as `"24.0"` is refused at
  the boundary. Consumers read numbers through `Measurement.numeric_value()`, the single
  place a measurement becomes a float: a numeric-looking string is refused rather than
  parsed, and a boolean is refused rather than promoted to 1/0.
* **Conditions compose, observation-first** — run-level conditions are defaults for the
  whole run; observation-level keys override them per time point. There is one canonical
  resolver, `ExperimentRun.effective_conditions(observation)`, so two readers cannot
  silently disagree about what an experiment measured.

### Integrity and identity (schema 1.1, PR13a)

Two hashes, because *"was this modified?"* and *"do I already have this?"* are different
questions. One hash forced to answer both would either make a harmless re-import look like
tampering, or make two genuinely different runs look identical.

| | `content_checksum` | `dedup_key` |
|---|---|---|
| answers | integrity | identity |
| covers | everything the run says, including version, `run_id`, metadata, provenance timestamps and preserved unknown fields | only what the run *observed*, plus run-level `origin_kind` / `acquisition_mode` / `source_system` / `source_run_id` / `method` |
| newer minor | **works** — hashing bytes needs no understanding of the fields | **refused** (`DedupUnavailableError`) |

`ExperimentRun.checksum` is an optional, self-verifying seal: when present it must equal
`content_checksum`, so a stored run edited in place no longer validates. It is **excluded
from its own input** — including it would be unsatisfiable, since writing the seal changes
the run. Absent means "not sealed", never "verified".

`dedup_key` refuses a newer minor on purpose. The hash spans the field set this reader
knows; a newer minor may have added the very field that distinguishes two runs, and hashing
without it would collapse records that are not duplicates. Silently merging distinct
experimental data is the one outcome dedup must never produce, so an unknown minor means
*cannot decide*, never *same*. Being readable and being dedupable are therefore separate
questions, and `literature.ingestion` reports them separately.

**Collection semantics are stated, not inherited from the serializer:**

| collection | semantics | order | multiplicity |
|---|---|---|---|
| `observations` | ordered **sequence** — it *is* the trajectory | significant | significant |
| `measurements` within an observation | unordered **multiset** — replicates are real data, so two identical readings at one time point are not one reading | normalized away | **significant** |
| `quality_flags` | true **set** — a flag repeated twice says what it says once | normalized away | normalized away |
| `conditions` (both levels) | mapping | normalized away | n/a |

One deliberate non-normalization: *where* a condition is declared is part of identity. A
run-level condition asserts it held for the whole run; the same key on one observation
asserts something narrower.

**Numeric identity is normalized in `dedup_key`, never in `content_checksum`.** `1` and
`1.0` are the same measurement — `Measurement.numeric_value()` reads both as `1.0` — and
`0.0`/`-0.0` are the same quantity, so they must not split a dedup group when a CSV reader
emits `int` and the literature converter emits `float` for one reading. Integrity asks a
different question: `1` and `1.0` are different bytes, so the checksum keeps them apart.

**Only finite numbers.** NaN and ±Infinity are refused by every canonical numeric field
(`Measurement.value`, `confidence`, elapsed-time values, and every `conditions`/`metadata`
map), and refused again before hashing so a preserved newer-minor extra — unvalidated by
design — cannot slip one through. The pre-check runs on the *python-mode* dump, because
pydantic's JSON mode rewrites NaN to `null`: checking afterwards would let a NaN-bearing run
and a null-bearing run seal to the same checksum, certifying data the serializer had already
altered. `json.dumps(..., allow_nan=False)` is the final guard. A non-finite reading is a
missing or invalid one, and `quality` is the field that says so.

`deduplicate_runs` keeps the first run of each group in input order, names every collapse,
and emits a structured `DedupCollision` (both run ids, both checksums, the shared key)
whenever two collapsed runs do not serialize identically. Since `run_id` is in the checksum
but not the key, two *distinct records* asserting the same observations always surface as a
collision while a byte-identical re-import collapses quietly — one record seen twice is
housekeeping, two records making the same claim is a fact about the data. A run whose
version blocks a dedup decision is **kept**, never dropped: being unable to prove two runs
are duplicates is a reason to hold both.

Scope today: this is the *foundation contract, its version policy, and the first adapter*.
It does **not** yet connect a real simulator, robot, or LIMS, and the existing
immortalization input/API/CLI are unchanged. Raw-assay ingestion and QC land in PR13.

## Declared tabular ingestion (`virtualcell.ingestion`)

Turns a raw CSV/TSV/XLSX export into canonical experiment runs, so an experimentalist's file
can reach a grounded decision report without anyone hand-transcribing it into the platform's
own shapes. qPCR Ct, FCS, imaging and omics are PR15+.

```
file -> RawTable -> ParsedCell candidates -> QCDecision -> ExperimentRun
```

The three layers are the literature pipeline's, for the same reason: a proposal, a decision
and a conversion are different acts, and merging any two of them is how a parse failure
quietly becomes an observation. A `ParsedCell` carries **no** quality verdict; a `QCDecision`
is the only thing that may assign one.

**Declared, never inferred.** A `DatasetSpec` states which columns exist, what they mean,
what type they hold and what units they are in. An unmapped column is *reported*, never
guessed; a required column that is absent fails the run; a column deliberately not ingested
is declared `ignored`, because an ignored column is a decision and an unmapped one is an
oversight. Free-form column mapping stays out of scope: a guess about what a column means is
a guess about what an experiment measured.

**QC is acquisition quality, never biology.** Every rule asks whether a reading was taken,
whether the instrument could represent it, whether it is inside the declared limits, whether
it is one of the declared categories. None asks whether the *cells* are interesting. The
vocabulary is exactly `MeasurementQuality`; ingestion adds no verdict of its own. The moment
a QC rule encodes a biological judgement it stops being reusable and becomes a hidden domain
model.

| rule | when | quality |
|---|---|---|
| `MISSING_TOKEN` | a declared "no reading" token | `missing` |
| `UNPARSEABLE` | text held no readable value | `suspect`, **no value** |
| `TYPE_MISMATCH` | value is not the column's declared type | `suspect`, **no value** |
| `UNIT_MISMATCH` | the cell carries a different unit | `suspect`, **no value** |
| `BOUNDED` | the cell is a bound (`<0.05`) | `suspect`, value kept as a **limit** |
| `BELOW_DETECTION` / `ABOVE_DETECTION` | outside the declared limits | matching quality |
| `OUT_OF_RANGE` | outside the declared plausible range | `suspect`, value kept |
| `UNEXPECTED_CATEGORY` | not a declared category | `suspect`, value kept |
| `ACCEPTED` | none of the above | `valid` |

A reading that could not be read keeps **no** value — there is nothing to keep, and
inventing one is the failure this layer exists to prevent. A reading that *was* read keeps
its value even when flagged, because the human reviewing the flag needs to see what was
recorded.

**A bound is never a point estimate.** `<0.05` does not mean 0.05, and a trend, mean or
comparison computed from it would be wrong in a way nothing downstream could detect. The
limit is kept — it is real information — but the reading is marked `suspect` and carries a
`bound:` flag, and `Measurement.numeric_value()` **refuses** anything carrying that flag.
Putting the guard in the schema rather than in each consumer is the point: a consumer that
only remembered to check `quality` still cannot read a limit as a value.

**One numeric grammar, with a strict whole-cell boundary.** `core.values.parse_value_text`
(PR8c, moved to `core` in PR13b) is shared with the literature pipeline, so a CSV cell and a
table cell in a paper are read by the same conservative rules: `1,234` is refused rather than
guessed, and qualitative text never gains a number. Ingestion additionally passes
`strict=True`, which anchors the *same* token definitions to the whole field — a declared
numeric column claims the entire cell is the value, so `abc24xyz` and `24 (n=3)` are refused
rather than yielding `24`. A value that **overflows to infinity** (`1e999`) is refused too:
it is syntactically a number and semantically nothing the canonical schema can hold, so
parsing it would hand a constructor a value guaranteed to raise — turning one raw cell into
a traceback instead of a QC verdict. Deciding which part of a cell was the datum is the reader
interpreting. The lenient default remains for literature prose spans, where a number
legitimately sits inside surrounding text. Both modes are built from one set of token
regexes, so they cannot drift into disagreeing about what a number is.

**No conversion this layer was not told about.** A column reporting minutes declares
`source_unit`, `unit` and `unit_factor`; every converted value carries a `NormalizationStep`
*and* its pre-conversion number in provenance, so a wrong factor is a visible mistake rather
than silently corrupted data. Unit inference, dimensional analysis, and cross-run
statistical normalization (batch correction, quantile) are all out — the last needs a model
of the whole dataset, which is reasoning, not ingestion.

### Spreadsheets (PR13b-2)

XLSX sits behind the **same** `DatasetSpec`, the same header contract and the same QC — the
container changed, the meaning did not, and a workbook and its CSV export produce the same
`dedup_key`. Every reader funnels through one `build_table`, so the header rules are stated
once rather than re-implemented per format. It needs the optional `virtualcell[xlsx]` extra:
a spreadsheet parser is a dependency only some imports need, and exporting a sheet to CSV is
always an alternative.

A spreadsheet is not a delimited file with a different separator, so the reader **refuses**
four things rather than inventing a value for them:

| refused | why it would otherwise be silent |
|---|---|
| an unnamed sheet in a multi-sheet workbook | picking the first is a guess about which experiment the file is about, and the wrong guess still imports cleanly |
| a formula with no cached value | openpyxl does not evaluate formulas; the cell reads blank, which QC would record as *missing* — asserting no reading was taken when one exists and cannot be seen |
| a merged cell over the used range | a merged block has one value and several coordinates; a `CellLocator` names one row and one column |
| an Excel error value (`#REF!`, `#DIV/0!`) | the spreadsheet already knows the cell is wrong |

Cells are read as **stored**, not as displayed: a column formatted to two decimals has not
rounded anything, and `25.0` — how Excel stores the integer 25 — is rendered `25` so a
passage count does not look fractional to a reader that is right to refuse fractional
passages.

Excel stores **no timezone at all** — openpyxl refuses even to write one — so an Excel
timestamp is always naive and a timestamp axis would be permanently unusable. `ColumnSpec`
therefore accepts a declared `timestamp_offset`, applied only to a stamp that carries none of
its own: stated by a human, never inferred, like every other reading decision here. A stamp
that states its own zone stays authoritative, because it describes the reading while the spec
describes the file. The offset must actually *name* a zone — an empty one parses cleanly and
leaves the stamp naive, which reads as an answer to exactly the ambiguity it fails to
resolve — and the parser re-checks awareness after applying it, so a naive stamp can never
reach canonical construction.

**Source headers must be unique and non-empty**, checked at the reader after stripping so
`id` and `id ` are caught. Everything downstream identifies a column by its header —
`CellLocator` carries nothing else — so two columns sharing one cannot be told apart: one
identifier would silently overwrite the other and lose a row's identity, and two same-named
measurements would be indistinguishable from the declared replicates the canonical multiset
exists to preserve. Neither is a reader's decision to make, so an ambiguous header row is an
`unreadable_source`, not a per-row QC outcome.

**Canonical names are unique across every ingested column.** Not just measurements: two
columns resolving to one name collapse into a single entry wherever the pipeline keys by
name, and for *identifiers* that is data loss with teeth — rows differing only in the
shadowed column would group into one run, merging unrelated cultures while the import
reported success. Column lookup is by source **header**, the thing the spec guarantees
unique at the file level. `ignored` columns are exempt, since they contribute nothing.

**Grouping cannot silently merge.** Runs group by the declared identifier columns, and a
row whose *required* identifier is blank or unreadable is **rejected**, not defaulted:
grouping every such row under `""` would merge unrelated cultures into one run. The group is
encoded by percent-encoding each name and value before joining them, which is injective — no
combination of identifier values can produce the string another combination produces, so a
value containing `|` or `=` cannot collide with two separate identifiers. Runs are emitted at
the current `SCHEMA_VERSION`, identified as `ingestion:<dataset_id>:<group>`, **sealed** with
their PR13a checksum, and deduplicated with the PR13a semantic identity so one file cannot
import the same measurement twice under two row numbers. Identifier values keep their
original text in the run's conditions, so nothing about the data lives only in the handle.

**The status is authoritative, including when rows are rejected.** Rejected rows are
reported structurally (`RowRejection`: row index, typed reason, column, detail) and
contribute no QC decisions, since their cells never became measurements and counting them
would inflate the numbers a human reads. Three outcomes, three exit codes, because there are
three answers:

| status | meaning | exit |
|---|---|---|
| `success` | every row imported | 0 |
| `partial` | runs produced **and** rows rejected | 2 |
| `no_valid_rows` / `no_rows` / `spec_mismatch` / `unreadable_source` | nothing usable | 1 |

A partial import must not exit 0 (the rejects would go unseen) nor 1 (the runs it did
produce are real).

**A `DatasetSpec` declares its version, and it is mandatory.** Unlike a canonical run, a
spec is **executed** rather than relayed: every field is an instruction about how to read a
file. A reader meeting a newer *run* minor can carry fields it does not understand through
untouched, so accepting one loses nothing — but a newer *spec* minor may carry an
instruction this reader would silently not follow, and the import would look successful
while ignoring part of what the author asked for. A newer minor is therefore **refused**,
and an unversioned spec is refused rather than assumed current. Spec numbers must also be
coherent: finite, positive conversion factors, and no inverted detection or plausible
ranges.

**Ingestion writes nothing.** It returns runs and a QC report; whether any of it reaches a
KnowledgeStore is a separate, deliberate act — the same rule `literature.canonical` follows.
`virtualcell experiment import --spec <spec.json> --input <data.csv>` is the CLI surface, and
its typed status is authoritative: a caller never infers failure from counts.

One consequence reached back into the immortalization vertical: `canonical_to_passage_observation`
now leaves a non-`valid` reading **absent** instead of reading it. `PassageObservation` has no
field for a quality flag, so a suspect or below-detection value entering the trajectory engine
would be indistinguishable from a clean one and could silently drive a candidate status.

## Literature discovery (`virtualcell.literature`)

Automated literature evidence, with one rule above all: **finding/reading a paper is
not the same as that paper being verified evidence.** The layers are kept distinct so
a discovery result — or an LLM's reading — can never leak into the graph as fact:

```
LiteratureAgent (existing)      = retrieval over already-ingested KnowledgeStore entities
LiteratureDiscoveryAgent (new)  = external paper discovery -> metadata + evidence *candidates*
Verification layer              = deterministic gate: does a candidate match its source text?
Canonical ExperimentRun         = verified quantitative observations only
Knowledge graph                 = reviewed / approved biological claims only
```

PR8c adds **source-grounded extraction**, still strictly upstream of evidence.
`literature.documents` parses open-access JATS safely (DOCTYPE/ENTITY declarations
refused, bounded size/sections/tables/cells, typed `JatsParseError`, no-body treated as
a warning), keeping the parsed body in-process — only `DocumentMetadata` (identifier,
`content_hash`, counts, warnings) enters a bundle, never the full text.
`literature.extraction` extracts only what an `ExtractionTask` asks for and puts every
extractor — including the optional `StructuredLiteratureExtractor` (LLM) — behind the
same `accept_candidates(document, result, task)` gate. That is extraction *integrity*,
not verification: **all PR8c candidates are source-grounded but unverified** — finding
or reading a paper is never itself a biological fact. Canonical conversion (turning a
verified measurement into an `ExperimentRun`) remains PR8d-2.

Extraction policies (deterministic, and applied to every extractor):

- **Targeting.** A table cell becomes a measurement candidate only when an axis label
  matches a requested measurement; a candidate whose `measurement_name` is not a
  requested target, or does not match its cited cell's row/column label (with the
  `sample_group` on the opposite axis of the *same* cell), is rejected. "The paper has
  a number" is never sufficient.
- **Exact-cell anchoring.** `SourceLocator` carries `row_index`/`column_index`, and all
  of {coordinates, row/column label, source_text, and any parsed number} must hold on
  one and the same cell — a locator cannot be assembled from parts of different cells.
- **Statistical columns.** p-value / adjusted-p / q-value+FDR / CI / n / SD·SEM·error
  columns are recognised and never extracted as a biological measurement. A candidate
  that explicitly targets a statistic axis is kept but tagged `statistic` — it is *not*
  a biological measurement and is out of scope for PR8d canonical mapping.
- **Value discipline.** Values are split (`raw_value`/`parsed_value`/`comparator`/
  `uncertainty`/`unit`/`parse_status`): a bound (`<0.05`) keeps its comparator, an error
  (`2.4 ± 0.3`) is kept apart, qualitative text (`increased`/`NS`) stays UNPARSED, and
  `1,234` is left UNPARSED (ambiguous separator). No number is ever invented.
- **`target_contexts` is reserved** — it does not filter extraction in this version
  (supplying it emits a warning).
- **Source-kind anchoring.** Abstract locators check the abstract only; section locators
  must name a section and match its text; figure/supplementary locators are rejected as
  unsupported by the current parser.
- **Bounds.** `ExtractionTask.max_candidates` is a per-*document* cap and
  `max_total_candidates` a run-wide cap; the agent applies both in a fixed order
  (accept → de-duplicate by `candidate_id` → per-document cap → global cap), with an
  optional extractor's failure isolated to its own document.

**PR8d invariant.** A candidate tagged `statistic` is a statistic *about* a measurement,
not a measurement, and must never be converted to a canonical `ExperimentRun`.

PR8d-1 adds the **deterministic verification gate** (`literature.verification`), a
separate layer between extraction and canonical conversion. `verify_candidates(document,
result, task)` re-checks each candidate against the *current* document — reusing the same
PR8c `accept_candidates` boundary, so there is one rulebook — and emits exactly one
`VerificationDecision` per candidate (deterministic, input never mutated, `verified_at`
injectable and timezone-aware, the judged source span's hash recorded). It is
conservative: only an exact, re-verified, quantitative **table cell** measurement
(`parse_status == parsed`, a `parsed_value`, `statistic is None`) is `MACHINE_VERIFIED`.
Abstract/section **prose**, qualitative/unparsed values, statistic-tagged measurements,
every claim and every author interpretation are `PENDING_REVIEW` (their meaning is a
semantic judgement a machine must not make). Anything whose source integrity no longer
holds — drift, wrong coordinates or labels, a value or target mismatch, unsupported
numeric notation — is `REJECTED`, never softened to pending. A candidate still carries no
status of its own; `VerificationDecision` is the sole authority. Verification is an
explicit opt-in on the agent (`verify: true`, which requires `extract: true`): a run
verifies only the candidates it *retained* after the caps (no orphan decisions),
`canonical_runs` stays empty, and nothing is written to the KnowledgeStore.

PR8d-2 adds **canonical conversion** (`literature.canonical`), the step between a
verified measurement and evidence storage. `experiment_runs_from_verified(measurements,
decisions)` links each decision to its candidate by `candidate_id` and turns **only** a
`MACHINE_VERIFIED` measurement into a source-neutral `core.experiment.ExperimentRun` — a
`PENDING_REVIEW`/`REJECTED` decision, a claim, an author interpretation and a
`statistic`-tagged candidate are all skipped (defensively re-checked, so a statistic can
never become a run). The run carries full provenance (`origin_kind=experiment`,
`acquisition_mode=imported`, article ids, exact locator, source-text hash, the
verification decision, and the raw value with its comparator/uncertainty preserved as
measurement quality flags); units/comparators/uncertainty/target/conditions map onto the
canonical contract. Conversion is deterministic — the same verified measurement always
yields the same `run_id`, and duplicate inputs collapse to one run — and a run only ever
references a *retained* (post-cap) candidate. It is a further opt-in (`convert: true`,
which requires `verify: true`); only successful conversions land in `canonical_runs`, and
this module still writes nothing.

PR8e adds **reviewed ingestion** (`literature.ingestion`), the first and only path that
writes literature evidence into a `KnowledgeStore` — and it does so *cautiously*, because
a single machine-verified number is not a mechanism. `ingest_runs(store, runs)` writes,
per canonical run, a `lit:`-namespaced `Marker` (the measured target) and `AssayResult`
(the measurement, carrying the full canonical provenance verbatim), linked by the **weak,
symmetric** `ASSOCIATED_WITH` relation at a fixed conservative confidence. No
`PROMOTES`/`INHIBITS`/`REGULATES`/`INDICATES` or any causal/established edge is ever
created here, every node and edge is tagged `review_status = "pending_review"` so it is
never silently merged into curated truth and can always be re-reviewed, and ingestion is
deterministic and idempotent (re-ingesting the same run upserts the same nodes and does
not duplicate the edge). It is a final opt-in on the agent (`ingest: true`, which requires
`convert: true` **and** an injected `knowledge_store` service): every earlier stage
(discovery, extraction, verification, conversion) still leaves the store untouched.

PR9 adds the **integrated evidence-query orchestrator** (`orchestration.query`), one
entry point that unifies the two evidence sources while keeping their epistemic status
distinct. `EvidenceQueryOrchestrator.answer` first grounds the question in the curated KB
(the unchanged `QuestionAnswerer` path); on a **miss** it consults literature —
discovery → extraction → verification → canonical conversion → weak-evidence ingestion —
and surfaces what survives as clearly **weak, pending-review** facts, never synthesized
into a confident answer (so a possibility is never phrased as a conclusion). It is a
*separate* layer over the existing pieces, not a fallback bolted into `qa.py`, and it
enforces the tier boundary the store cannot: a `lit:` node is never an established KB hit,
a literature fact surfacing alongside a curated answer is downgraded to `HYPOTHESIS`, and
a repeat query re-surfaces previously ingested evidence (still weak) instead of
re-discovering it.

**Classification precedes synthesis (PR10a).** Because the curated graph and ingested
literature share one store, a retrieval can return both — so `qa.ground` assigns tiers
*before* `qa.synthesize` renders the evidence block for a backend. Evidence is capped
below `ESTABLISHED` and explicitly labelled at grounding time, so no backend — offline
template or LLM — can ever be handed unreviewed evidence dressed as curated truth, and the
natural-language answer carries exactly the tiers the structured facts report.

What counts as provisional is decided by **one shared predicate**,
`core.evidence.is_unreviewed`, which lives in domain-neutral `core` so no layer
re-implements it and `reasoning` needs no dependency on the literature pipeline. It treats
two *independent* signals as sufficient on their own:

1. an explicit `review_status = "pending_review"` property on a node, and
2. an entity id or citation in a namespace reserved for unreviewed evidence (`lit:`).

Either alone caps the fact, because neither reliably accompanies the other — a fixture,
migration, or hand-built graph can create a `lit:` node with no review property, while a
future non-`lit:` source may carry the property alone. Grounding passes every anchor a
fact rests on (the node, both endpoints of a mechanistic path, the composed citation), so
a path is only as strong as the weakest node beneath it. The predicate can only ever
weaken a tier, never strengthen one, and it protects every caller — the orchestrator,
`/reasoning/qa`, and the CLI alike. The orchestrator's split of curated from literature
facts uses the same predicate purely for *reporting*; it never re-tiers. Literature
evidence is *never hidden* to achieve any of this: it stays in the answer, visible and
labelled, just never established.

PR9-b/PR10b close the last benchmark gap, and close it **on the product path**. The
mechanism (Q5/Q6) and hypothesis (Q9) intents — which the assessment builder refuses —
are answered by the shipped policies `agents.immortalization.grounding` and
`agents.immortalization.hypotheses`, dispatched by `ImmortalizationAssessmentAgent`. Their
mechanistic chains come from the seed graph via `explain` (auditable, tier-graded, weak
edges capped at `hypothesis`, target allowlists and per-target relation signatures), and
the negative claims the graph cannot express — "TERT alone does not bypass a competent
p16/RB checkpoint" — live in the curated `limitations` catalog. Guardrails: TERT alone is
never sufficient, immortalization is never conflated with safety or function, and Q9's
spontaneous route stays a hypothesis stated as *P53-independent* — never a P53-negative
reduction, never `CAUSES`.

**The benchmark runs the product path (PR10b).** All ten questions are evaluated through
`ImmortalizationAssessmentAgent.assess`, the same entry point API and CLI callers use; the
harness never selects a builder by intent, so the 10/10 scorecard is evidence about the
shipped agent rather than a benchmark-only code path. An earlier duplicate Q5/Q6/Q9
implementation (`agents.immortalization.mechanism`) was removed rather than kept in
parallel — one canonical implementation per intent. Forbidden-phrase scoring reuses the
production notion of an *assertion* field (`hypotheses.assertion_texts`: conclusion plus
evidence claims), so required safety guidance such as "P53-independent does not mean P53
loss" is not mistaken for the violation it prohibits.

PR9-c adds **entity resolution** (`literature.resolution.resolve_literature_markers`): a
`lit:marker` is bridged onto the curated ontology node carrying the same
name/symbol/alias, by a weak, reviewable `ASSOCIATED_WITH` edge, so discovered evidence
becomes reachable from the known graph without being merged into it or upgraded past
`hypothesis`. Matching is conservative — an exact normalized name/symbol/alias only (no
fuzzy matching, no synonyms) — and an ambiguous match (several curated candidates) is left
unresolved rather than guessed; resolution is deterministic and idempotent. The
orchestrator runs it right after ingestion, and because `explain` caps a weak-edge path at
`hypothesis` and the orchestrator downgrades any `lit:`-citing fact, a later curated hit
that reaches the bridged literature evidence still surfaces it as weak.

PR8b implements the discovery slice: `literature.contracts` (query, article metadata,
source-anchored candidates with deterministic ids, transparent relevance, verification
status, and the `LiteratureEvidenceBundle`); a bounded, injectable `EuropePmcProvider` over
the official public API (no scraping, no paywall circumvention); and deterministic query
building, deduplication, and relevance scoring. Dedup merges on strong ids (PMCID/PMID/DOI)
and only falls back to title when it does not contradict a strong id — distinct papers are
never merged away. `QueryMode` (default `terms` = AND of word tokens for recall; `phrase`
for exact-phrase precision) is recorded in provenance. A machine-readable `DiscoveryRunStatus`
(`success`/`zero_results`/`provider_error`) distinguishes an empty result from a failure — the
CLI exits non-zero only on `provider_error` — and `VerificationDecision` is the authoritative
status a candidate is checked against. `LiteratureDiscoveryAgent` returns the typed bundle
in `AgentOutput.result` and **no biological `Claim`s** — discovery metadata is not
evidence, and `AgentOutput.confidence` is not the relevance score. By default nothing
here writes to the KnowledgeStore — only the explicit `ingest: true` opt-in does.
Source-grounded extraction (PR8c), the deterministic verification gate (PR8d-1), canonical
conversion of verified measurements (PR8d-2), reviewed weak-evidence ingestion (PR8e) and
the integrated KB→discovery→evidence query orchestrator (PR9) are now in place. A paper is
never treated as true merely because it was read.

## Platform boundary (`virtualcell.platform`)

PR11 introduces the domain-neutral seam every interface goes through:

```
                 API  (POST /reasoning/query)      CLI  (virtualcell query)
                                  │                        │
                                  └────────────┬───────────┘
                                               ▼
                                    ReasoningService.query()      one application service
                                               │
                                               ▼
                                        DomainRegistry            resolve domain + task
                                               │
                                               ▼
                                          DomainPack              per-vertical adapter
                                               │
                                               ▼
                              ImmortalizationAssessmentAgent      the real product path
```

* **`platform.contracts`** — `ReasoningQuery` (domain, task, optional question, normalised
  `experiment`, validated `explanation_level`, explicit `allow_literature`, typed
  `target_measurements`) and `ReasoningResponse`, a domain-neutral envelope carrying
  observations, quality findings, interpretations, evidence (as tiered `Claim`s with
  citations), mechanistic links, missing information, decision support, recommended
  validation and next experiments, limitations, overinterpretation risks, literature
  outcome, and provenance. Nothing is flattened to prose: the vertical's native report is
  preserved verbatim in `domain_details`, so normalisation can never lose meaning.
* **`platform.domains`** — the `DomainPack` protocol and `DomainRegistry`. The registry
  holds **no** scientific rules and never falls back to a default domain: an unregistered
  domain raises `UnknownDomainError`, a registered domain that cannot do the task raises
  `UnsupportedTaskError`. A test asserts the registry's executable code mentions no domain
  concept at all.
* **`platform.service`** — `ReasoningService`, the single application entry point used by
  both API and CLI. It owns domain resolution, task dispatch, literature orchestration and
  provider-outcome mapping, provenance assembly — and no biological rules.
* **`platform.packs.immortalization`** — the first domain pack. A thin adapter that calls
  `ImmortalizationAssessmentAgent.assess` (the same path PR10b aligned the benchmark to)
  and converts its `DecisionReport` into the envelope. It re-derives nothing: status,
  claims, tiers, citations, limitations and mechanistic links come from the agent
  unchanged, so PR10's claim boundaries and the Q5/Q6/Q9 corrections survive intact.
* **`platform.bootstrap`** — the single registration point.

### Literature is optional, and a failure is never evidence

The literature agent is composed in the **real** API and CLI paths (defaulting to the
Europe PMC provider), so `allow_literature=true` can actually retrieve; both surfaces keep
dependency injection for tests. `allow_literature=false` performs no external retrieval at
all — the CLI does not even construct a provider.

When it is true, the service reuses the existing evidence orchestrator (so PR9/PR10a
weak-ingestion and never-established semantics apply unchanged) and reports the outcome as
a distinguishable `LiteratureStatus`: `not_requested`, `unavailable` (requested but no
provider wired), `success`, `zero_results`, `provider_error`, `timeout`.

A **timeout is typed end to end** rather than collapsed into a generic failure:
`UrllibTransport` raises `ProviderTimeoutError` (a `ProviderError` subclass, so existing
handlers keep working) for both read timeouts and connect timeouts wrapped in
`URLError(reason=TimeoutError)`; `EuropePmcProvider` preserves the subclass through its
retry loop and defensively translates any raw error a third-party transport leaks; the
agent records `DiscoveryRunStatus.PROVIDER_TIMEOUT` on the bundle; and the service maps it
to `LiteratureStatus.TIMEOUT`. That distinction matters operationally — a timeout is
usually worth retrying, a hard error usually is not.

**Evidence is attached only on success** — enforced by a model validator on
`LiteratureOutcome`, not by convention, so a failed retrieval cannot be constructed with
evidence attached. It is kept separate from the domain's own evidence and retains its weak
pending-review tier and citations. "We could not look" is never reported as "we looked and
found nothing", including when the discovery agent absorbs a provider failure internally.

### Adding a domain pack

A second vertical requires **no API, CLI, contract, or service change** — only a pack and
one registration line:

```python
# virtualcell/platform/packs/adipogenesis.py
class AdipogenesisDomainPack:
    domain = "adipogenesis"
    supported_tasks = ("assess_state",)

    def execute(self, query, store):
        report = AdipogenesisAgent(store=store).assess(...)   # that vertical's own path
        return ReasoningResponse(...)                          # the shared envelope

# virtualcell/platform/bootstrap.py
def default_registry() -> DomainRegistry:
    registry = DomainRegistry()
    registry.register(ImmortalizationDomainPack())
    registry.register(AdipogenesisDomainPack())    # <- the only line added
    return registry
```

It is then immediately addressable as `{"domain": "adipogenesis", "task": "assess_state"}`
over both `POST /reasoning/query` and `virtualcell query`.

### Current limitation: `explanation_level`

The level is validated and carried end to end, but PR11 does **not** yet let it change the
scientific content of a response. Re-pitching an evidence-graded report for a non-expert
without softening claims needs a knowledge-learning layer that does not exist yet, so the
level is preserved as request provenance and no explanation is fabricated to fill the
schema. A test pins that novice and expert responses are scientifically identical today.

## Orchestration (`virtualcell.orchestration`)

A LangGraph graph that routes a request through the relevant agents and merges
their evidence-tagged outputs. In v0.1 this is a minimal single-hop router.

## Simulation (`virtualcell.simulation`)

Defines `CellState`, `TimeStep`, and the `SimulationEngine` interface. The cell is
modeled dynamically over time; concrete engines arrive in later releases.

## API & CLI (`virtualcell.api`, `virtualcell.cli`)

FastAPI exposes `/health`, knowledge, reasoning (`/reasoning/qa`,
`/reasoning/explain`), and agent (`/agents`, `/agents/{name}/run`) endpoints;
registered agents — including `immortalization_assessment` — are reachable
generically, and bad assessment input returns `422`. The CLI mirrors this with
`search`/`neighbors`/`qa`/`explain`/`ingest`/`seed` and
`assess immortalization --input <json>`.

## Extension model

Add capability by (1) implementing a new `BaseAgent`, (2) adding a backend behind
an existing protocol, or (3) adding a `DataSource`. Modules depend only on `core`
protocols, so any piece can be replaced without touching the rest.
