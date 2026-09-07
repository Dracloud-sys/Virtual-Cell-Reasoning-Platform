# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **VCRP-OPS-001 — safeguards for an unattended run.** `scripts/automation/` decides whether a
  scheduled run may start, and says precisely why when it may not: `NO_READY_WORK`,
  `AMBIGUOUS_QUEUE`, `INVALID_SPEC`, `BLOCKED_GITHUB_ACCESS`, `BLOCKED_ENVIRONMENT`,
  `BLOCKED_SCOPE`, `ALREADY_RUNNING`, `AWAITING_REVIEW`. The ten operational questions it must
  answer were written before it existed and live in `tests/automation/`; every one is driven by
  a fixture, because a queue used as a test fixture is a queue that can dispatch real work by
  accident.

  **The distinction the package exists for** is between "the queue was empty" and "the queue
  could not be read". Both leave the repository untouched, so a single status makes a broken
  token indistinguishable from a quiet night — which is how three consecutive runs looked
  correct while doing nothing at all. `QueueRead` makes the confusion impossible to write: a
  failed read carries no list to iterate.

  **The cross-container lock did not actually exclude.** Git objects are content-addressed, so
  two runs with the same work id, the same owner and the same one-second timestamp built the
  *same* commit; the second push found the ref already pointing at it, git reported "Everything
  up-to-date" and exited 0, and both runs believed they held the lock — `[True, True]`. Every
  lock commit now carries a `secrets` nonce, each run gets a unique owner, and an up-to-date
  push counts as contention. The uniqueness is the mutual exclusion; the CAS only enforces it.

  Concurrency is held by `O_CREAT | O_EXCL`, not by an instruction in a prompt — a prompt that
  says "stop if another run is going" is a request delivered to the only party that cannot
  check whether the other party received it. The lock is atomic within one container and blind
  across containers, which is where scheduled runs live; that gap is recorded in
  `docs/operations/routine_runbook.md` and gates re-enabling the schedule.

  The issue template no longer applies `claude-ready`. Queueing work was a side effect of
  opening a tab; it is now an act — a person adds the label when they approve the contract.

  **The five steps are one run, or they are nothing.** Each step passing on its own says
  nothing about whether they belong to the same run, and every step now has to present a chain:
  the *remote* lock ref must still equal the token's `lock_sha` (a token file proves what a run
  once took, not what holds the lock now); `postflight` and `finalize` refuse without a
  confirmation artifact bound to that same token, so `preflight → postflight` cannot skip the
  re-read; and `postflight` derives its path policy from a body whose hash matches the confirmed
  one, so widening *Allowed paths* in the request file after phase one yields `BLOCKED_SCOPE`
  rather than a wider diff.

  **A refused `confirm` gives the lock back.** A withdrawn label, a changed queue, a pull
  request that appeared — any of them used to leave the lock held and every later run reporting
  `ALREADY_RUNNING`. If the release itself fails, the report carries both the refusal and the
  release failure rather than one hiding the other.

  **The revision is recorded by `finalize`, after the push.** `finalize` checks that the SHA on
  the branch is the one `postflight` verified before writing the applied id to durable state.
  Recording at postflight time and then failing to push left "already applied" true while the
  fix existed nowhere but a container about to be reclaimed. The selected revision is also bound
  into the token — record id, pull request, head SHA and a hash of the instruction body — and
  `confirm` re-parses the raw approvals to check it is still there unchanged, so no later step
  can substitute a different one or drop it.

  **A request may not choose its approvers.** `approvers_file` is now a schema error rather than
  an override: the agent writes the request, so a list it can point at is a list it can write.

  **What landed is what the remote says landed.** `finalize` used to compare a `--pushed-sha`
  the caller supplied — in practice its own `git rev-parse HEAD`, which is equally true when
  the push failed, went to another branch, or never ran. It now asks `git ls-remote` what the
  bound branch carries and requires that to equal the commit verification passed on. A missing
  branch, a different commit, and the verified commit sitting on some other branch are each
  `BLOCKED_SCOPE`, and each keeps the token so the run can be retried.

  **The base is resolved once, on the remote, and frozen.** `postflight --base` let the step
  that judges the diff choose how much of the diff to look at: `HEAD~1` on a resumed branch
  measures the last commit and calls every earlier one unchanged. `preflight` now reads
  `base_branch` off the remote, stores the full 40-character SHA in the token alongside the
  branch and remote, and `postflight` measures `base…HEAD` from there. The flag survives only so
  that passing one that disagrees is an error rather than a silent narrowing, and `--branch` is
  gone from `finalize` entirely.

  **There is no default lock, and no default state store.** A request whose `lock` field was
  missing or misspelled used to fall back to an in-process store — which, for runs that get one
  container each, is not a weaker lock but no lock at all, reported as though it were real. Any
  kind but `git-ref` is now `INVALID_SPEC` unless `--development` is passed, and a run carrying
  an approved revision with no durable state store is refused at `preflight`, before the lock,
  rather than after the push.

  **A `finalize` whose release fails is not a finished run.** It used to delete the token and
  confirmation and exit 0 with `lock_released: no` in the evidence, which strands the lock and
  throws away what `release` needs to retry. It now exits non-zero, keeps both artifacts, and
  prints the manual `--force-with-lease` recovery line. Re-running it is safe: recording an
  already-recorded revision is a no-op.

  **The failure paths are driven against a real remote.** `tests/automation/test_full_cycle.py`
  builds a bare repository and a clone, and runs the whole chain through it: the success path
  pushes and finalizes, and "postflight passed but nothing was pushed" is a real unpushed branch
  rather than a test that declines to call `finalize`.

  **Which repository a run acts on is committed, not requested.** Reading the base off "the
  remote" proves nothing while the caller picks the remote, and `target.remote`,
  `target.base_branch`, `lock.remote` and `state.remote` all came out of the request file — so
  pointing phase one at another reachable repository bound that as production and every later
  check verified the wrong thing carefully. `docs/operations/run_target.json` now names the
  repository, remote, base branch, branch prefix, lock namespace and state ref; a request may
  repeat those values but a request that differs from them is a schema error; and `preflight`
  checks, before taking the lock, that `git remote get-url origin` in this checkout normalises
  to the configured repository. A request may never state `applied_revision_ids` at all.

  **A pushed branch is not the deliverable.** `finalize` said `work item complete` once the
  remote carried the verified commit, but the Routine's output is a **draft pull request
  targeting `main`**, and a branch with no pull request is work done where nobody was asked to
  look at it. `finalize` now takes `--completion`: a pull request listing queried after the
  push, which must show exactly one open pull request for the work item, `draft: true`, from the
  bound branch, at the verified commit, targeting the configured base — and on a revision run,
  the pull request the approved instruction was written on. Anything else refuses without
  recording or releasing anything, because on the revision path pushing to a second
  `claude/<work-id>-*` branch and recording the instruction as applied would retire it while the
  pull request its author is reading stayed exactly as it was.

  **A release that fails on the way out of `preflight` is reported.** It used to be dropped: the
  refusal was printed and the lock stayed on the remote with nothing saying so, which is how one
  bad run becomes every later run reporting `ALREADY_RUNNING`.

  **The lock is a state machine, because the environment refuses ref deletion.** Probing the
  real `origin` answered two questions the tests could not. Creating `refs/vcrp-locks/*` or
  `refs/vcrp-state/*` is refused outright — HTTP 403 on `git-receive-pack`, while creating and
  updating a branch succeeds — so the automation state moved to
  `refs/heads/vcrp-automation/{locks,state}`. And **deleting** a ref is refused the same way, so
  releasing a lock cannot mean deleting it: the ref is created once and then alternates between
  an `active` and a `tombstone` record, carrying schema, work id, state, owner, nonce, monotonic
  generation, timestamps, the previous lock SHA and a per-release nonce as JSON that is parsed
  rather than grepped. Acquiring from a tombstone is a compare-and-swap on that tombstone's SHA,
  so six contenders reading the same one still produce exactly one winner; a token from an
  earlier generation cannot retire a later holder's lock; and a record that does not parse
  raises `LockCorrupt` rather than reading as a free lock.

  **A push's exit code is not evidence.** The refused delete printed `Everything up-to-date` and
  exited **0** with the ref untouched, which the old `release()` would have reported as success —
  a lock released in the report and held on the remote. Every write now re-reads the remote and
  counts only when `ls-remote` shows the commit this process built; a release additionally
  re-reads the object and requires it to parse as a tombstone, and `record()` requires the
  identifier to actually appear in the remote's `applied.json`. A push that reports success
  without landing raises rather than returning quietly. That exact 403-shaped liar — 403 in
  stderr, "Everything up-to-date" on stdout, exit 0 — is reproduced as a regression test.

  Recovery in `docs/operations/routine_runbook.md` is the same transition, done by hand from the
  exact active SHA under a lease. There is no delete step anywhere, and no procedure for
  overwriting a lock with an arbitrary SHA.

  **An entry point that runs where the Routine starts.** `python scripts/automation/cli.py
  preflight ...` works from the repository root with nothing set up. The command documented in
  the previous round needed `scripts/` on `PYTHONPATH` and failed exactly where it is used
  (`No module named automation`); its integration test passed by running with `cwd=scripts`,
  arranging the one condition the real caller cannot provide.

  **Permission is granted by a second process, against a second read.** `preflight` takes the
  lock and stops; the agent re-queries GitHub; `confirm` submits that re-read with the lock
  token and is the only command that writes the proceed marker. It refuses evidence captured
  before the lock was taken, and refuses to proceed when the issue body or the open pull
  requests have moved since. The previous round parsed both "before" and "after" out of one
  file written before the lock existed, which is two snapshots wearing a costume.

  **`postflight` is where scope enforcement actually happens.** `PathPolicy` had tests and no
  caller, so `BLOCKED_SCOPE` was unreachable from the CLI: a run that started legally could
  finish by pushing anything. It now judges the real diff — `git diff --name-status -M
  base...HEAD`, renames checked at both ends — against the issue's own path rules and its
  kernel authorisation, runs `scripts/verify.py` in full, and releases the lock on failure so a
  bad night does not block the next one.

  **The lock is released by whoever holds the token, not by whoever is still running.** It used
  to live in a process attribute, so the first successful run would have stranded its own lock
  and every later run would have reported `ALREADY_RUNNING` forever.

  **Approvals are derived from GitHub's records.** The record id, author login, body, pull
  request and full commit id all come from the raw review payload; an `approved_by` the agent
  writes beside them is ignored, because the agent writes the request. Approvers come from a
  committed `docs/operations/run_approvers.json`, and an empty list approves nobody rather than
  everybody.

  **A response that is not a listing is not an empty listing.** `{"message": "Bad credentials",
  "status": "401"}` carries no `issues` collection, and used to read as a healthy empty queue.
  So do GraphQL `errors` envelopes, a missing `state`, unreadable `labels`, and a `number` that
  is not an integer — each fails the read against fixtures captured from the real tool.

  Exit codes are the contract: 0 means the step succeeded and the next may begin, and every
  refusal has its own code so a shell branches on a number rather than on prose.

  **A lock that reaches across containers.** `GitRefLockStore` pushes an orphan commit to
  `refs/vcrp-locks/<work-id>`; a push that would not fast-forward is rejected by the server, so
  exactly one creation wins and the *remote* decides. Six threads released from one barrier
  against one bare repository assert that, and a same-owner same-second pair pins the collision
  above. Rejected is not failed — an unreachable remote raises rather than reporting a free
  lock. The durable state store is fail-closed the same way: a ref that does not exist yet is an
  empty set, but a ref that cannot be *reached* blocks the run, because reading "nothing has
  been applied" out of a failed fetch is how an approved revision gets applied twice.

  **Identity and approval are verified, not assumed.** The work id the issue declares is
  authoritative and a mismatch stops the run; two open pull requests for one work id is a
  refusal rather than a coin toss; a revision instruction needs an approval record id, an
  approver on the committed list, and the full 40-character head SHA it was written against.

  **Contract and path checks that catch the near-misses.** `TODO`, `TBD`, `<reason>` are refused
  as loudly as an empty section — they are evidence somebody opened it and did not finish.
  Authorising a kernel change requires naming the files and the reason; declaring a biological
  change requires stating it and its grounding. The kernel stays forbidden even when a wide
  allow rule and a forgetful forbidden list would let it through, paths must be
  repository-relative (`../` and absolute paths are refused before they are matched), and a
  rename is judged on both ends — moving a file out of the kernel is a kernel change.

