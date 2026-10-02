# What the VCRP check changed in the plan (condition B)

Two calls to `check_research_draft`: payload 1 → 83 findings; revised payload 2 → 1 finding.

## Changed in response to the check

- **`discriminates` was being misused.** I had written pair strings ("H1 vs H2"). The checker returned
  43 findings: `unknown_hypothesis_id` ("'H1 vs H2' ... is not a hypothesis here") plus a matching
  `discrimination_claimed_without_predictions` for each. Changed to plain hypothesis-id lists per
  experiment. This was a schema error of mine, not a scientific one — but it had silenced the
  discrimination bookkeeping for every experiment.
- **Hypothesis support labels were not backed by citations on the hypothesis object.**
  `unsupported_evidence_link` for H2-H6: "claims to be evidence-linked, but nothing it cites is a user
  observation or a span read from a source." `evidence_links` alone did not count. Added
  `supporting_evidence_ids` to H2-H7 and `contradicting_evidence_ids: [lit-4003fcca2815]` to H1.
- **Three predictions had `basis: assumption` with no assumption written out**
  (`assumption_without_stated_assumptions`: E2/H1 CM transfer, E3/H1 clonal bimodality, E4/H1 GATA6).
  Added the explicit assumption behind each. After the revision, **0 prediction traces have gaps**.
- **Objective coverage was partly implicit.** `objective_levels` listed many
  `reached_without_stated_level` entries (e.g. E6 touching O1, E3-E6 touching O2). Added explicit
  `out_of_scope` / `proxy` entries so each experiment states what it does *not* reach, instead of
  leaving the checker to note silence.

## Flagged and deliberately not changed

- **ML11 `no_evidence`** (residual exogenous TGF-β1 adsorbing to plastic/ECM and desorbing after
  washout). Left ungrounded on purpose: no source in the pack measures residual ligand, and attaching a
  citation that does not say it would hide the pack's real gap. It is called out in the answer and is
  precisely what E1 arm (f) measures.
- **All twelve mechanism links are `not_in_graph`** (the knowledge graph holds no route between these
  exact entity names). Not actionable — these are literature-derived case candidates, and renaming
  entities to force a graph match would fake corroboration. Reported as a limitation instead.
- **`understated_evidence_link` on H7** (the one remaining finding in call 2: marked
  `unverified_candidate` while citing a grounded span). Kept as unverified: `lit-04139c6d6982` supports
  only the premise that TGF-β1-induced myofibroblasts barely proliferate; no pack source tests selection
  or population composition. Calling H7 evidence-linked would overstate it.
- **Within-experiment unseparated pairs** (e.g. E1 cannot split H4/H5/H7/H8; E3 cannot split H6 from H7;
  E4 cannot split H3 from H5). Not "fixed" by adding readouts to a single experiment — the plan covers
  them across experiments, and the checker confirms **no pair is never separated** plan-wide. The
  per-experiment blind spots are reported in the answer rather than engineered away.
- **Senescence predictions that mirror H7** and the HDAC-direction prediction whose direction is my
  inference against the source's rescue result: both left standing with the caveat written into the
  prediction, since fixing them would mean asserting more than the pack supports.

## Tool issues encountered

- Both `check_research_draft` results exceeded the inline token limit and were written to files by the
  harness; copied verbatim to `condition_B_check_1.json` and `condition_B_check_2.json` and analysed
  with python/jq. No call failed.
- Call 1 included `what_if: {remove_evidence_ids: ["lit-4003fcca2815"]}`; the impact section named H4,
  H1, ML2, ML3, E1 and E5 as resting on it — i.e. withdrawing the one span that says receptor blockade
  did not reverse the TGF-β1-induced state would undercut the central H4-vs-H1 reading in E1 and E5.
  Call 2 was sent without `what_if` (confirmation only).
