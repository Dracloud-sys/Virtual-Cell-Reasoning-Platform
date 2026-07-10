# Collaboration workflow (GPT × Claude Code × human)

How the two AI agents and the human co-develop this repo. The **git repository is
the single source of truth and the durable message bus**; decisions live in
[`roadmap.md`](roadmap.md) and `CHANGELOG.md`, which are the shared memory across
both agents.

## Roles

| Actor | Owns | Cannot do |
|---|---|---|
| **GPT** (spec · domain · review) | Strategy, the benchmark + acceptance criteria, biology content (seed correctness, evidence tiers, forbidden phrasings, literature grounding), review of diffs | Run code, run tests, or push to git |
| **Claude Code** (implement · verify · repo) | The codebase, turning specs into code + tests, running lint/pytest, committing/pushing, keeping docs in sync, **surfacing implementation-level gaps** | Make the final domain (scientific) judgment |
| **Human** (arbiter · bridge) | Trade-off decisions, carrying artifacts between the agents, final go | — |

The agents' strengths do not overlap: GPT brings literature-grounded domain
correctness; Claude runs the code and surfaces *real* gaps (e.g. the relation-aware
tier ceiling was found by running the seed, not by reasoning about it).

## The loop: Spec → Implement → Verify → Review (benchmark is the referee)

```
1. GPT    → writes the PR spec + acceptance criteria (machine-readable where possible)
2. Human  → lands the spec (see "git mechanics") and points Claude at it
3. Claude → implements + runs tests + commits/pushes, then reports back:
            diff summary · test results · real output samples · discovered gaps · questions
4. Human  → gives GPT the pushed commit hash to review
5. GPT    → reviews the REAL commit, returns structured feedback: apply-now / defer(PRx) / keep
6. Claude → applies, re-verifies, commits
   If in doubt, add/adjust a benchmark case; a green benchmark = agreement.
```

## git mechanics (who reads / who writes)

GPT **cannot push** to git (absent a GitHub tool/connector). So:

- **Reading = git-centric (both sides).** Every review references a real commit
  hash / GitHub URL, never a pasted, possibly-stale snippet. This is the main
  anti-divergence rule. Repo is public: `Dracloud-sys/Virtual-Cell-Reasoning-Platform`.
- **Writing = asymmetric.** Claude pushes code/tests/docs directly. GPT's artifacts
  (specs, reviews) reach git through the **human** — committed to the repo (e.g.
  under `docs/specs/`, or as a GitHub issue/PR comment) or simply relayed.

Recommended default (a hybrid of "all-git" and "all-manual"):

- If **GPT can browse the web/GitHub**: the human carries only GPT's *outputs* into
  the loop; GPT reviews pushed commits directly by URL + hash. (Least friction.)
- If **GPT cannot browse**: the human must also paste the current file/diff to GPT
  (higher divergence risk — keep snippets tied to a commit hash).

## Guardrails

1. **Single writer to git.** Only Claude commits, to avoid two-writer races.
2. **Sync anchor = commit hash + URL.** GPT never assumes file contents; it reviews
   the pushed commit.
3. **Ownership by layer.** GPT = benchmark/spec/seed-content/review; Claude =
   engine/infra/tests/docs. In the overlap (seed biology) GPT authors the content
   and Claude encodes it and reports implementation constraints (e.g. "negative
   edges can't be expressed → handle in the agent rule").
4. **Decisions are recorded** in `roadmap.md` / `CHANGELOG.md` so neither agent
   re-litigates.
5. **GPT code is a proposal.** Since GPT can't run/verify, it prefers specs,
   acceptance criteria, and reviews; reference implementations (e.g.
   `baseline_status`) are fine but Claude integrates and verifies them.

## Handoff formats

- **GPT → Claude:** machine-readable specs (YAML like the benchmark) are best — Claude
  turns them straight into tests. Biology content as a table (node/edge · relation ·
  tier-intent · confidence · citation). Reviews as structured *apply-now / defer / keep*.
- **Claude → GPT:** the committed diff/file + commit hash, test results, real behavior
  samples (e.g. `explain` output), and a short gaps/questions list (only what needs a
  domain call).