### Changed
- **`scripts/verify.py` stops overstating itself.** `--fast` and `--no-kernel-diff` used to
  drop checks and still print "All 9 checks passed"; skipped checks now appear as `SKIP` rows,
  the summary names them, and **the process exits 2** — a caller that only tests for zero can no
  longer record a partial gate as a full pass. `--unchanged PATH` generalises the kernel
  assertion to any path, so a work item that must not touch product code can prove it.

  Two comparisons it now refuses to make dishonestly. A base that resolves to *this* commit is
  a failure, not a pass: `origin/main...HEAD` on `main` is empty for the least interesting
  reason there is, and CI passes an explicit base per event instead. And a **dirty working tree
  fails every diff check**, because `git diff base...HEAD` reads commits — run it with edits
  still uncommitted and it answers honestly about the previous commit while the caller believes
  it answered about their change. That produced a false green "product code unchanged" twice
  during this work item before it was caught.
- **CI runs the gate, not a subset.** The workflow ran `pytest` and `ruff` while the gate also
  covers the standalone benchmark run, every scorecard and the kernel diff — so a scorecard
  regression could pass CI and fail locally. It now runs `python scripts/verify.py` with an
  explicit base, and records the PR head SHA, the base SHA and the **actual checkout SHA**
  separately: on a `pull_request` event the checkout is `refs/pull/N/merge`, so "we tested the
  head" and "we tested a merge of the head" are different claims and only one of them is true.

