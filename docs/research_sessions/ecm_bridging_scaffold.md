# ECM bridging scaffold — revised in vitro design (host draft, 2026-09-23)

Written by the host (Claude Code) on the `virtualcell` MCP server. The hypotheses, design and
interpretation are the host's; the experiment is the researcher's to approve. The baseline this
replaces is kept verbatim in `ecm_bridging_scaffold_baseline.md`.

**How the evidence was read.** Every passage that carries design weight here was read through
the host's own PubMed tools, not through VCRP. `read_evidence_source` did not exist on the host
when this design was written; it was built afterwards because of the gap this session exposed,
and it did **not** shape this design. Any live use of it is recorded separately, as its own
record, and does not rewrite this one.

**Status of this draft.** `check_research_draft` on the live host returned `findings: []`,
`scientific_validity_checked: false`. That is a structural and citation check only. It did not
judge plausibility, whether the alternatives compete, whether the experiments separate them,
whether a source supports what it is cited for, or whether controls and timepoints are adequate.

## The goal, restored

An ECM-based material temporarily bridges and supports a defect, then hands function over
through cell ingress and new ECM formation. Scar minimisation is the long-term aim; this stage
is in vitro cell experiments.

**Not yet chosen by the researcher, and used here only as candidates:** material source (type I
collagen is a candidate), cell type/source (human dermal fibroblasts are a candidate), crosslinker
(EDC/NHS is a candidate), acellular vs cell-loaded format.

## Where each goal axis is tested

| Goal axis | Experiment | Readout that answers it | What it cannot answer |
|---|---|---|---|
| Temporary bridging / continuity | **E4** gap-spanning construct | load-bearing continuity over time vs acellular bridge and empty gap; gap-length change | in vivo loading; immune-mediated loss |
| Cell ingress | **E2** scaffold against a cell source | nuclei vs depth; viability by depth; pore size/permeability | ingress by cell types not included |
| Original vs new ECM | **E3** pulse-chase, collagen-specific readout, matrix + medium | labelled collagen chains retained in construct vs released | a general protein label alone cannot say "collagen" |
| Degradation of original material (baseline question, now a sub-experiment) | **E1** cells × GM6001 × crosslinking | CHP map of denatured scaffold collagen; hydroxyproline in scaffold, medium and cell lysate; mass; geometry | which enzyme; immune-mediated degradation |
| Persistent contraction / fibrosis-like response | **E5** TGF-β1 challenge then withdrawal, serum vs defined low-serum | α-SMA, contraction incl. after withdrawal, degraded-collagen uptake, new-collagen chain ratio | clinical scarring |
| Handover (the goal itself) | **E4**, explained by E1–E3 | a *candidate* criterion, below | whether the combination means handover in vivo |

### Handover: a candidate criterion, not a definition

The combination "continuity kept in cell-laden but not in acellular bridges, while new collagen
rises and the gap does not shorten" is a **candidate** way to judge handover in vitro, to be
revised once E1–E4 data exist. It is not sufficient on its own: continuity in a cell-laden bridge
can come from **original material that cells have protected or slowed the loss of**, from **new
matrix**, or from both. The criterion only means handover if E4 separates the two contributions —
remaining original material (CHP / pre-label) and new collagen (E3 method) measured in the same
construct as the mechanics.

## Hypotheses — not mutually exclusive

Any combination can hold at once; each experiment estimates contributions, not a winner.

- **H1** Cell-dependent proteolysis contributes to loss of original material; metalloproteinase
  activity is one candidate route among several. *unverified_candidate*
- **H2** Cell-independent loss (hydrolysis, medium) contributes. *unverified_candidate*
- **H3** Cell-generated contraction changes geometry and mass readouts independently of
  degradation. *unverified_candidate*
- **H4** Crosslinking/permeability changes nascent-matrix deposition and ingress as well as
  degradation — a trade-off variable. *evidence_linked* to host-necm-2; source is engineered
  hydrogels, not EDC/NHS collagen.
- **H5** A myofibroblast-like state couples higher contractility with reduced degradation and
  reduced uptake of degraded collagen. *evidence_linked* to host-tpm-1 and host-mrc2-1; sources
  are renal fibroblasts on collagen gel and lung myofibroblasts.
