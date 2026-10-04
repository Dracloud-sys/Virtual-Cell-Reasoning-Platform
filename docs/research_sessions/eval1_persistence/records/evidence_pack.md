# Shared evidence pack: the same for both conditions

**Question.** "After a treatment applied to cells is stopped, the phenotype change persists. Design
experiments that tell apart the possible explanations: residual treatment material, cell-to-cell
signalling, a persistent change of cell state, and others."

**Development assumptions (fixed for this evaluation; not confirmed by any user):**
- **Cells:** primary human fibroblasts (dermal or lung; not fixed), cultured on standard tissue-culture
  plastic unless the design changes that.
- **Treatment:** recombinant TGF-β1, about 2–5 ng/mL for 48–72 h, then washout into TGF-β1-free medium.
- **Phenotype that persists:** the myofibroblast state, read as α-SMA in stress fibres and as
  contractility, still present days after washout.
- **Not fixed:** donor, passage, serum level, substrate stiffness, exact days after washout.

The three named explanations are examples. Do not assume they are the only ones, or that they
exclude each other.

## Sources read (all abstracts read to the end through the platform's reader)

Each entry gives: what the source studied, the span ids read, and the limits on applying it here.
"Host reading" is an interpretation, not the paper's words.

**S1. Driesen et al., Cardiovasc Res 2014, "Reversible and irreversible differentiation of cardiac
fibroblasts".** DOI 10.1093/cvr/cvt338. Parent id `lit-a661aae7cadd`; spans `lit-04139c6d6982`,
`lit-4003fcca2815` (0–2030 of 2030).
- Text, abridged:
  - Adult rat cardiac fibroblasts on stiff plastic spontaneously became proliferating myofibroblasts
    (p-MyoFb).
  - TGF-β1 gave α-SMA-positive, non-proliferating myofibroblasts (non-p-MyoFb).
  - SD-208 (a TGF-β-RI kinase blocker) induced dedifferentiation of p-MyoFb, with stress-fibre
    depolymerisation, but not of non-p-MyoFb, "despite maintained stress".
  - Strain release in unrestrained 3-D collagen depolymerised stress fibres in both. "Only p-MyoFb
    showed true dedifferentiation after long-term 3-D cultures."
- Host reading: the TGF-β1-induced, non-proliferating state did not reverse with receptor kinase
  blockade or strain release, whereas the spontaneous one did.
- Limits: rat cardiac cells, not human dermal or lung. The abstract does not say how long the reversal
  was followed, or the TGF-β1 dose.

**S2. Myofibroblast persistence with real-time changes in boundary stiffness (Acta Biomater 2016).**
DOI 10.1016/j.actbio.2015.12.031. Parent `lit-3e4e13ea59f5`; spans `lit-0f512e20b35a`,
`lit-b1bf272184af`, `lit-b0c020392ab5` (0–3010 of 3010).
- Text, abridged:
  - Valvular interstitial cells in fibrin micro-tissues between magnetically tunable posts.
  - Forces rose with increased boundary stiffness and "continued to increase following dynamic
    reduction of boundary stiffness back to baseline".
  - Apoptosis and lower α-SMA followed complete freeing of the tissues, but not a twofold stiffness
    decrease.
  - "temporary stiffening of boundary causes irreversible myofibroblast activation".
- Host reading: a transient mechanical stimulus left a persistent contractile state, and only a large
  drop in tension reversed it.
- Limits: valvular cells, a mechanical stimulus rather than TGF-β1, fibrin micro-tissues.

**S3. ECM-stiffness mediated persistent fibroblast activation requires integrin and formin dependent
chromatin remodeling (Adv Sci 2026).** DOI 10.1002/advs.202517631. Parent `lit-69e5f1f121ee`; spans
`lit-13f07d427fef`, `lit-21c2cde4f3dc` (0–1723 of 1723).
- Text, abridged:
  - Human cancer-associated fibroblasts switch from transient to persistent activation after
    prolonged exposure to stiff ECM "and stiffness-dependent secreted factors".
  - β1 integrin activation smooths the nuclear lamina and reduces lamin–chromatin contacts; the
    formin mDia2 alters lamin–chromatin coupling.
  - Blocking either pathway prevents persistent activation; HDAC inhibition rescues that prevention.
- Host reading: one demonstrated route to a persistent state goes through chromatin remodeling
  downstream of matrix sensing.
- Limits: CAFs, not normal fibroblasts; the trigger is stiffness plus secreted factors, not a TGF-β1
  pulse.