### Added
- **MCP server.** `src/virtualcell/mcp/` exposes three tools — `list_domains`,
  `describe_domain` and `reason` — over the same `ReasoningService` the API and CLI use.
  No new request type, no MCP-specific reasoning path, no re-derivation: the adapter is a
  fourth surface, not a new capability. Install with `pip install "virtualcell[mcp]"` and
  run with `python -m virtualcell.mcp`.

  **Ordering is the safety mechanism.** Every boundary this platform has built lives inside
  the report as text, and nothing forces a summarising model to relay it — three verticals'
  worth of refusals can evaporate in one summarisation step. So `reason` returns a model
  whose field order puts the status (and an explicit reason when it is null), the
  measurements the domain did not recognise, the missing inputs, the limitations and the
  overinterpretation risks *before* the summary. The SDK derives both the output schema and
  the serialized object from that declaration, so the order is structural rather than a
  convention a client has to honour.

  Two decisions came out of building it against the real SDK. A tool typed "answer **or**
  refusal" has its payload wrapped under a single `result` property, which flattens exactly
  that ordering — so an anticipated failure travels on the tool-error channel instead,
  carrying a parseable `ToolRefusal` that names the tool which fixes it (`unknown_domain`,
  `unsupported_task`, `invalid_experiment`, `malformed_query`). And the SDK import is
  confined to `virtualcell.mcp.server`, so the payload shapes and the safety text stay
  importable — and testable — without the extra installed.

  The adapter names no vertical, imports no `virtualcell.agents` module and holds no
  per-domain branch; everything domain-specific arrives through `DomainRegistry` and
  `DomainDescription`. A test registers a domain this repository does not ship and drives
  all three tools against it, and an AST guard fails if any module under
  `src/virtualcell/mcp/` ever mentions a registered domain by name.

  Strictly additive. No pack, kernel or scientific rule changed; all four scorecards hold
  their per-question scores and the CLI and API responses are byte-identical.

- **Round-trippable missing inputs (PR19).** `ReasoningResponse.missing_inputs` carries typed
  `MissingInput` entries beside the existing `missing_information` strings: a stable `id`, the
  **canonical** `canonical_axis` to resubmit, a human `label`, `why`, the `task` that needs it,
  and the `value_type` / `vocabulary` / `minimum` / `maximum` / `unmeasured_value` needed to
  construct a valid value without a second round trip.

  **Only missing experiment inputs.** Validation goals, next experiments, limitations and
  risks keep their own response fields; nothing is duplicated here. A list named "missing
  inputs" that also held advice would force every consumer to filter it before acting, and
  advisory entries had no stable identity - their ids were list positions, so reordering a
  recommendation reassigned an id to a different sentence. `id` is now
  `{domain}.axis.{canonical_axis}`, derived from identity rather than wording or order.
  `resubmittable` is retained as a computed field that is always true, stating the promise
  explicitly rather than leaving it to be inferred from the field name.

  This closes the last blocking MCP prerequisite. Immortalization reported `SA-b-Gal` for an
  axis a caller must send as `SA_b_gal`, so an agent that echoed the platform's own string was
  told its correct measurement was an unrecognised key - a contract failure, not a caller
  mistake.

  `AxisDescription` gained `display_label`, making the three names explicit and distinct:
  `name` is the public query key, `canonical_name` the internal model field, `display_label`
  prose. Resolution happens at each pack's conversion boundary by **exact lookup** against its
  own declaration, never by normalising punctuation; a pack reporting a gap its description
  does not declare raises `UnknownRequirementError` rather than shipping a keyless
  requirement.

  A `MissingInput` refuses to express the failure it exists to prevent: a resubmittable kind
  must name an axis, and a non-resubmittable one must not carry a key an agent could mistake
  for a field.

  **Compatibility: strictly additive.** `missing_information` keeps its exact values and
  order - `SA-b-Gal` included, and still refused as an experiment key. No status, flag, claim
  text, tier, citation, confidence, mechanistic chain or recommendation changed, and all four
  scorecards hold with identical per-question scores. CLI `--format text` now prints
  `SA-b-Gal  (send as: SA_b_gal)`; `--format json` is additive only.

