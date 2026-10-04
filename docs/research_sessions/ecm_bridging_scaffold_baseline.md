# ECM bridging scaffold — baseline draft (preserved for comparison)

This is the **first** host-written draft from the 2026-09-23 session, kept verbatim as the
comparison baseline for the revised design in `ecm_bridging_scaffold.md`. It is not the
current design. Do not cite it as one.

## How it was produced

- Host: Claude Code with the `virtualcell` MCP server (`.mcp.json`, `--literature`).
- `research_evidence("collagen scaffold degradation", search_literature=true)`:
  first call `literature: lookup_failed` (Europe PMC returned no usable hitCount — a failed
  lookup, not an absence of literature); the identical second call `ok`, 25 articles, 23
  citable spans, **all 23 truncated at 400 characters**.
- No span was read past its first 400 characters. None of the returned spans reported
  degradation kinetics or mechanism for a collagen scaffold.
- The nested field names for `check_research_draft` (`support`, `discriminates`,
  `branches[].outcome/implication`) were **not** in the tool's input schema. The host
  learned them by reading `src/virtualcell/research/contracts.py`. The first submission used
  guessed names and got `unexpected_model_field`, `no_decision_branches` and
  `discriminates_nothing` findings for fields that were present under other names.

## What was submitted (third, accepted submission)

**Restated question.** In a cell-seeded type I collagen scaffold cultured in vitro, how much
of the observed scaffold mass/structure loss is cell-mediated (MMP-dependent) versus
cell-independent (hydrolytic or medium-driven), and does crosslinking change that split?

**Hypotheses** (all `unverified_candidate`)

- H1 — Scaffold loss in cell-seeded constructs is predominantly MMP-dependent proteolysis by
  the seeded cells.
- H2 — Scaffold loss is predominantly cell-independent (hydrolysis or medium components);
  cells contribute little.
- H3 — Apparent mass change is dominated by cell-driven contraction and new ECM deposition,
  which masks degradation.

**Experiment E1.** 2x2x2 factorial: cells (seeded vs acellular) x broad-spectrum MMP
inhibitor (GM6001 vs vehicle) x crosslinking (EDC/NHS vs none); n>=4 constructs per arm per
timepoint; d0, d3, d7, d14, d21. Measurements: dry mass; hydroxyproline in scaffold and
conditioned medium; construct area and thickness; collagen cleavage neoepitope in medium;
DNA content; SEM or SHG fibre architecture; newly synthesized collagen by metabolic label.
Branches: inhibitor reduces the cell-dependent loss without a drop in DNA → "favours H1";
no cell or inhibitor effect → "favours H2"; area shrinks while mass/hydroxyproline flat or
rising → "favours H3"; inhibitor lowers DNA → confounded.

**Evidence cited.** `lit-1e00520d14d7` (double-layer collagen scaffold, NPMSC
proliferation) and `lit-fac7693ec391` (MMP13-sensing dual-drug scaffold), as context only;
both `server_retrieved`.

**Check result.** `findings: []`, `scientific_validity_checked: false`. That is a structural
result only.

## Problems recorded against this baseline

1. **The goal shrank.** The research goal is an ECM-based material that temporarily bridges
   and supports a defect and hands function over through cell ingress and new ECM
   formation, with scar minimisation as the long-term aim. The baseline answered only "why
   does the scaffold lose mass", and dropped infiltration, original-vs-new ECM, bridge
   continuity, and persistent contraction/fibrosis.
2. **Unconfirmed choices were written as the system.** Type I collagen, dermal fibroblasts
   and EDC/NHS were never confirmed by the researcher; the baseline stated them as the
   system rather than as candidates.
3. **Hypotheses were treated as mutually exclusive.** Cell-mediated proteolysis, hydrolysis
   and contraction/deposition can all run at once; "favours H1 over H2" framing hides that.
4. **Inhibitor logic overreached.** GM6001 reducing loss with DNA content unchanged was
   written as sufficient for MMP-mediated degradation. It is not: GM6001 is broad-spectrum,
   DNA content does not measure MMP expression or cell behaviour, and the inhibitor can
   change contraction and deposition too.
5. **New protein was conflated with new collagen.** "Newly synthesized collagen by metabolic
   label" named a readout that a general protein label does not provide.
6. **Replicates and timepoints were presented as a fixed standard** (n>=4; d0-d21) with no
   source.
7. **Evidence read was 400-character prefixes.** No method or result section of any paper
   was read, so no design decision rested on literature.
