# check_research_draft resubmission trial — notes

Draft under test: `docs/research_sessions/eval1_persistence/records/condition_B_payload_1.json`
(TGF-beta1 pulse-and-washout myofibroblast persistence; 8 hypotheses H1-H8, 6 experiments
E1-E6, 17 evidence items, 30 evidence_links, 12 mechanism_links, `what_if` removing
lit-4003fcca2815). Two calls were made; no third.

## (a) view "compact" on both calls, and what the server returned

- Both calls passed `view: "compact"` explicitly.
- The server returned a **compact** response both times: `view:"compact"`, `findings:null`,
  with `finding_groups`, `not_computed`, `plan_summary` (holding `plan_summary.experiments`
  with separated/unseparated pairs, objective_levels, conditions, mechanism_links, evidence
  span counts, impact) and an `omitted` list. The flat `findings` list and the detailed
  `plan_analysis.prediction_traces` / `plan_analysis.experiments` were omitted as designed.
  `findings:null` here does NOT mean "no findings" — the findings live in `finding_groups`.

## (b) each change and which finding group prompted it

Two finding groups were kind **"input"** in call 1; both were fixed. The script
`revise.py` made the edits and asserted nothing else changed.

1. Group `unsupported_evidence_link` (kind input, field
   `hypotheses[].supporting_evidence_ids`, 5 occurrences: H2,H3,H4,H5,H6).
   H2-H6 declare `support=evidence_linked` but had empty `supporting_evidence_ids`, while
   `evidence_links` already names grounded role="supports" ids for each. Fix: populate
   `supporting_evidence_ids` with **exactly** the ids the draft's own evidence_links link to
   that hypothesis with role "supports" — no invented ids, no other role used:
   - H2: lit-13f07d427fef, lit-90bac4ae80b3, lit-91332fe8e2a5
   - H3: lit-8ccc91bd45f9, lit-d4c2a13f46ee
   - H4: lit-4003fcca2815, lit-13f07d427fef, lit-21c2cde4f3dc, lit-de72b3cfc53c, lit-31f9da012da1
   - H5: lit-b1bf272184af, lit-b0c020392ab5, lit-87a281f303a5, lit-086e187e2c2d
   - H6: lit-e62f54ed4087, lit-90bac4ae80b3
   (All are retrieved_source items, satisfying the schema requirement that an
   evidence_linked hypothesis list at least one user_observation or retrieved_source.)
   H1 and H7 also carry supports-role links (lit-04139c6d6982) but are
   `unverified_candidate`, so they were not flagged and were left untouched.

2. Group `unknown_hypothesis_id` (kind input, field `experiments[].discriminates`,
   39 occurrences across E1-E6; carried a derived `discrimination_claimed_without_predictions`,
   39). Every `discriminates` entry was a **pair string** like `"H1 vs H2"`; the schema wants
   one hypothesis id per entry. **This split is my edit as the host** (per instructions): each
   "Hx vs Hy" was split into Hx and Hy, unique ids kept in first-appearance order per
   experiment:
   - E1: ["H1","H2","H3","H4","H5","H6","H7","H8"]
   - E2: ["H2","H4","H5","H7","H8","H6"]
   - E3: ["H4","H7","H1","H2","H8"]
   - E4: ["H5","H4","H3","H1","H2","H8"]
   - E5: ["H4","H8","H1","H2","H3"]
   - E6: ["H6","H4","H5","H1","H2","H8","H7"]
   No hypothesis statements, predicted values, bases, evidence, evidence_links roles,
   mechanism links, designs, readouts, branches or what_if were changed. The script confirmed
   every other top-level field byte-identical and that only `supporting_evidence_ids` and
   `discriminates` moved.

## (c) what remains, and why it was left