- **Developer harness: `CLAUDE.md` and `scripts/verify.py`.** One command —
  `python scripts/verify.py` — runs the full suite, the benchmark suite, every scorecard,
  `ruff check`, `ruff format --check` and a kernel-unchanged diff against `origin/main`,
  and exits non-zero if any of them fails. Scorecards are discovered by globbing
  `tests/benchmarks/eval_*_v0.py`, so a new vertical's scorecard is picked up without
  registering it anywhere. `--fast` skips the scorecards; `--base <ref>` retargets the
  kernel diff.

  pytest runs with a `--basetemp` created outside the repository and removed afterwards:
  a basetemp *inside* the tree once fed fixture files to `ruff check .` and produced
  phantom lint errors that belonged to no source file.

  Tooling only — no `src/` or `tests/` change, and the test count is identical to the
  commit it was branched from.

- **Third reasoning vertical: genome-edit validation (PR18).** `{"domain": "genome_editing"}`
  is answerable on the service, HTTP and CLI, with its own curated seed graph (21 nodes /
  22 edges), four-value status vocabulary, six flags, and a ten-question benchmark written
  before the implementation (10/10). Chosen for the shape of its decision rather than its
  subject: it judges a molecular claim about a construct, and the verdict turns on **how** a
  value was measured, not on the value — a PCR band reaches no conclusion in either direction.
  **Kernel changes: zero**, and one line in the composition root.

  New public API: `virtualcell.agents.genome_editing.*` and
  `virtualcell.knowledge.sources.genome_editing_seed.GenomeEditingSeedSource`.

- **Domain self-description (PR18).** `DomainPack.describe()` returns a `DomainDescription`
  (`virtualcell.platform.description`): tasks with purposes, per-task required and read axes,
  and each axis's canonical name, description, value type, vocabulary, required flag, kind
  (`status` / `guidance` / `context`) and unmeasured spelling. Reachable as
  `DomainRegistry.describe(domain)` and `.descriptions()`.

  **Breaking for third-party packs only:** `register()` now refuses a pack without a
  `describe()` method. No shipped pack, request contract or response shape changed.

  This replaces PR17's private `_STATUS_AXES` / `_GUIDANCE_AXES` duplication: `AxisKind` is now
  the single declaration and each pack's `measurement_consumption` is derived from it via
  `derive_consumption`. One consequence is visible in responses — the `reason` text on
  `not_applicable` entries is now uniform across domains rather than per-pack prose, and a
  `not_applicable` entry for an axis a *task* does not read now says so explicitly. Statuses,
  flags, evidence, tiers, citations, confidences and benchmark scores are unchanged.

- **Strict validation on adipogenesis marker axes (PR18 hardening).** The eleven categorical
  marker axes (`PPARG`, `CEBPA`, `FABP4`, `ADIPOQ`, `PLIN1`, `lipid_accumulation`,
  `lipid_efficiency`, `WNT_signalling`, `DLK1`, `viability`, `morphology`) were typed
  `str | None` and accepted any string. Because an unrecognised value matched neither the
  present set (`high`) nor the absent set (`low` / `absent`), it was then treated exactly like
  `unknown` — so `PPARG: "hgih"` produced a confident report that had silently dropped the
  marker, in the one vertical whose purpose is separating "we did not look" from "we looked and
  it was not there".

  They are now typed to `virtualcell.agents.adipogenesis.models.MarkerValue`
  (`high` / `low` / `absent` / `unknown`).

  **Compatibility: every previously documented value stays valid** and an omitted field still
  means no reading. What changes is that an *invalid* value is now refused at the boundary
  rather than absorbed: HTTP `422`, CLI exit `1`, `QueryValidationError` in-process, where
  before it returned `200` with the axis treated as unmeasured. Statuses, flags, evidence,
  tiers, citations, confidences and all benchmark scores are unchanged.

  This is boundary hardening for invalid input, and it also makes the new domain description
  honest: a description that publishes a four-value vocabulary while the model accepts anything
  is a contract that lies — which matters far more now that an agent can read it.

- **`DomainPack.validate_experiment(task, experiment)` (PR18 hardening).** Runs a domain's real
  input validation without executing any reasoning, raising `QueryValidationError` on a payload
  the domain cannot accept. Added so the platform can check a description against the input
  contract it describes **without knowing which vertical it is talking to** — the drift test
  previously mapped three domain names to three Pydantic model classes, which quietly made "a
  new domain is validated the moment it is registered" untrue. The validation source stays
  inside the pack.

  Also new: `virtualcell.platform.domains.validate_pack(pack)`, the full consistency check
  (description domain matches the pack, described tasks match `supported_tasks`, no duplicate
  task, no task naming an undeclared axis, and **every declared axis is a payload the pack's own
  validation accepts**). `register()` performs the cheap structural subset; `validate_pack`
  adds the per-axis probe, which costs a validation call per axis and belongs in a composition
  test rather than a constructor. `virtualcell.platform.description.probe_value(axis)` supports
  both.

  **Breaking for third-party packs only:** `register()` now refuses a pack without
  `describe()` or `validate_experiment()`, and refuses a description that contradicts the pack.
  No shipped pack, request contract or response shape changed.

- **`docs/mcp_server_design.md`** — design only. Three tools (`list_domains`,
  `describe_domain`, `reason`) over `src/virtualcell/mcp/`. **No MCP package, server,
  dependency or tool registration is added in this change.**

