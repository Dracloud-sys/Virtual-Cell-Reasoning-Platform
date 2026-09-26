# Review sheet — how a B/C pair is judged

**Written before any run.** Nothing in this file was chosen after seeing an output, and it
must not be edited once outputs exist. If an axis turns out to be the wrong axis, say so in
the write-up; changing the sheet to fit the answers is how a comparison stops measuring
anything.

## What the answers are being scored on

A **development** comparison of three things C adds over B: a system prompt, a required
output structure, and a post-hoc check. Nothing else. No literature is retrieved, no
knowledge graph is read, and no answer is checked against real papers — so this cannot say
whether either condition is factually right about the biology, only whether the design it
proposes would decide the question it was given.

Every observation in every case is **invented for development**. A `user_observation` is an
input in the shape a caller's observation would take; nobody ran the experiment. Do not score
either answer for agreeing or disagreeing with the numbers as though they were data.

**A citation either answer names may be fabricated**, and nothing here verifies otherwise.
One case contains no `retrieved_source` at all, which means no invented paper is in the
*input* — it says nothing about what a model may write in its own free text. Treat any paper
either answer names as unverified, and score naming one as support under
**over-interpretation**.

## What is not scored

**Not the JSON.** C is instructed to return a JSON object and B is instructed to answer
normally, so C will satisfy any structural check and B will fail one. Scoring that would be
scoring the instruction, not the reasoning, and C would "win" before a single biological
claim was read.

**Not the count of anything.** Not hypotheses, not experiments, not controls, not decision
branches, not citations. A design with two hypotheses that separates them beats one with
six that does not, and counting rewards padding.

**Not length.** Not vocabulary. Not how confident it sounds.

**Not a particular marker, assay, phrase or order of steps.** Experimental design has many
valid answers. The question is whether *this* design would decide *this* question — not
whether it matches the reviewer's own first idea.

## Preparation

1. Score C from `c_report.txt`, not from `c_report.json`. The JSON's field names announce
   the condition on every line.
2. Strip the provenance footer (the `produced by …` block) from C's text before reading.
3. Shuffle the order of the two answers per case, and record which is which in a file you
   do not open until every axis is scored.
4. Read the case's `request.json` first, so the evidence is in hand before either answer is.
5. Score one axis across both answers before moving to the next. Scoring one answer fully,
   then the other, imports the first one's framing into the second.

The reviewer is not the person who wrote the implementation, if that can be arranged. If it
cannot, record that it could not — a development evaluation scored by the implementer is
still worth running, and it is not a holdout result.

## The axes

Each is scored **−1 / 0 / +1** relative to the other answer for that case, with a sentence
of evidence quoted from the answer. "Both the same" is a legitimate and common score.

| # | axis | the question it asks | what a failure looks like |
|---|---|---|---|
| 1 | **goal connection** | Does the answer serve the `goal` the request actually states, or a more general version of the question? | The case asks for *the single next experiment before the formulation is frozen*; the answer lists five equally-weighted experiments and does not say which comes first or why |
| 2 | **alternative explanations** | Are the dull explanations present — assay artefact, operator or lot confound, wrong system, donor difference — or only the interesting mechanism? | Every hypothesis is a signalling mechanism; nothing considers that two runs differed in donor, lot and operator at once |
| 3 | **controls** | Would the proposed experiment survive contact with a reviewer? Are the comparisons, blinding and the thing held constant named? | "Compare coated and uncoated" with no statement of what else is held fixed, no blinding where scoring is subjective |
| 4 | **what a result would change** | For each proposed measurement, is it said what a positive, a negative and an ambiguous result would *decide*? | The experiment produces data and the answer stops there; no outcome is tied to a next action |
| 5 | **contradicting evidence** | Is the conflict engaged, or averaged into a sentence like "results were variable"? Is the *derived* inference (`inf-1`) recognised as inheriting the confounds of the run it came from? | `obs-2` is mentioned once and never affects the design; `inf-1` is repeated as if it were an observation |
| 6 | **over-interpretation** | Is anything asserted that the evidence does not carry — a mechanism stated as established, a number invented, a stiffness from lot A applied to lot B, a citation that was never supplied? | "The coating lowers stiffness, which suppresses conversion" stated flatly when lot B was never measured |
| 7 | **unnecessary refusal** | Does it decline to help where it could have? **A system that avoids errors by saying little scores badly, not well.** Refusing is only correct when the request genuinely cannot be served. | "More data is needed" with no design offered, when a design was affordable |
| 8 | **correction burden** | How much would the researcher have to fix, delete or look up before acting on this? Count concrete edits, not impressions. | Three timepoints that the stated constraints rule out; an assay the lab does not have |

## Recorded alongside, never merged into the score

These are facts about the run, not judgements of it:

* **Integrity findings** for C, from `manifest.json` — checkable defects such as a citation
  to an id nobody supplied. Real, automatic, and *not* a research-quality measure. B has no
  equivalent because prose has no ids to check, so this column cannot be compared across
  conditions and must not be added into a total.
* **Cost**: input and output tokens and measured `elapsed_seconds` from each `*_call.json`.
  A C advantage bought with more tokens is not an advantage of the structure. The runner
  matches the budgets; verify that it did.
* **Failures**: a condition that errored is reported as a failure of that condition, not
  quietly dropped.

## Reporting

Report **every** case that was run and both answers for each, including the ones where C
looks worse. Selecting the good C outputs would make this a demonstration, and a
demonstration of a thing that has never been evaluated is worse than no result.

Three development cases is enough to see whether the difference is worth pursuing. It is not
enough to conclude anything, and the write-up says so in its own first paragraph. These are
**development** cases, visible to the session that wrote the implementation — the ECM ones in
particular have been discussed at length. Holdout verification stays marked *not performed*.

If C loses to B, the next step is to find which stage cost it — the system prompt, the
required JSON shape, the labelling, the integrity check — and ablate that stage. It is not to
adjust this sheet.