- Group `assumption_without_stated_assumptions` (kind **review**, 3 occurrences:
  E2:H1:aSMA_in_naive_recipient, E3:H1:clonal_bimodality, E4:H1:GATA6_protein). These three
  H1 predictions have `basis:"assumption"` but no text in their `assumptions` array. Left
  unfixed: it is kind "review" (fix only kind "input"), and the only way to clear it would be
  to invent assumption text, which the rules forbid ("do not invent assumptions to make a
  review item go away"). It persists in call 2's `finding_groups` but is **not** counted in
  `finding_count` (which is 0) and no longer appears in `not_computed`.
- `not_computed`: 6 entries in call 1 (one per experiment: "N discriminates value(s) are not
  hypothesis ids…") were all caused by the pair-string `discriminates`. After fix 2,
  `not_computed` is **empty** in call 2.
- `scientific_validity_checked` is false in both calls (always). The `not_checked` list
  stands: plausibility, whether alternatives compete, whether an experiment truly separates,
  whether a source supports what it is cited for, control/timepoint adequacy — none of these
  are checked. A finding_count of 0 is a clean **structural** result only.
- `impact` (the what_if removing lit-4003fcca2815) is unchanged across both calls: it flags
  H4/H1 predictions in E1/E5 via ML2 (and ML2/ML3) as resting on the withdrawn evidence and
  needing re-examination; no predicted value is reversed. This was reported, not acted on
  (the task was not to change what_if).

## (d) evidence_origins

For all 17 evidence ids the server reported `origin:"host_supplied"` ("This server did not
issue this id. It is the caller's own material, which is legitimate — it is simply not
something the server retrieved."), with `authored_by:"host_llm"` and
`internal_model_calls:0`, in BOTH calls. This is expected: the ids were transcribed from a
stored draft and resubmitted to this server instance, which did not itself retrieve them
(consistent with a server that does not persist previously-issued ids across sessions, e.g.
after a restart). I am not representing any of this evidence as server-retrieved; it is
host-supplied and relayed as such.

## (e) understanding the responses without parsing code

The compact responses were read directly — no script was needed to locate or interpret the
findings. `finding_groups` grouped by `code`/`kind`/`field` with per-occurrence `where`
made both input problems and the exact fix obvious from the text. The only script written was
`revise.py`, which applies the revision (not to find the findings); the fix ids for group 1
were taken from the server's own `detail` text and cross-checked against the draft's
evidence_links role="supports" entries.

## (f) problems calling the tool

- **Payload size / client transcription.** The draft serialises to ~90 KB (experiments alone
  ~68 KB, 144 predictions). There is no file-reference mechanism for a tool argument, so the
  entire draft had to be inlined into the tool call as named parameters. This is the dominant
  usability cost of resubmitting a stored draft and the main friction in the exercise.
- **First attempt rejected (client-side), quoted exactly:**
  `InputValidationError: mcp__virtualcell__check_research_draft was called with input that
  could not be parsed as JSON.` ... `Common causes: unescaped backslashes in file paths (use
  / or \\), unescaped control characters, or truncated output. Retry with valid JSON.`
  Cause: a first try wrapped the whole payload in a single non-schema field rather than
  passing the schema's named top-level parameters. Resolved by passing each top-level key as
  its own named argument (question, objectives, …, experiments, evidence, what_if, view).
  The two real calls (call 1 and call 2) then both succeeded with no server error.
- No size limit, truncation, or server error was hit on the two successful calls.

## Result summary

- Call 1 (original draft): `finding_count = 83`.
  Groups: `unsupported_evidence_link` kind=input, count 5 (+0 derived);
  `unknown_hypothesis_id` kind=input, count 39 (+ derived
  `discrimination_claimed_without_predictions` 39); `assumption_without_stated_assumptions`
  kind=review, count 3. `not_computed`: 6 entries.
- Call 2 (draft_v2): `finding_count = 0`.
  Only remaining group: `assumption_without_stated_assumptions` kind=review, count 3 (not
  counted in finding_count). `not_computed`: empty.
- Not "all problems solved": 3 kind=review assumption items remain by design, and the
  structural-only caveat (`scientific_validity_checked:false`) stands.