- **Measurement-consumption transparency (PR17).** `ReasoningResponse` gained
  `measurement_consumption`, reporting for every key the caller submitted what the reasoning
  did with it: `used_for_status` (reached the verdict), `used_for_guidance` (consulted for
  flags, evidence, safety caveats or next experiments, but not for the status),
  `not_applicable` (submitted, with nothing for this task or this reading to consult it for),
  `unsupported` (the domain does not recognise the name), or `quality_excluded` (QC did not
  mark it `valid`). Each entry carries `submitted_as`, `canonical_name`, `used_for`, `reason`,
  `provenance` and a computed `affected_status`; the report adds `unsupported` and
  `status_inputs` summaries. Exposed identically on the Python service, HTTP and CLI
  `--format json`, with a compact block in CLI `--format text`.

  This closes the gap where an unrecognised key — a typo such as `gamaH2AX` — was accepted,
  preserved on the input, and reached no reasoning, producing a response byte-identical to not
  having submitted it.

  **Compatibility: strictly additive.** The field is defaulted, so existing clients are
  unaffected and a pack with no declared policy reports nothing rather than something wrong.
  No `candidate_status`, flag, evidence tier, citation, confidence or claim text changed, and
  both scorecards hold with identical per-question scores. The vocabulary lives in
  `virtualcell.core.consumption` (not `platform`) because the canonical-experiment adapters
  under `agents` need it too, and an `agents → platform` import closes a dependency cycle.

  New public API: `virtualcell.core.consumption.{ConsumptionStatus, MeasurementConsumption,
  ConsumptionReport, ConsumptionLedger}`, re-exported from `virtualcell.platform`; and
  `virtualcell.agents.immortalization.run_consumption(run)`, the reporting companion to
  `run_to_passage_series` that names which canonical measurements QC kept out and why.

  The field invariants are enforced by a `model_validator` on `MeasurementConsumption`, not
  only by the builder, so a deserialised payload or a future pack cannot express a
  self-contradicting entry: `canonical_name` is `None` **if and only if** the status is
  `unsupported`; consumed states must name at least one `used_for` purpose and must carry no
  `reason`; unconsumed states must carry a non-blank `reason` and no `used_for`. Entries are
  frozen. `provenance` is not required on the general model, though the canonical conversion
  path always supplies one.

  Known limitations are recorded in [`docs/measurement_consumption.md`](docs/measurement_consumption.md):
  `used_for_guidance` means "was read for these purposes", not "changed the output";
  `quality_excluded` is not yet reachable from a `ReasoningQuery` because the query contract
  carries `PassageObservation`s, which have no quality flag; and an unrecognised key is
  reported rather than rejected.

### Changed
- **Contract notes (PR7 hardening).** Relative to the last *released* version, the PR7
  output is additive. However, one change happened *within* the unreleased PR7 line and
  affects both the Python API and the HTTP/CLI JSON: the `DecisionReport.trajectory`
  key `terminal_dt_deterioration` was renamed to `terminal_dt_spike` (its computation —
  final DT vs the preceding observations' median — is unchanged; the name now reflects
  that it is a single-terminal-point signal, not a window trend). Clients built against an
  intermediate PR7 commit must update that key. Because PR7 is still `Unreleased`, no
  compatibility alias is added. Purely Python-level (in-process) changes, with no HTTP/CLI
  effect: (1) `immortalization.effective_markers.reconcile_markers()` returns a 4-tuple
  `(markers, derived_input, input_conflicts, blocked_overrides)` — was a 3-tuple; (2) it no
  longer globally early-returns on `state == insufficient_series`, so each axis is reconciled
  on its own derived value (a valid DT trend applies even when PDL is too thin); (3)
  `SeriesQualityFlag` dropped `SPARSE_LATE_PASSAGE` / `POSSIBLE_OUTLIER` and added
  `SPARSE_PASSAGE_SAMPLING`. In-process callers should update to the new shapes.
- **`DecisionReport` hardened + linked to `AgentOutput` (GPT review, pre-PR5).**
  `candidate_status` and `flags` are now enum-validated (`CandidateStatus` /
  `AssessmentFlag`, moved to `reasoning.decision` and reused by the deterministic
  baseline) so a typo can't slip through; added `missing_axes`,
  `conflict_explanation`, and `limitations` fields; relevance scores are bounded
  to `[0, 1]`. `AgentOutput` gained an optional `result: dict` so an agent can
  preserve a full structured `DecisionReport` (via `model_dump()`) instead of
  losing it to the `notes` string.

### Added
- **PR8c extraction hardening.** The acceptance boundary is now **task-aware**:
  `accept_candidates(document, result, task)` rejects any measurement candidate whose
  `measurement_name` is not a requested target or does not match the cited cell's axis
  (with `sample_group` on the opposite axis of the *same* cell), so an LLM cannot smuggle
  in an unrequested or renamed measurement. `SourceLocator` gained `row_index`/`column_index`
  and every table constraint must hold on one cell. `RelevanceResult` now carries `provider`,
  so a provider_id-only article's score resolves and the agent ranks it correctly (was: 0);
  ranking, dedup and the agent share one `ArticleIdentifier.stable_key`
  (PMCID > PMID > DOI > provider-scoped id) and same-provider_id-across-providers no longer
  collides. `ExtractionTask` gained a run-wide `max_total_candidates` alongside the
  per-document `max_candidates`; the agent applies both (accept → dedup → per-document →
  global). Statistic columns / values are split as before. Documented invariant: a
  `statistic`-tagged candidate is not a biological measurement and is out of scope for PR8d
  canonical mapping.
- **Source-grounded literature extraction (PR8c).** `literature.documents` parses
  open-access JATS safely: DOCTYPE/ENTITY declarations are refused before parsing (so
  neither a billion-laughs bomb nor an external/entity-smuggled reference can resolve —
  ElementTree never fetches remote resources), size and section/table/row/cell counts are
  bounded, malformed/oversized XML raises a typed `JatsParseError`, and a well-formed
  document with no `<body>` is a warning rather than an error. Inline-tag text, section/
  table order, captions, footnotes and row/column labels are preserved; the parsed body
  stays in-process and only `DocumentMetadata` (identifier, `content_hash`, counts,
  warnings) enters a bundle. `literature.extraction` is targeted by an `ExtractionTask`
  (a cell becomes a candidate only when an axis label matches a requested measurement),
  keeps values split (`raw_value`/`parsed_value`/`comparator`/`uncertainty`/`unit`/
  `parse_status`) so `<0.05` stays a bound and `increased`/`NS` never gain a number, and
  gates every extractor behind `accept_candidates`, which re-checks locators and numbers
  against the real document — a fabricated span, unknown table, wrong label or
  hallucinated value is rejected. `StructuredLiteratureExtractor` is a separate typed
  protocol (the narrative `LLMBackend.answer` is deliberately not reused); only a fake
  extractor is used in tests and **no production Anthropic adapter is implemented yet**.
  The discovery agent/CLI gained opt-in extraction (`--extract --target-measurement …`).
  All PR8c candidates are **unverified**: `verification_decisions` and `canonical_runs`
  stay empty and nothing is written to the KnowledgeStore (PR8d owns verification).
