# Measurement consumption: what the reasoning did with what you submitted

A caller could submit a measurement and get back a response **byte-identical** to not having
submitted it. An unrecognised key was accepted, preserved on the input, and reached no
reasoning. A typed axis handed in as `unknown` looked exactly like one that drove the verdict.
Nothing in a response distinguished a measurement that was used from one that was ignored.

The failure mode is worse than a missing feature. A user who mistypes `gamaH2AX` gets a
confident report that silently ignored the marker they cared most about, and no signal that
anything went wrong. Recorded as finding 3 of PR16 and closed here.

## Where it lives, and why

`virtualcell.core.consumption` — not `virtualcell.platform`. Both the domain packs and the
canonical-experiment adapters need to speak this vocabulary, and an adapter under `agents`
importing from `platform` closes a dependency cycle (`platform.bootstrap` imports the packs,
which import those adapters). `core` is the layer everything already depends on and which
depends on nothing, so the vocabulary sits beside `core.evidence`.

The split follows the same rule as the reasoning kernel:

| | |
|---|---|
| **platform / core** | the *states* a submitted measurement can end up in — so a caller comparing two domains reads the same word to mean the same thing |
| **domain pack** | *which* measurement is in which state — only the vertical knows that viability refines one call and decides another |

`core/consumption.py` imports nothing from `virtualcell`, pinned by an AST test.

## The five states

| state | meaning |
|---|---|
| `used_for_status` | contributed to the domain's verdict |
| `used_for_guidance` | consulted, but not for the status — flags, evidence, safety caveats, recommended validation, next experiments |
| `not_applicable` | submitted and recognised, but this task or this reading had nothing to consult it for |
| `unsupported` | the domain does not recognise the name; **the state that used to be invisible** |
| `quality_excluded` | recognised, but QC did not mark it `valid`, so the reasoning could not trust it |

Per entry: `submitted_as`, `canonical_name`, `status`, `used_for`, `reason`, `provenance`, and
a computed `affected_status`. Plus two report-level summaries, `unsupported` and
`status_inputs` — the auditable answer to *"what was this call actually based on?"*.

### Field invariants, enforced on the model

A `model_validator` rejects any combination that contradicts the state it claims to be in.
Enforced on `MeasurementConsumption` rather than in `ConsumptionLedger`, because a contract
that holds only when the convenience builder is used is a convention: a deserialised HTTP
payload, a future pack, or a hand-built fixture must be equally unable to express a
self-contradicting entry. Same structural discipline as `LiteratureOutcome`, which refuses
evidence on a failed retrieval rather than asking callers to remember.

| state | `canonical_name` | `used_for` | `reason` |
|---|---|---|---|
| `used_for_status` | required | **non-empty** | must be absent |
| `used_for_guidance` | required | **non-empty** | must be absent |
| `not_applicable` | required | must be empty | **required** |
| `unsupported` | **must be `None`** | must be empty | **required** |
| `quality_excluded` | required | must be empty | **required** |

Two of these carry the weight:

- **`canonical_name is None` if and only if the status is `unsupported`.** A recognised name
  resolved to something even when nothing read it, so `not_applicable` and `quality_excluded`
  carry it too. Leaving it empty there would make *"we know this axis and had nothing to use
  it for"* indistinguishable from *"we have never heard of this"* — the one distinction the
  ledger exists to draw.
- **`reason` is forbidden on a consumed entry.** It answers "why was this *not* used"; beside
  a consumed value it would read as a caveat on a verdict that does not have one. A blank or
  whitespace-only reason is refused where one is required.

`affected_status is False` for guidance needs no validator — it is computed from `status`, so
the contradiction is not representable. `provenance` is deliberately **not** required: on the
canonical path it is always available and always set (`run_consumption` names the observation
index, pinned by a test), but forcing it on the general model would block a producer that has
none. Entries are frozen, so a legal entry cannot be mutated into an illegal one afterwards.

### Two rules that keep the ledger honest

**Only submitted measurements appear.** An axis nobody sent is not "unconsumed", it is absent,
and `missing_information` already reports it. Listing it here too would make a gap look like a
rejection.

**A flag is not a status.** `used_for_status` means the value reached the *verdict*. PR16
established that genomic stability and differentiation retention report beside the status and
never through it, so they are `used_for_guidance` however loudly they flag. Collapsing the two
would undo exactly the separation PR16 created.

## The two policies, and why they differ

The declarations are the evidence that this is a platform contract with domain content rather
than one vertical's feature wearing a generic name.

**Immortalization** — every flag-raising axis is guidance:

| | axes |
|---|---|
| status | `PDL_trend`, `DT_trend`, `gammaH2AX`, `SA_b_gal`, `p16`, `p21`, `observations` |
| guidance | `genomic_stability`, `adipogenic_retention`, `construct` (mechanism task) |
| not applicable | `species`, `cell_type`; everything, on `explain_mechanism` and `handle_hypothesis` |

**Adipogenesis** — the split lands somewhere else entirely:

| | axes |
|---|---|
| status | the five markers, `lipid_accumulation`, **`WNT_signalling`, `DLK1`, `viability`, `induction_day`** |
| guidance | `lipid_efficiency`, `morphology` |

An active inhibitor reaches `differentiation_inhibited` and a failing culture withholds the
negative call, so both genuinely gate the verdict. Only efficiency and morphology refine a call
they can never make. That difference is science, which is why the declaration is in the pack.

### Two findings a caller could not previously have discovered

- **`handle_hypothesis` reads no submitted value at all.** It answers from a fixed,
  citation-bound policy whose status and claims are identical for every input. Defensible, and
  it was completely undiscoverable.
- **`species` and `cell_type` steer nothing.** They are carried and preserved; no deterministic
  builder reads them.

## Surfaces

Identical `measurement_consumption` on the Python service, FastAPI and CLI `--format json`
(parity is tested). CLI `--format text` gets a compact block, unrecognised names first because
that is the line that usually means a mistake:

```
measurements:
  ! not recognised (ignored): telomere_length_kb, gamaH2AX
  used for the status: PDL_trend, DT_trend, gammaH2AX, p16, p21
  used for guidance only: genomic_stability, adipogenic_retention
  not used here: species, cell_type, SA_b_gal
```

## Compatibility

Strictly additive. `ReasoningResponse.measurement_consumption` is a defaulted field, so an
existing caller is unaffected and a pack that has not declared a policy reports nothing rather
than something wrong. No status, flag, evidence tier, citation, confidence or claim text
changed; both scorecards hold at 10/10 and 6/6 with identical per-question scores. The domain's
own `DecisionReport` is untouched — transparency is an envelope concern, which is precisely why
it could not move a benchmark.

## Known limitations

1. **`used_for_guidance` means "was read for these purposes", not "changed the output".**
   Proving the latter would mean re-running the domain's rules with the value removed, which
   the pack must not do — packs declare policy, they never re-derive science.
2. **`quality_excluded` is not reachable from a `ReasoningQuery` today.** QC verdicts live on
   canonical `Measurement`s, and the query contract accepts `PassageObservation`s, which carry
   no quality flag. The state is implemented and tested where the exclusion actually happens —
   `agents.immortalization.adapters.run_consumption`, the reporting companion to
   `run_to_passage_series` — and will reach the query path when canonical runs do.
3. **Free-text `measurements` are still accepted rather than rejected.** Whether an
   unrecognised key should be a 4xx instead of a reported `unsupported` entry is a separate
   ingestion-policy question; reporting it is the smaller, non-breaking half.
4. **No per-entry value echo.** The ledger names the measurement, not its value; the submitted
   value is already preserved verbatim in `domain_details`.