- **H6** New matrix accumulates and carries load before the scaffold loses continuity
  (handover). *unverified_candidate* — the goal behaviour; nothing read tests it.

## Experiments

**E1 — degradation routes (baseline factorial, kept and revised).** Cells present/absent ×
GM6001/vehicle × crosslinked/non-crosslinked. Readouts: CHP staining of denatured scaffold
collagen in sections; hydroxyproline in scaffold, conditioned medium **and cell lysate**; dry
mass; area/thickness; α-SMA; DNA; cell-associated signal from a pre-labelled scaffold if the
material allows. Controls include an inhibitor-only viability check and **measuring the
inhibitor's effect on contraction and deposition**.
Branches: GM6001 reduces the cell-dependent loss with viability and contraction unchanged →
*consistent with* a metalloproteinase-sensitive contribution; it does not identify the enzyme,
exclude internalisation or other proteases, or make H2 false. GM6001 also shifts contraction,
deposition or DNA → confounded. Area falls while scaffold hydroxyproline and CHP do not →
contraction, not degradation.

**E2 — ingress.** Scaffold against a cell-laden gel or explant edge so cells must enter, vs
pre-seeded (which bypasses ingress); crosslinked vs not; cell source as a factor if more than
one candidate is kept. Readouts: nuclei vs depth, viability by depth, pore size/permeability.

**E3 — original vs new matrix.** Pulse-chase labelling of newly synthesised protein, read in
matrix and medium. A general label (AHA/HPG) reports **new protein**; a **new collagen** claim
needs a collagen-specific step — azido-proline, a chain-resolved gel of labelled collagen, or
label enrichment with mass spectrometry. Gene-expression ratios are not used as a proxy.

**E4 — bridge continuity and handover.** Scaffold spanning a defined gap between two anchored
ends (or an ex vivo skin-explant defect), cells entering from the edges; the same constructs read
for mechanics, remaining original material (CHP/pre-label) and new collagen (E3), with acellular
bridge and empty gap as controls. Continuity kept only because the gap shortened is recorded as
contraction, not handover.

**E5 — persistent contraction.** TGF-β1 vs none, in defined low-serum and in serum medium, then
withdrawal. Readouts: α-SMA protein, contraction over time including after withdrawal, uptake of
degraded collagen, chain ratio of newly synthesised type I collagen.

**Replicates and timepoints** are set from a pilot's variance and from the acellular scaffold's
own loss curve.

**Method details taken from single papers are options, not requirements.** The [14C]proline
pulse-chase in the Dupuytren study, its estimate of TGF-β in 10% serum (~10 ng/mL, for that
study's serum), the 14-day culture and the EDC/NHS recipe in the collagen–elastin study are what
those studies did in their systems. None is a required condition for another material or a
general constant; serum TGF-β in particular varies by lot and must be measured or controlled,
not assumed.

## What reading changed — decision by decision

Material read via the host's PubMed tools (full abstracts of seven candidates; full text of two;
located passages of a third). According to PubMed:

