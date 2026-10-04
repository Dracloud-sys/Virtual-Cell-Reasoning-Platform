# Live-host calls (2026-10-04)

**Setup.**
- Host: Claude Code, calling the `virtualcell` MCP server it started from `.mcp.json`.
- Server process: `.venv-mcp/bin/python -m virtualcell.mcp --literature`, editable install of
  this repository's `src/` at `a1dfca9`.
- Started at 02:09 UTC, before any file in this change existed.
- Draft directory: `docs/research_sessions/eval1_persistence`.
- This build has no `prior_path` or `revision`, so the revision itself ran only on the product
  path (`run_revision.py`).

**Not stored.** The replies were not saved byte for byte. The host returns them into its own
context and not to a file, and re-typing ~25 KB of JSON by hand would make a copy nobody could
trust. The fields below are transcribed from them. Everything except `evidence_origins` is
reproduced by `run_revision.py`, which runs the same check in-process: the per-experiment pairs,
the finding count and the mechanism-link gaps. `evidence_origins` depends on which server
process issued the spans, so only this record has it.

## Call 1 — the original plan

`check_research_draft_file(path="records/condition_B_payload_2.json", sha256="dda23951ce8bc4c9fa40f61b7b98a34af71181377f3a5b18922a8538f2599bb0")`, view compact (default)

- `input_file.bytes` 132,454.
- `finding_count` 1: `understated_evidence_link` at `hypothesis:H7`. This was already in the
  recorded `condition_B_check_2.json`.
- `evidence_origins`: all 17 `host_supplied`. They were issued by an earlier server process.
- `plan_summary.prediction_count` 144.
- E1: 21 separated pairs; unseparated H2/H3, H4/H5, H4/H7, H4/H8, H5/H7, H5/H8, H7/H8;
  `readout_exclusions` 0.
- `mechanism_links`: ML1–ML12 `not_in_graph`; ML11 also `no_evidence`.

## Call 2 — the revised plan

`check_research_draft_file(path="evidence_gap_v1/draft_revised.json", sha256="663eaf84fc89f15e82936a42c9e8dcdce6bf3f73bcce679e529727ed66e9cabe")`, view compact

- `input_file.bytes` 163,923.
- `finding_count` 1: the same H7 finding, and nothing new.
- `evidence_origins`:
  - the 10 new spans are `server_retrieved` ("Issued by this server and unchanged since"):
    `lit-e60fafae0030`, `lit-0650a4586f10`, `lit-fcd84996ed09`, `lit-bc7c597aaca4`,
    `lit-a0b6b0ba4b51`, `lit-2f2b31039dc0`, `lit-8ad9688ecbdd`, `lit-436033cdfec3`,
    `lit-1ba98dbcd8f3`, `lit-758a014077fb`;
  - `prior-latent-vs-active` is `host_supplied`;
  - the 17 original spans are `host_supplied`.
- `plan_summary.prediction_count` 152.
- E1: the **same** 21 separated pairs and the same 7 unseparated pairs; `readout_exclusions` 10
  (see the README finding).
- `mechanism_links`: ML13–ML15 `not_in_graph`; ML11 still `no_evidence`.
- New evidence rows:
  - H4 `contradicts` (1 span, 1 study);
  - H4 `scope_limit`: 6 spans across 4 studies;
  - H1 `scope_limit`;
  - H1 `method`: 2 spans across 2 studies;
  - ML14 `supports` and `method`;
  - ML15 `supports`;
  - H5 `method`;
  - H5 `scope_limit`: 3 spans across 2 studies.
- `not_computed`: what_if not sent.
