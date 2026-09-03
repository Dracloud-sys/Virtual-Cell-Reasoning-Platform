# MCP server: design

**Design only. Nothing in this document is implemented, and no MCP package, server, dependency
or tool registration exists in the tree.** The order is deliberate — third-domain validation
first, MCP second — because an MCP tool schema built on an unvalidated abstraction breaks when
the abstraction moves. It has now been validated by a third domain, so this can be built next
without that risk.

## Why MCP is the right surface

The platform's positioning is a complement to predictors, not a competitor: where a predictor
says *what* changes, VCRP explains *why, through which pathways, and how confidently*. The
natural consumer of that is an LLM agent, not a human typing JSON — and MCP is the protocol for
"an LLM calls a deterministic reasoning tool".

The architecture is already the right shape. Every surface goes through one entry point:

```
API / CLI / MCP  ->  ReasoningService.query()  ->  DomainRegistry  ->  DomainPack  ->  agent
```

An MCP server is a **fourth adapter**, not a new capability. Adding it should require no change
to any pack, and if it does, the boundary leaked.

## Where it lives

```
src/virtualcell/mcp/
```

It imports `virtualcell.platform` and nothing else from the codebase. It must not import
`virtualcell.agents.*`, must not name a vertical, and must not contain a per-domain branch.

## The three tools

### 1. `list_domains`

No arguments. Returns each registered domain's identifier, one-line summary, and task names —
`DomainRegistry.domains()` plus `describe()`. Cheap enough to call first, every time.

### 2. `describe_domain(domain)`

Returns the `DomainDescription` this milestone added: tasks with their purposes and required
axes, and every axis with its canonical name, description, value type, accepted vocabulary,
required/optional, whether it can move the verdict or only refine it, and how to spell "no
reading was taken".

**This is the tool that makes the other two safe.** An LLM assembling an `experiment` payload
from a sentence invents axis names constantly. Without introspection it guesses; with it, it
asks. `describe_domain` turns PR17's `unsupported` from a correction into a prevention.

### 3. `reason(domain, task, experiment, ...)`

Validates into the existing `ReasoningQuery` and calls the existing `ReasoningService.query`.
No new request type, no MCP-specific reasoning path, no re-derivation. The response is the
existing `ReasoningResponse`, **reordered** (below) rather than reshaped.

## `unsupported` is the self-correction channel

PR17's ledger is the feedback loop that makes an LLM caller safe to run unattended:

```
LLM sends   {"gamaH2AX": "high", ...}
VCRP replies  measurement_consumption.unsupported == ["gamaH2AX"]
LLM corrects  describe_domain -> "gammaH2AX" -> resend
```

Without it, the model gets a confident report that silently ignored the marker the user cared
about most, and nothing anywhere says so. The `reason` tool description must state that a
non-empty `unsupported` means **the answer was computed without those measurements** and should
be corrected and re-sent rather than reported.

## Response ordering, and the risk it mitigates

**The risk.** Every safety boundary this platform has built lives *inside* the report as text:
`overinterpretation_risk`, `limitations`, `missing_information`, the forbidden-phrase guards.
Nothing forces a calling model to relay any of it. Hand an LLM a raw `ReasoningResponse` dump
and the failure is obvious in hindsight:

```
VCRP:  insufficient_evidence - a band is not a genotype
LLM:   "The edit looks confirmed."
```

That failure cannot happen on the CLI or the API, because a human sees the whole report. It
opens the moment a model summarises. Three verticals' worth of refusals can evaporate in one
summarisation step.

**The mitigation, in three parts.**

1. **Order the payload so the refusals are read first.** The `reason` result puts, in this
   order: `status` (with an explicit `null` and its reason for mechanism tasks),
   `missing_information`, `limitations`, `overinterpretation_risks`, and
   `measurement_consumption.unsupported` — *then* the summary, evidence and mechanistic links.
   Models attend to what comes first; a summary at the top gets copied and the caveats below it
   get dropped.
2. **Make the caveats structurally unskippable, not prose.** Keep them as typed lists so a
   client cannot mistake them for narrative padding, and never merge them into `summary`.
3. **Put the rule in the tool description**, where it is read before any call — see below.

## The rule the tool description must carry

Verbatim intent, to be phrased for the tool schema:

> This tool does not invent a verdict. It returns the platform's status **together with** its
> limitations, its unmeasured axes, and its overinterpretation risks, and all of those are part
> of the answer. Report the status only alongside them. Do not upgrade `insufficient_evidence`
> to a conclusion, do not describe an axis the platform reported as unmeasured as if it had
> been measured, and if `unsupported` is non-empty, say so — the answer was computed without
> those measurements.

## The boundary test

One principle, stated as a test that must exist before the server ships:

> **If the MCP adapter knows the name of a vertical, that is a boundary failure.**

Concretely, mirroring the AST guards already in place for the kernel and the interfaces: no
module under `src/virtualcell/mcp/` may import `virtualcell.agents.*` or contain the literal
`immortalization`, `adipogenesis` or `genome_editing`. Everything domain-specific reaches the
tools through `DomainRegistry` and `DomainDescription`.

A second test worth having: adding a fourth domain must change **zero** lines under
`src/virtualcell/mcp/`.

## What this milestone already prepared

| MCP needs | status |
|---|---|
| one entry point | `ReasoningService.query` — unchanged since PR11 |
| domain enumeration | `DomainRegistry.domains()` |
| axis / vocabulary introspection | `DomainDescription` (this milestone) |
| per-task input requirements | `TaskDescription.required_axes` / `reads_axes` |
| a self-correction channel | `measurement_consumption` (PR17) |
| a validated abstraction | three domains, zero kernel changes |

## Prerequisites — blocking, not advisory

**The MCP server must not ship until these are closed.** Both are cases where an agent would
be misled by something the platform told it, which is worse than an agent that has to guess.

### 1. `missing_information` must round-trip as an axis name — **OPEN, blocking**

Immortalization reports display labels (`SA-b-Gal`) rather than axis names (`SA_b_gal`). The
loop an MCP client runs is exactly: read what is missing → measure it → send it back under the
name it was given. Today that returns `unsupported`, so the agent is told its correct
measurement is an unrecognised key.

Not fixed in PR18 because the same label is spelled inside an existing evidence claim and that
milestone must not change claim text. Pinned by
`test_missing_information_is_not_always_round_trippable_as_an_axis_name`.

### 2. Every categorical axis must be strictly validated — **CLOSED (PR18 hardening)**

Adipogenesis accepted any string on a marker axis, so `PPARG: "hgih"` passed validation and was
then treated exactly like `unknown` — a typo silently becoming "we did not look" in the
vertical whose purpose is keeping those apart. A description that promised a vocabulary while
the model accepted anything was a contract that lied, which matters far more once an agent
reads that description and believes it.

All three domains now type their categorical axes as enums. The vocabulary check in
`tests/integration/test_domain_description.py` runs in **both** directions: every declared
value is accepted, and a value outside the vocabulary is refused with a validation error.
