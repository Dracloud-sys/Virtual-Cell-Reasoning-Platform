# The decision-status contract

The question PR14b recorded, PR18 confirmed, and the third domain was supposed to trigger:
**`DecisionReport.candidate_status` carries immortalization's vocabulary while living in a
shared contract.** This document is the answer, and the answer is not the one the trigger
implied.

## What was actually found

The migration was specified on the assumption that the residue would *block* a second and
third domain. Read against the code, it does not.

| | |
|---|---|
| `DecisionReport.candidate_status` | typed `CandidateStatus \| None` — immortalization's three values |
| adipogenesis | sets `candidate_status=None` and routes its verdict through `DecisionSupport.status` |
| genome editing | the same |
| what any surface reads | `ReasoningResponse.decision_support.status` — **never** `candidate_status` |
| what reads `candidate_status` at all | the immortalization pack's own conversion, and `virtualcell assess`, which is immortalization-only |

So the platform already has one status source, and it is already domain-neutral. Two
verticals route around the residue at a cost of one line and a comment each, and neither
was blocked. The migration would buy tidiness in a contract that no caller reads, paid for
in churn against four scorecards.

**The real exposure was somewhere else**, and it was found by looking rather than by
reasoning from the trigger.

## The exposure: the envelope trusted whatever a pack put in it

Since PR18 every pack declares a `status_vocabulary` and a `flags` list. Since the MCP
server, `describe_domain` hands both to a calling agent as the authoritative list of what
it may see — which is the entire point of publishing a vocabulary; an agent is expected to
branch on those values.

Nothing checked that what a pack *emitted* was in what it *declared*. `DecisionSupport.status`
is `str | None` and `flags` is `list[str]`, and no code path compared either against the
declaration they came from.

This is the same defect PR18 fixed on the **input** side, where "a description that promised
a vocabulary while the model accepted anything was a contract that lied, which matters far
more once an agent reads that description and believes it." The output side was still open.

**No drift exists today.** That is not the reassurance it sounds like. Sweeping every
categorical axis of all three shipped domains produces 3 of 5 adipogenesis statuses, 2 of 4
genome-edit statuses, 2 of 3 immortalization statuses and 5 of 16 flags — the rest need
trends, series or day values to reach. A mismatch on one of those paths would be invisible
to every test in the tree, and would reach an agent as a verdict it cannot map and has no
reason to distrust.

## Decision

**Keep `candidate_status` where it is. Check the envelope instead.**

`validate_declared_outcome(description, support)` runs in `ReasoningService.query`, on the
one path every surface shares, and refuses a status or flag the domain's own description
does not declare.

Four properties, each deliberate:

- **No vocabulary is merged.** The comparison is always against the description that came
  from the same pack. The three domains' vocabularies stay separate, as the milestone
  required.
- **Nothing is ranked or interpreted.** The generic layer carries the value; what it
  *means* stays with the pack.
- **An empty declaration is a promise, not an exemption.** `status_vocabulary=()` means the
  pack returns no status, because that is what an agent reading the description would
  conclude. Treating it as "unconstrained" would invert it.
- **`status=None` is always allowed.** That is how a pack says it reached no verdict, which
  is a position rather than a violation.

It also fixes the thing the milestone asked for in one line rather than in a migration:
**the status source MCP reads is now the only validated one.**

### Compatibility

Strictly additive. No field was renamed, removed or re-typed; no serialized response
changed shape. Every existing response passes — proven by the full product suite, all four
scorecards at identical per-question scores, and a byte comparison of 21 fixed queries
against `main`.

### The new migration trigger

The old trigger — "the third domain" — has fired and produced this document, so it is
spent. It is replaced by a condition that would represent real damage rather than
untidiness:

> Migrate `candidate_status` when a vertical needs to read **another** vertical's status
> from the shared report, or when a caller is observed reading `candidate_status` from a
> non-immortalization response.

Until one of those happens, the field is inert residue with two documented workarounds and
a check standing over the envelope that actually gets read.

## The second finding, fixed in the same change

The sweep that produced the evidence above turned up an unrelated hole in the same
boundary, pointing the other way.

`immortalization/explain_mechanism` with an empty payload: `validate_experiment` accepted
it, `execute` then raised the vertical's own `UnsupportedMechanismError` — a plain
`ValueError` the platform does not classify — and the caller received **HTTP 500** and,
through MCP, the bare string `Error executing tool reason`. No detail, nothing to act on.

It was reachable by doing exactly what the description said: `describe_domain` listed no
required axes for that task, so an agent following it sent nothing and crashed the server.
Sending the axis's own declared unmeasured value crashed it too.

Both halves are now closed:

- The vertical's *unanswerable-request* refusals (`UnsupportedMechanismError`,
  `UnsupportedHypothesisError`, `UnsupportedIntentError`, `AssessmentInputError`) become
  `QueryValidationError`, so a caller's mistake is reported to the caller on every surface
  — 422, and the MCP `invalid_experiment` refusal — with a message naming the constructs
  that do work.
- `explain_mechanism` now declares `construct` in its `required_axes`, so an agent reading
  the description never reaches the refusal at all.

**The safety errors are deliberately excluded.** `HypothesisSafetyError` and
`ImmortalizationSafetyError` fire when the vertical produced something it must not ship.
Converting one into a 422 would tell the caller to fix a payload while the real defect went
quiet — the exact failure this platform exists to prevent. They stay loud.

That is also why `UndeclaredOutcomeError` is **not** a `DomainError`: every member of that
family is the caller's mistake and is reported as one, and an undeclared status is the
pack's defect. The honest answer there is that the server is broken, not the request.

## Recorded, not fixed

**An axis vocabulary can be wider than a task can answer.** `construct` accepts an
unmeasured value because "nobody identified the construct" is a legitimate thing to say
about a sample — but `explain_mechanism` cannot explain a construct nobody named.
`DomainDescription` has no way to express a per-task vocabulary, so the description cannot
state this and the refusal message carries it instead.

Left as a finding rather than widened into the description: one task in one vertical wants
it, and a per-task vocabulary added on first contact would be shaped entirely by that one
caller. The trigger is a second task, in any domain, that needs to narrow an axis it shares.
