# Questions the revision comparison must answer

Written **before** `virtualcell.research.revision` existed, on 2026-10-04, from the gap this case
found: the platform could check one draft, and trace what rests on an evidence id inside it
(`what_if`), but nothing compared a revised draft with the one it revises. A host could rewrite
a plan after reading new papers and no code would say what changed, whether the change cites
what was read, or whether anything else moved with it.

Each question is answered by code from two drafts and the host's stated decisions. None asks
code to judge whether a change is scientifically right. The tests in
`tests/integration/test_mcp_draft_revision.py` hold each one, on the product path
(`check_research_draft` / `check_research_draft_file` through `build_server()`).

| # | Question | What a passing answer looks like |
|---|---|---|
| R1 | Which evidence is new, and what does each new id reach? | Evidence ids added, removed or edited (same id, other `content_hash`); for each new id, the hypotheses, mechanism links and predictions that cite it, and the `what_if` impact of withdrawing it from the revised plan. |
| R2 | Is the source kept apart from the reading? | Each new id's roles are listed as the host's (`interpretation_by: host`); origin stays the existing `server_retrieved` / `host_supplied` classification. |
| R3 | Is a method, contradicting or scope-limiting source quietly counted as support? | A new id linked to a hypothesis with a non-`supports` role and also listed in that hypothesis's `supporting_evidence_ids` is a finding. |
| R4 | Are several spans of one paper counted as one study? | New evidence is counted by article as well as by span. |
| R5 | Are limits that were dropped visible? | Removed assumptions, open conditions, open items and per-prediction assumptions are listed as removals, not folded into "modified". |
| R6 | Did anything change that the new evidence does not reach? | Every changed object says which new ids it cites directly; changes that cite none and are covered by no decision are listed as untraced. Unchanged objects are counted, and unchanged experiments are named. |
| R7 | Is the original plan preserved? | The result names both drafts by hash; nothing in the prior is rewritten, and the prior hash is the hash of what was submitted as prior. |
| R8 | Does each decision match what happened? | Decisions are `keep`, `revise`, `hold` or `unchanged_no_new_evidence`, recorded as the host's. A decision on an unknown target or citing an id the revised draft does not hold is a finding; `keep` or `unchanged_no_new_evidence` on a changed target is a finding; `revise` on an unchanged target is a finding; `unchanged_no_new_evidence` citing evidence is a finding; a changed hypothesis, mechanism link or experiment with no decision is listed. |
| R9 | Did a predicted value move, and on what? | Every change of `expected` is listed with its old and new value and the new ids it cites. Code never changes a value. |
| R10 | Does a small draft on an unregistered subject take the same path? | The same call with an unrelated two-hypothesis draft returns the same structure. This is a reuse test of the contract, not a second biological evaluation. |

Not asked, on purpose: whether the revision is better, whether a role is right, whether a new
source applies to the researcher's system, or which experiment should go first. Those are the
host's argument and the researcher's decision.