- **Automated literature discovery — first slice (PR8b).** A new `virtualcell.literature`
  package that keeps *finding/reading a paper* strictly separate from *verified evidence*.
  Contracts (`contracts.py`): `LiteratureQuery` (non-empty, bounded), `ArticleRecord`
  (metadata only — never a biological claim), source-anchored extraction candidates
  (`ExtractedMeasurement`/`Claim`/`AuthorInterpretation`, each with a `SourceLocator` + text
  hash, defaulting to `pending_review`), a transparent `RelevanceResult` breakdown (search
  relevance only), `VerificationStatus`/`VerificationDecision`, and `LiteratureEvidenceBundle`.
  A bounded, injectable `EuropePmcProvider` (`providers/`) over the official public REST API
  (no scraping, no paywall circumvention; stdlib `urllib` transport, capped pages/results,
  bounded retry, explicit timeout, descriptive User-Agent; provider error ≠ zero results).
  Deterministic `discovery.py`: query building (phrase-quoted, sanitized, only caller-provided
  synonyms, expansions recorded), dedup (PMCID > PMID > normalized DOI > title fallback), and
  additive relevance scoring. `LiteratureDiscoveryAgent` (registered as `literature_discovery`)
  + `virtualcell literature discover` CLI return the typed bundle in `AgentOutput.result` with
  **no biological `Claim`s** and confidence 0.0 (not the relevance score). The existing
  `LiteratureAgent` (KnowledgeStore retrieval) is unchanged. Extraction/verification/canonical
  conversion are the next slices; nothing here writes to the KnowledgeStore. Tests use a fake
  transport/provider — no network, no LLM.
- **Canonical experiment schema + immortalization adapter (PR8a, additive).** A new
  source-neutral contract `virtualcell.core.experiment` — `ExperimentRun` / `Observation`
  / scalar `Measurement` (+ `MeasurementQuality`) / `Provenance`, a discriminated
  `TimePoint` union (passage / elapsed_time / simulation_step / timezone-aware timestamp),
  and orthogonal `OriginKind` (simulation|experiment) ⟂ `AcquisitionMode`
  (manual|instrument|robotic|imported). It stays in `core` and imports nothing from
  `agents`/`reasoning`. An immortalization adapter (`agents/immortalization/adapters.py`:
  `passage_observation_to_canonical`, `canonical_to_passage_observation`,
  `passage_series_to_run`, `run_to_passage_series`) maps canonical runs to/from
  `PassageObservation` — reshaping only, no reasoning; a canonical run can therefore feed
  the existing `extract_trajectory` pipeline. This is additive: the existing
  immortalization input, API, and CLI are unchanged, and no path is migrated onto the
  canonical schema. The adapter carries only the two trajectory-relevant measurements
  (`cumulative_PDL`, `DT_hours`); other `PassageObservation` fields are not yet mapped
  (documented loss). No simulator/robot/LIMS connector, ingest, normalization, or LLM.
- **PR7 trajectory hardening (real long-culture validation).** Quality gating is now
  **axis-specific**: `TrajectoryAssessment` exposes `usable_PDL_timepoints` /
  `usable_DT_timepoints`, a derived trend is produced only when its own axis meets
  `min_timepoints`, and a partial-missing axis flags `MISSING_DT` / `MISSING_PDL`.
  Low-quality axes are blocked from overriding the snapshot — `NON_MONOTONIC_PDL` and
  the new `SPARSE_PASSAGE_SAMPLING` (policy `max_supported_passage_gap`) withhold a
  PDL override, with the reason recorded in the new `DecisionReport.blocked_overrides`;
  the snapshot value is kept and is *not* shown in `derived_input`. Classification is
  **terminal-anchored**: `re_arrest` is returned only when the series actually ends
  arrested (a historical F→G→F followed by terminal growth is `recovery_after_plateau`,
  not `re_arrest`), and `plateau_interval` is the terminal flat run only. The DT trend
  uses the full stable band with an explicit `unknown` zone between the stable band and
  the worsening threshold (no more silent "1.49× is stable"), and `TrajectoryThresholds`
  validates its ordering. A single-terminal-point `terminal_dt_spike` signal surfaces
  a late DT spike a whole-series median would dilute (reported in `uncertainty`).
  Conflict explanations name only the markers that actually contributed (no more
  "normal p16" while p16 is measured high). `SPARSE_LATE_PASSAGE` / `POSSIBLE_OUTLIER`
  removed (every declared quality flag is now produced). `baseline_status` unchanged;
  `LONGSERIES-IMM-V01` adversarial fixture added; API/CLI unchanged but now expose the
  usable counts and blocked overrides.
- **Passage-aware time-series assessment (PR7).** Typed `PassageObservation` series
  (`observations`) carry raw per-passage measurements — DT hours, cumulative PDL,
  proliferation/viability fraction, endogenous TERT/CDK4, quantitative markers —
  with field constraints (negative DT, out-of-range fractions, duplicate passages
  are input errors → `422` / non-zero CLI exit). `trajectory.py::extract_trajectory`
  deterministically classifies the proliferation course into 8 states via explicit
  `TrajectoryThresholds` (a v1 policy, not a biological law), sorting a copy so the
  input is never mutated and smoothing single DT outliers with a median early/late
  window. `effective_markers.py::reconcile_markers` lets a sufficient series' derived
  PDL/DT trend override the snapshot label, recording it in `derived_input` and
  surfacing any material disagreement in `input_conflicts` (the series value is used,
  never silently). `DecisionReport` gained `trajectory` (serialized dict, keeping
  `reasoning` domain-agnostic), `derived_input`, and `input_conflicts`; the trajectory
  is reported *alongside*, never *as*, the candidate status — a time series alone never
  confirms immortalization. New benchmark `immortalization_timeseries_v1.{md,yaml}`
  (TS01–TS12) + the de-identified `REALISTIC-IMM-V01` case + `examples/03_passage_trajectory_assessment.py`.
  The existing API/CLI accept the `observations` array unchanged.