**S4. Mechanical memory of mesenchymal stromal cells, SALL1–GATA6 circuit (Adv Sci 2026).** DOI
10.1002/advs.202522056. Parent `lit-870022eccebf`; spans `lit-de72b3cfc53c`, `lit-31f9da012da1`
(0–1486 of 1486).
- Text, abridged:
  - MSCs primed on stiff surfaces keep myofibroblast traits after switching to soft surfaces
    ("mechanical memory").
  - RNA- and ATAC-seq; HOXA11, SALL1 and GATA6 identified; "GATA6 as a keeper of stiff-induced
    myofibroblast memory after switching to soft surfaces".
- Host reading: chromatin accessibility and a transcription-factor circuit can hold a myofibroblast
  state after the inducing condition is removed.
- Limits: MSCs, not fibroblasts; the inducer is stiffness, not TGF-β1.

**S5. Simultaneous induction of differentiation and senescence in cardiac fibroblasts by TGF-β1
(Front Pharmacol 2026).** DOI 10.3389/fphar.2026.1877172. Parent `lit-67e938ca5b7a`; spans
`lit-e62f54ed4087`, `lit-90bac4ae80b3` (0–2130 of 2130).
- Text, abridged:
  - Neonatal rat cardiac fibroblasts, TGF-β1 for 7 days.
  - Senescence markers (p15–p16, p21), increased SA-β-gal, reduced Ki-67 and p-Rb.
  - SASP-like secretion (IL-1β, IL-6, …), elevated collagen.
  - Navitoclax and D+Q reduced viability and the SA-β-gal-positive fraction.
- Host reading: TGF-β1 exposure can also produce senescence, a stable state with its own secretome.
  That is an explanation beyond the three named.
- Limits: neonatal rat cells, 7-day exposure, and the abstract's dose text is garbled ("10 46 ng/mL").

**S6. Dupuytren's disease is mediated by insufficient TGF-β1 release and degradation (IJMS 2023).**
DOI 10.3390/ijms242015097. Parent `lit-e981f9468582`; spans `lit-8ccc91bd45f9`, `lit-d4c2a13f46ee`
(0–1934 of 1934).
- Text, abridged:
  - In Dupuytren fibroblasts, LAP-TGF-β and LTBP-1 were up and plasmin was down.
  - Exogenous plasmin inhibited α-SMA expression.
  - Caveolin-1 (TGF-β signal degradation) was down, and rescuing it inhibited myofibroblastogenesis.
- Host reading: how TGF-β is held in, and released from, the matrix-bound latent complex, and how
  its signal is degraded, can sustain or limit myofibroblast formation without new exogenous ligand.
- Limits: diseased palmar fibroblasts. This is not a washout experiment, and it does not measure
  residual exogenous TGF-β1.

**S7. c-Met and CD44v6 contribute to autocrine TGF-β1 signalling in interstitial lung disease (JBC
2014).** DOI 10.1074/jbc.m113.505065. Parent `lit-cf9c74fc6b4f`; spans `lit-91332fe8e2a5`,
`lit-ea0d3890720d` (0–1717 of 1717).
- Text, abridged:
  - An autocrine TGF-β1 signalling in ILD fibroblasts up-regulates Met and CD44v6.
  - HGF inhibited TGF-β1-stimulated collagen-1 and α-SMA expression.
- Host reading: fibroblasts from fibrotic lung can run autocrine TGF-β1 signalling; there is a
  precedent for a self-sustaining ligand loop.
- Limits: patient ILD fibroblasts, not normal fibroblasts after a pulse.

**S8. Substrate stiffness modulates fibroblast contractility and migration independent of TGF-β
stimulation (Mechanobiol Med 2025).** DOI 10.1016/j.mbm.2025.100158. Parent `lit-13bba37725f2`;
spans `lit-87a281f303a5`, `lit-086e187e2c2d` (0–1388 of 1388).
- Text, abridged: environmental stiffness "plays a deterministic role in determining fibroblast
  phenotype, surprisingly even overruling the classical TGF-β-mediated stimulation", shown by
  morphometry, traction force microscopy and migration.
- Host reading: the culture substrate (stiff plastic) can itself hold a contractile phenotype, so
  substrate is a confounder for any "persistence after washout" claim on plastic.
- Limits: the abstract does not give which fibroblasts were used or the stiffness range.

## What is NOT in the pack

- No primary source read here measures residual exogenous TGF-β1 after washout: its adsorption to
  plastic, ECM or serum proteins, or cells, and how long that lasts. Statements about residual
  ligand rest on general knowledge, not on a source in this pack.
- No source read here tests paracrine signalling between cells, for example conditioned-medium
  transfer after washout.
- Reviews returned by the searches (on mechanomemory, epigenetic memory and similar) were **not**
  read beyond 400-character excerpts and are not part of the pack.
