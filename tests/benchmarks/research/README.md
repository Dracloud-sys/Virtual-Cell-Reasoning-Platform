# Development cases and scoring for the research path

> **These were written after P1, not before it.** The P1 instruction asked for development
> cases and a rubric at P0; they were not produced then, and the honest record is that the
> implementation came first. Saying otherwise would make this the only benchmark in the
> repository whose "benchmark-first" claim is retrospective, which is worse than admitting
> the gap. They are written now so P4 has something fixed to score against, and nothing here
> has been run.

## What these are for

P4 compares three conditions on the same questions:

| | condition |
|---|---|
| **A** | the same model, alone |
| **B** | the same model, given the same evidence, answering normally |
| **C** | the same model, same evidence, through the research path |

**B and C get matched inference and retrieval budgets.** A win for C bought with more calls
or more material is not a win for the structure, and the comparison is worthless without
that control.

## Development, not holdout

Every case here is a **development** case. They are visible to the implementing session, so
they can shape the code, and a number produced against them says how the thing behaves on
what it was built against — nothing more.

The ECM case in particular has been discussed at length in the session that wrote the
implementation. Calling it a holdout later would be false.

Holdout cases, their answers and their rubric must be prepared and scored **outside** the
implementing agent's context, search and session memory. Until that separation exists,
results are reported as development evaluation and holdout verification stays marked *not
performed*.

## The cases

Each is a `ResearchRequest` JSON in `cases/`, chosen to make a different failure visible.

| case | what it probes |
|---|---|
| `ecm_scaffold_single_cell.json` | the discussed ECM question: a rate-matching problem with an engineered material in the causal chain, constrained to one cell type for cost |
| `thin_evidence.json` | almost nothing supplied — does it draft under stated assumptions, or stall? |
| `contradicting_evidence.json` | two items that disagree — is the conflict engaged or averaged away? |
| `species_mismatch.json` | the only supporting span comes from a different species and cell type — is the over-extension named? |
| `unrelated_subject.json` | a question from a different field entirely — does the same path handle it without domain-specific scaffolding? |

`thin_evidence`, `contradicting_evidence` and `species_mismatch` are the ones that can fail
informatively. A case everything passes measures nothing.

> **`species_mismatch.json` carries a placeholder source and cannot be run as it stands.**
> Its `retrieved_source` names DOI `10.0000/placeholder-not-a-real-paper` and its span says
> so in its own text. Inventing a plausible-looking paper to fill the slot would put a
> fabricated citation into a file whose entire purpose is checking how citations are
> handled. Replace it with a real span, actually read, before the case is used — and until
> then the case is listed but not runnable.

## Scoring

Two layers, never merged.

**Code** (objective, automatic): every cited id exists; a claim marked `evidence_linked`
cites something grounded; each experiment names what it discriminates and what a result
would change; observations are not restated as predictions; the run stayed in budget; the
failure state is correct. These are `IntegrityFinding`s and the CLI exit code.

**A reader** (judgement, manual): the rest, scored blind to condition where possible.

| axis | asks |
|---|---|
| research usefulness | would a researcher act differently for having read this? |
| mechanistic plausibility | is the proposed mechanism biologically coherent for *this* system? |
| alternatives | are the dull explanations there — artefact, confound, wrong system? |
| discrimination | would the experiment actually separate the hypotheses, or merely produce data? |
| evidence handling | are observation, inference, prior and prediction kept distinct? |
| unwarranted certainty | is anything asserted that the evidence does not carry? |
| cost | calls, tokens, latency, and how much the user must fix afterwards |

**A system that avoids errors by saying little scores badly**, not well. Refusing to answer
is not accuracy.

Experimental design has many valid answers. Nothing is scored by requiring a particular
marker name, a phrase, or an order of steps — only by whether the design would decide the
question.

**The rubric is not adjusted to make C win.** If C loses to B, the next step is to isolate
which stage cost it and run the ablation that removes or simplifies that stage.

## Running a case

```bash
virtualcell research --input tests/benchmarks/research/cases/<case>.json --format json
```

Record alongside the output: commit, model id, `prompt_version` from the report's
provenance, the case file, token usage and any failure. The B condition uses the same
evidence rendered as a plain prompt; `virtualcell.research.service.build_prompt` produces
exactly what C sends, so B can be given the same material without hand-copying it.