- **Product-surface integration (PR6).** The `ImmortalizationAssessmentAgent` is now
  registered in the agent registry (`immortalization_assessment`) and reachable via
  the API (`POST /agents/immortalization_assessment/run`) and the CLI
  (`virtualcell assess immortalization --input <json>`, JSON or text output). The
  agent constructor follows the registry convention (store from
  `context.services['knowledge_store']`), the API/CLI seed the immortalization graph
  so mechanism/hypothesis reports ground, and invalid assessment input returns HTTP
  `422` (structured detail) instead of `500`. Docs synced to the implemented
  capabilities; `ruff format` applied so `ruff format --check` passes in CI.
- **`ImmortalizationAssessmentAgent` + end-to-end benchmark (PR5c-3).** A single
  `input_from_scenario` adapter (`adapters.py`, maps the benchmark `construct` key to
  `construct_type`) and `ImmortalizationAssessmentAgent` (`agent.py`) that dispatches by
  intent to the deterministic builder (Q1-Q4/Q7/Q8/Q10), the Q5/Q6 mechanism grounding,
  or the Q9 hypothesis policy, and packages the `DecisionReport` onto `AgentOutput.result`
  (`model_dump(mode="json")`, conclusion in `notes`, claim-mean confidence). The agent
  recomputes nothing. All 10 benchmark questions now run end-to-end through
  `assess()`/`run()`, with status-source boundaries pinned and a forbidden-phrasing safety
  scan — **the deterministic immortalization prototype is complete** (LLM narrative is PR5d).
- **Q9 hypothesis policy (PR5c-2).** `agents/immortalization/hypotheses.py`
  (`build_hypothesis_report`) handles the PGC1A/TERT spontaneous-immortalization
  hypothesis: it separates the established TERT/PGC1A context from the weak reported
  route, keeps "P53-independent" exactly (never P53 loss/knockout/absence), never
  promotes `ASSOCIATED_WITH`/`SUGGESTS` to causation, keeps a required citation on the
  reported-route claim, and fixes `candidate_status` to `insufficient_evidence` by
  policy (not `baseline_status`). Grounding uses a per-target relation signature so the
  spontaneous route and the strong Q6 CDK4→G1/S path cannot cross-contaminate. A
  `validate_hypothesis_report` safety guard scans assertion fields for forbidden
  phrasing (excluding the curated safety-guidance fields that name those phrases to
  prohibit them).
