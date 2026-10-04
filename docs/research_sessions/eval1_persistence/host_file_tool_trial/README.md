# check_research_draft_file — real-host trial record

One trial of the file-input tool on a real host: check the stored draft by file, edit two
fields into a new file, check that file. Two tool calls were made; none was repeated for this
record.

## What ran

- Code: commit `c70a638aa176e335c74ac4080f0ded93c667a6bd` (HEAD at the time; `src/` clean
  against it). The MCP server was the repository's local stdio server
  (`python -m virtualcell.mcp --literature`, editable install importing from this checkout's
  `src/`), called by the Claude Code host as `check_research_draft_file`. The tool exists only
  from `c70a638`, so the server ran at least that code; its start time was not recorded.
- Draft directory: `docs/research_sessions/eval1_persistence`. The variable was present in
  both the shell and the running server process, with the same value; `.mcp.json` sets no
  env for the server, so it was inherited. No other environment variable is recorded here.
- Both calls passed `view: "compact"`.

## Files

| file | what it is |
|---|---|
| `check_1_arguments.json`, `check_1_response.json` | call 1 arguments and the server's response text, extracted verbatim from the session transcript |
| `check_2_arguments.json`, `check_2_response.json` | call 2, same |
| `draft_v2.json` | the revised draft that call 2 checked, byte-for-byte as checked |
| `revise.py.as_run.txt` | the script that wrote `draft_v2.json`, byte-for-byte as run. Stored as `.txt` only so the repository's `ruff check` / `ruff format --check` do not lint it (it fails SIM102 and formatting as written); its bytes were not changed |

The input draft is not copied. It is
`records/condition_B_payload_1.json` as of commit `d6d2b05977dfac5484a2fceaea934219e05125c8`.

| | bytes | SHA-256 |
|---|---|---|
| input `records/condition_B_payload_1.json` | 130,050 | `d44100e2d966a08fb7120b08dbdec4a95b2f4065bd810f9d131a8a7250c83d65` |
| revision `host_file_tool_trial/draft_v2.json` | 145,579 | `1a254386c29dfc66601af4fe24d71ff680f3af2bc3013daa9aaa2d716be364d7` |

Both hashes are also the ones the server echoed back in `input_file` of each response.
The input hash matches `records/SHA256SUMS`. Hashes of the files in this folder are in
`SHA256SUMS`.

## The edit: two fields only

- `experiments[].discriminates`: each `"Hx vs Hy"` string split into hypothesis ids, unique
  per experiment, first-appearance order.
- `hypotheses[].supporting_evidence_ids` for H2-H6 (the hypotheses call 1 flagged): the ids
  the draft's own `evidence_links` already link to that hypothesis with role `supports`.
  They equal the ids call 1 named. No id was added from anywhere else.
- **Not edited:** the three predictions with basis `assumption` and no stated assumption.
  Filling them only to clear the finding was ruled out.

How "nothing else changed" is checked: the script deletes those two fields from a copy of the
input and of the revision and asserts the remainders are equal (and that `assumptions` is
equal), and writes nothing if not. After the trial the script was rerun against a temporary
directory whose `records/` links to the real one; it produced a byte-identical
`draft_v2.json`. The input file was never written.

## Results, as read from the two responses

| | call 1 (input) | call 2 (revision) |
|---|---|---|
| `finding_count` | 83 | 0 |
| `unsupported_evidence_link` (input) | 5 | — |
| `unknown_hypothesis_id` (input) | 39 (plus 39 derived `discrimination_claimed_without_predictions`) | — |
| `assumption_without_stated_assumptions` (review) | 3 | 3 |
| `not_computed` entries | 6 | 0 |
| `scientific_validity_checked` | false | false |
| evidence origins `host_supplied` | 17 of 17 | 17 of 17 |

- The 44 input-kind findings are gone; the 3 review-kind gaps remain. `finding_count: 0`
  counts the flat findings only; the review group is still listed in `finding_groups`, and
  it does not mean the draft has been reviewed.
- `host_supplied` means this server did not issue those ids. It does not mean the evidence is
  false or unusable.
- `scientific_validity_checked: false` on both: plausibility, whether a source supports what
  it is cited for, and the adequacy of controls were not checked.
- Per-experiment `unseparated_pairs` are identical in both calls (the edit changed no
  predicted value). Plan-wide `pairs_never_separated` is empty in both: in the submitted
  prediction tables, every hypothesis pair has a differing predicted value on some readout of
  at least one experiment. That is a computation over what the host wrote, not a check that
  any experiment would discriminate in practice or that the hypotheses are biologically
  sound. An unseparated pair inside one experiment is not a pair no experiment separates.
- `what_if` (`impact`) is the reach of the submitted dependency on `lit-4003fcca2815`: 6
  predictions in E1 and E5, ML2 and ML3, hypotheses H4 and H1. Identical in both calls.
- Still for a person: the 3 assumption gaps, the 4 open conditions, 12 mechanism links not
  in the graph (ML11 also without evidence), and the impact items above.

## Time and usage: what was measured

- Server-side, from transcript timestamps: call 1 response 1.7 s after the call was sent,
  call 2 1.0 s. `internal_model_calls: 0` on both. Response text 27,204 and 21,058 bytes.
- About 57 s between the first and last shell commands of the trial (`date +%s`). That window
  is part of the run, not all of it: model time before the first and after the last command
  is outside it. It is not comparable with the 1,617 s figure in `../README.md`, which was
  measured differently, and no speed-up ratio is derived from the two.
- Tokens, cost and billing for this run were not measured. The host's context size at the end
  of the session is not tokens consumed by the run and is not recorded as such.