| Decision in the baseline | Changed to | Because of |
|---|---|---|
| "Newly synthesized collagen by metabolic label" | New **protein** vs new **collagen** separated; collagen claim needs azido-proline, chain-resolved gel or enrichment/MS | nECM perspective: AHA/HPG label nascent proteins generally; azido-proline named for collagen; enrichment separates new from existing ECM — [DOI](https://doi.org/10.1016/j.celbio.2026.100404) |
| New collagen read from the medium only (hydroxyproline/neoepitope) | Matrix **and** medium, pulse-chase | Processed new collagen was in the construct, proforms mostly in the medium — [DOI](https://doi.org/10.1172/jci.insight.175188) |
| (implicit) collagen gene expression as a synthesis proxy | Not used as a proxy | mRNA ratio showed no positive relation to the new-collagen chain ratio — same source |
| Serum unspecified | Serum vs defined low-serum as an explicit condition in E5 | that study estimated ~10 ng/mL TGF-β in its 10% serum — a reason to control serum, not a constant — same source |
| Neoepitope in medium as the degradation readout | CHP staining of denatured scaffold collagen in situ, labelled as "denatured", not "MMP" | CHP binds denatured but not intact triple-helical collagen; reports proteolysis **or** mechanical disruption — [DOI](https://doi.org/10.1021/jacs.3c00713) |
| Degradation = extracellular MMP (GM6001 + DNA sufficient) | Internalised fragments measured (cell lysate / pre-labelled scaffold); GM6001 result read as "consistent with", not "establishes" | Degraded collagen is internalised via MRC2, and myofibroblasts internalise less — [DOI](https://doi.org/10.1172/jci.insight.201712) |
| H1 vs H3 treated as alternatives | Non-exclusive; α-SMA and contraction measured alongside degradation | Myofibroblasts: increased contractility with reduced matrix degradation — [DOI](https://doi.org/10.1016/j.isci.2025.113317) |
| Crosslinking as a degradation-only factor | Crosslinking as a trade-off (degradation, deposition, ingress) — H4 | Degradability and permeability guide nascent-ECM assembly (hydrogels) — [DOI](https://doi.org/10.1016/j.celbio.2026.100404) |
| Dermal fibroblast assumed | Cell source as an open choice / factor in E2 | Fetal > eschar > adult fibroblasts in deposition and infiltration within collagen scaffolds — [DOI](https://doi.org/10.1016/j.mtbio.2025.102239) |
| In vitro degradation read as predictive | Explicit limitation: immune-mediated loss is outside a fibroblast-only system | In vivo, scaffold fragments surrounded by giant cells — same source |
| EDC/NHS unspecified | One published recipe available as a starting candidate for that study's material (33 mM EDC / 6 mM NHS, 3 h, MES + 40% ethanol, pH 5.0); not a required condition | same source |
| TGF-β1 challenge unprecedented | Precedent for dermal fibroblasts on porous collagen scaffolds + TGF-β1 | [DOI](https://doi.org/10.3390/jfb16020051) |

## Evidence provenance

- **server_retrieved** (issued by `research_evidence`, unchanged): `lit-a359897bec6b`,
  `lit-36fa8d506553`, `lit-c99c2b5d4107` — 400-character abstract prefixes, used for identity.
- **host_supplied**: every passage above that carries design weight (`host-necm-1..3`,
  `host-dup-1..4`, `host-mrc2-1`, `host-tpm-1`, `host-chp-1`, `host-otr-1`, `host-ce-1..3`),
  read through the host's PubMed tools and quoted verbatim. The server did not retrieve them and
  cannot vouch for the text.
- **Section titles — host label vs the paper's heading:**

  | id | `section_title` submitted | heading in the text as read |
  |---|---|---|
  | host-necm-1, host-necm-3 | `nECM characterization` | "nECM characterization:" |
  | host-necm-2 | `The nECM: a third player in cell-hydrogel signaling.` | same |
  | host-dup-1 | `Results` | under "Results", subsection "Type I collagen homotrimer is actively produced by Dupuytren's tissue." |
  | host-dup-2, host-dup-3 | `Discussion` | "Discussion" |
  | host-dup-4 | `Introduction` | "Introduction" |
  | host-ce-2 | `Results (in vivo)` | **host label**; the paper's heading was not captured by the reader |
  | host-ce-3 | `Methods (scaffold preparation)` | **host label**; the passage sat after "2.2.1 Preparation of the scaffolds", but the heading of the exact subsection was not confirmed |
- **model_prior**: `prior-gm6001` (GM6001 is broad-spectrum).
- **Not read and not claimed:** how the collagen–elastin study quantified in vitro infiltration;
  any table or figure; the full text of the MRC2, Tpm1.6, CHP and OTR4120 papers (abstracts only).

## Lookups that failed

Two of the eight `research_evidence` calls returned `lookup_failed` (Europe PMC gave no result
envelope); both succeeded on one retry. Before the retry, those searches said nothing about the
literature. One graph finding (`size` → amplicon size, genome-editing seed) was a lexical match
with no bearing on the question and was not used.

## Open items for the researcher

1. Material source, cell type/source, acellular vs cell-loaded — E2 and E4 change shape with it.
2. New-collagen method (radiolabel, azido-proline, enrichment/MS) — facility and regulatory fit.
3. Whether E4 uses an anchored gap or an ex vivo skin-explant defect.
4. Any in vivo step must test immune-mediated degradation separately.