- **Q5/Q6 mechanism graph grounding (PR5c-1).** `agents/immortalization/grounding.py`
  (`build_mechanism_report`) combines the catalog's curated claims with intent-scoped
  `explain` paths over the rule's `seed_entity_ids` into a mechanism `DecisionReport`
  (no candidate status). A target allowlist plus a weak-relation path filter keep the
  P53-independent spontaneous route (Q9's domain) from leaking into a Q5/Q6 chain via a
  shared target; a missing seed raises `GroundingError`. Catalog claim tiers/citations
  are preserved and paths are de-duplicated.
- **Q5/Q6 mechanism-rule catalog (PR5b).** A typed `ConstructType` on the input
  and `agents/immortalization/limitations.py`: curated, evidence-tiered supporting
  *and* limitation claims for the TERT-only and TERT+CDK4 constructs (the negative
  claims the graph cannot express, e.g. "TERT alone does not bypass p16/RB"; CDK4
  is a *functional* bypass, "does not directly inhibit p16"; safety caveats on
  genomic stability, differentiation, and non-tumorigenicity). `get_mechanism_rule`
  returns the rule with `seed_entity_ids` for PR5c to ground; mechanism rules carry
  no candidate status and only internal curated provenance. No graph/agent/LLM yet.
- **Deterministic immortalization assessment builder (PR5a).**
  `agents/immortalization/models.py` (enum-validated `ImmortalizationAssessmentInput`
  over the benchmark marker vocabulary; retention split into its own `RetentionValue`)
  and `rules.py` (`build_decision_report`). Status/flags come only from the
  deterministic `baseline_status`; the builder assembles both-sided evidence,
  missing axes, conflict explanation, overinterpretation risks, and the
  validation-axes vs next-experiments split, leaving relevance scores `None`.
  Mechanism/hypothesis intents raise `UnsupportedIntentError`. Benchmark
  Q1-Q4/Q7/Q8/Q10 are run through the builder as a regression.
- **`DecisionReport` output contract (PR4b).** `virtualcell.reasoning.decision`:
  the structured assessment output — conclusion, `candidate_status` + flags,
  supporting/contradicting `Claim`s, `mechanistic_chain` (reuses `explain`'s
  `MechanisticLink` via `DecisionReport.scaffold`), uncertainty,
  overinterpretation_risk, recommended_validation, next_experiment, and
  experimental relevance scores — shaped so every benchmark `required_output` is
  representable. Placed in `reasoning/` rather than `core/contracts` to keep
  `core` free of a `reasoning` dependency.
- **Immortalization seed graph — biologist-reviewed (PR3).** A curated
  `ImmortalizationSeedSource` (26 nodes / 28 edges) over the ontology, built with
  `virtualcell seed immortalization [--load ...] [--save ...]`. Added
  `PROMOTES`/`INHIBITS` mechanistic relations. Review fixes: CDK4→p16 documented as
  a functional bypass (not direct inhibition); differentiation edge redirected to
  `assay INDICATES loss_of_differentiation`; single-marker confidences lowered;
  telomere-length & TERT-activity added as next-tests; p16/p21 marker aliases; the
  spontaneous route softened to a "recovery route" and kept `ASSOCIATED_WITH`/
  `SUGGESTS`, explicitly **P53-independent** (never `CAUSES` / "P53 loss"). Surfaced
  a real gap for PR4: `explain`'s tier is hop-based only, so a 1-hop weak
  association is mislabelled `established`.
- **Cell-engineering ontology v0 (PR2).** Extended the schema with five vertical
  node types (`CellLine`, `Marker`, `AssayResult`, `Phenotype`, `Mechanism`) and
  relations (`HAS_RESULT`, `INDICATES`, `SUPPORTS`, `CONTRADICTS`,
  `ASSOCIATED_WITH`, `SUGGESTS`, `SUGGESTS_NEXT_TEST`). `ASSOCIATED_WITH` is
  symmetric; the rest are directed, so `explain` reasons causally over them.
  Persistence round-trips the new subclasses. The molecular substrate
  (gene/protein/pathway) is unchanged.
- **Cell-engineering vertical, benchmark-first (PR1).** Landed the immortalization
  assessment benchmark under `tests/benchmarks/` (`immortalization_v0.md` +
  machine-readable `immortalization_v0.yaml`: 10 questions, a 3-status vocabulary,
  and a scoring rubric) together with a deterministic rule-based
  `baseline_status` (`virtualcell.agents.immortalization.baseline`) and a CI
  regression that freezes the baseline↔spec self-check (8/8 status questions;
  mechanism questions Q5/Q6 excluded). This is the near-term wedge; the 12-stage
  roadmap stays the north star.

### Changed
- **`explain` tiers are now relation-aware (PR4a).** A path's tier is
  `weaker_of(hop-distance tier, weakest-edge ceiling)`: `ASSOCIATED_WITH`,
  `SUGGESTS`, and `SUGGESTS_NEXT_TEST` cap the tier at `hypothesis` no matter how
  few hops, while strong relations impose no ceiling. Relation type stays
  independent of tier. This fixes the gap the seed graph surfaced — a 1-hop weak
  association is no longer mislabelled `established` (e.g. the P53-independent
  spontaneous route now reads `hypothesis`), directly serving benchmark Q9.
- **Edge directionality is now preserved for reasoning.** The store records each
  edge's direction; `edges()`/`explain()` follow biological arrows by default
  (`direction="forward"`), so `explain` yields causal/downstream reach rather than
  mere graph reachability (e.g. TP53's forward reach no longer includes its
  upstream regulator MDM2). Symmetric relations (`INTERACTS_WITH`) traverse both
  ways; `neighbors()` stays undirected; pass `direction="any"` for reachability.
- Repositioned as the **Virtual Cell Reasoning Platform** — an interpretable,
  evidence-graded mechanistic reasoning layer, not a black-box simulator. Dynamic
  ML simulation is out of scope (delegated to external models). Updated README,
  API/CLI titles, and package metadata/URLs accordingly.

### Added
- **IntAct protein-protein interaction connector** (`IntActSource`,
  `virtualcell ingest intact`): parses an IntAct MITAB export into symmetric
  `INTERACTS_WITH` edges (UniProt accessions, isoforms collapsed, `--min-score`
  filter). It is edge-only and merges onto a protein-bearing graph; `load_into`
  now skips interactions whose endpoints are absent instead of raising. This adds
  the protein↔protein mechanistic wiring so `explain` finds real chains — e.g.
  TP53 now reaches MDM2 via `encodes` then a physical `interacts_with`.
- **JSON graph persistence** (`virtualcell.knowledge.persistence`): `save_store` /
  `load_store` snapshot an ingested graph to a portable JSON file and rebuild it
  losslessly (entity subclasses, directed edges). `virtualcell ingest --save`
  persists a graph, `ingest --load ... --save` merges sources into one file, and
  the query commands (`search`/`neighbors`/`ask`/`qa`/`explain`) take `--load` to
  work over it — so real ingested genes (TERT, CDK4, ...) survive across sessions
  instead of only the bundled sample. The API loads `VCELL_GRAPH_PATH` if set.
- **`explain` is now wired into natural-language Q&A.** Grounding traces directed,
  evidence-graded mechanistic paths from the retrieved entities (instead of shallow
  1-hop neighbours), so answers can cite multi-hop chains and honestly hedge them
  (a 2-hop inference is surfaced as `hypothesis`, not `established`).
- **Evidence-graded multi-hop reasoning primitive** (`virtualcell.reasoning.explain`,
  `virtualcell explain <id>`, `GET /reasoning/explain/{id}`): traverses the graph
  from a seed entity and ranks reachable entities by a path-decayed, multi-path
  corroborated confidence. Direct curated edges stay `established`; 2-hop
  inferences are downgraded to `hypothesis` and 3+-hop to `speculative`, so an
  inference is never presented as an established fact. Each result carries the
  path that justifies it. Backed by a new typed, weighted `Edge` on the store.
- **Natural-language reasoning layer** (`virtualcell.reasoning`): retrieves a
  relevant subgraph for a question and answers it, grounded strictly in cited,
  evidence-graded knowledge-base facts. Backed by **Anthropic Claude** (`llm`
  extra + `ANTHROPIC_API_KEY`) with a deterministic offline fallback so it runs
  with no key. Exposed via `virtualcell qa` and `POST /reasoning/qa`.
- Real **Reactome** data-source connector (`ReactomeSource`) that ingests the
  `UniProt2Reactome` export into the knowledge base as `Protein`/`Pathway`
  entities and `PARTICIPATES_IN` interactions, with species filtering and source
  provenance (roadmap Stage 1 → real data).
- Real **UniProt** data-source connector (`UniProtSource`) that ingests a
  UniProtKB TSV export as rich `Protein` and `Gene` entities plus `ENCODES`
  interactions, enriching skeletal proteins previously ingested from Reactome
  under the same `protein:<accession>` id.
- `virtualcell ingest {reactome,uniprot} --path <file>` CLI command.

## [0.1.0] - 2026-07-06

### Added
- Initial open-source scaffold for the Virtual Cell Platform.
- `core` abstractions: `BaseAgent`, data contracts, `EvidenceTier`/`Claim`,
  confidence utilities, agent registry, and configuration.
- Working in-memory **Cellular Knowledge Base** (roadmap Stage 1) with graph and
  vector backend interfaces (Neo4j, Qdrant).
- Specialized agent stubs: genome, transcription, protein interaction, metabolism,
  signaling, literature, validation.
- LangGraph orchestration skeleton.
- Simulation engine interface.
- FastAPI app with `/health` and knowledge endpoints; CLI entry point.
- pytest suite, Ruff configuration, GitHub Actions CI, Docker Compose.
