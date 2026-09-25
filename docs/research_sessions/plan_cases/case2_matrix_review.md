# Case 2: the full H1/H2a/H2b/H3a/H3b matrix, reviewed cell by cell

`case2_draft.json` is kept exactly as submitted. This review is the host's. Its corrected
version is `case2_revised_draft.json`. No new literature was read for this review. Each cell
below is judged only against three things: the hypothesis as written, the readout as written,
and the evidence already in the draft.

**What each verdict means.**
- **kept**: the cell follows from the hypothesis and the readout.
- **corrected**: the cell was wrong in kind, direction or reference.
- **unconfirmed**: the cell asserted a value the hypothesis does not fix. It now reads
  `not_predicted`, with what would decide it in `unresolved`.

A cell that holds only under an assumption about another assay is kept. Its basis is changed
to `assumption` and the assumption is written down. Interference on one assay is never assumed
to carry over to another assay, and never assumed not to.

## The claim under review

`README.md`, case 2 said: *"General answer's experiments (cell-free resazurin, per-cell
normalisation, ATP/membrane, mitochondrial content/OCR): H3b is never separated from H2a or H2b.
A compound that quenches resorufin would read as lower metabolic activity per cell in every one
of them."*

The second sentence is **wrong**. ATP, membrane integrity, citrate synthase and OCR do not read
resorufin. The first sentence was computed correctly from the matrix, but it came from three
defects in the matrix, not from the biology:

1. E5 carried **no H3b prediction at all**, so code had nothing to compare.
2. The H3b cell for ATP was `not_predicted`. Its only support was that luminometric readouts were
   affected by *graphene* (`lit-8e6cd61795a6`). That generalises interference across assays and
   across compound classes.
3. The H2a/H2b cells for ATP said `decrease`. Neither hypothesis fixes that, because glycolysis
   can hold ATP up.

## E1: resazurin + compound, no cells

The original readout was "cell-free resorufin formation change" with `present`/`absent`. That
states a **change** as a **state**, with no reference. It is corrected to "fluorescence vs
resazurin in medium alone" (a change).

| hyp | original | verdict | revised | why |
|---|---|---|---|---|
| H3a | present | **unconfirmed** | not_predicted | H3a is "reacts directly". A reducing compound raises cell-free fluorescence. One that over-reduces resorufin, or consumes resazurin, lowers it. The hypothesis does not fix the direction. |
| H3b | absent | **unconfirmed** | not_predicted | Resazurin stocks and medium carry some resorufin background. If there is enough, a quencher lowers this reading. Whether there is enough is not known. |
| H1, H2a, H2b | absent | **corrected** (kind) | no_change vs resazurin alone | No cells, so no biology. Basis: measurement model. |

**Found:** the Expectation vocabulary cannot say "changes, direction unknown". H3a's real
prediction here is exactly that. It is recorded as a finding, not fixed (see README).

## E2: resorufin ± compound, no cells

The original readout was "resorufin fluorescence loss with compound" with `present`/`absent`.
Again a change stated as a state. It is corrected to "resorufin fluorescence vs resorufin
alone".

| hyp | original | verdict | revised | why |
|---|---|---|---|---|
| H3b | present | **corrected** (kind) | decrease | Quenching or adsorption lowers measured resorufin. Basis: evidence observed for graphene (`lit-fd67cab1bedc`, `lit-d1719f786da7`), a scope limit for other compounds. |
| H3a | not_predicted | kept | not_predicted | Over-reduction lowers it; otherwise no change. |
| H1, H2a, H2b | absent | **corrected** (kind) | no_change | No cells. |

## E3: same-well DNA count + resazurin per cell

| hyp | readout | original | verdict | why |
|---|---|---|---|---|
| H1 | cell number | decrease | kept | |
| H2a, H2b | cell number | no_change | kept | As written, H2 changes activity per cell, not cell number. |
| H3a, H3b | cell number | no_change | kept, **basis now assumption** | Holds only if the compound does not also interfere with the DNA dye. That dye is also fluorescent, and no control in the plan checks it. |
| H1 | signal per cell | no_change | kept | |
| H2a, H2b, H3a, H3b | signal per cell | decrease | kept | This is why E3 cannot separate H2 from H3. |

## E4: membrane integrity and ATP per cell

| hyp | readout | original | verdict | why |
|---|---|---|---|---|
| H1 | membrane-compromised fraction | increase ("if loss is by death") | **unconfirmed** | H1 is "death **or arrest**". Arrest predicts no change. The note admitted the disjunction; the value hid it. |
| H2a, H2b | membrane | no_change | kept | |
| H3a, H3b | membrane | no_change | kept, **basis now assumption** | Only if the membrane readout is not resorufin-coupled. Common LDH-release kits read LDH through a diaphorase/resazurin → resorufin step, and on those H3b would *lower* apparent LDH. The readout spec now names a non-resorufin readout. |
| H1 | ATP per cell | no_change | kept, basis assumption | Dying or arrested cells can have lower ATP. Kept as an assumption. |
| H2a, H2b | ATP per cell | decrease | **unconfirmed** | Less mitochondrial content or function lowers ATP only if glycolysis does not compensate. That is not known for these cells or this medium. |
| H3a | ATP per cell | no_change | kept, basis assumption | |
| H3b | ATP per cell | not_predicted | **corrected** | H3b as written is about resorufin. With biology intact, ATP per cell is unchanged, *provided* luciferase is not affected. That provision is an assumption, and a cell-free ATP + compound check would test it. The graphene luminometry result is a scope limit, not a prediction for this compound. |

## E5: citrate synthase content and OCR per content

| hyp | readout | original | verdict | why |
|---|---|---|---|---|
| H2a | content per cell | decrease | kept | |
| H2b, H1 | content per cell | no_change | kept | |
| H3a, H3b | content per cell | *(absent)* | **added**: no_change, basis assumption | Biology intact. Assumes the citrate synthase assay (DTNB absorbance) is not affected by the compound. |
| H2a | OCR per content | no_change | kept | |
| H2b | OCR per content | decrease | **unconfirmed** | H2b is "per mitochondrion **or of other reductases**". If the lost reductase activity is outside mitochondria, OCR per content does not move. |
| H1 | OCR per content | no_change | kept | |
| H3a, H3b | OCR per content | *(absent)* | **added**: no_change, basis assumption | Assumes the oxygen sensor is not affected. Plate-based OCR uses a fluorescent oxygen probe, so this is a real assumption. |

## What the corrected matrix says about the claim

Computed on the revised draft restricted to the general answer's experiments (E1, E3, E4, E5;
`case2_revised_draft_general_experiments_result.json`):

- **H3b vs H2a is separated** by E5 citrate synthase content (H2a decrease, H3b no change). It
  rests on an unchecked assumption, that the compound does not affect the citrate synthase
  assay.
- **H3b vs H2b is not separated.** After the correction, H2b's OCR cell is `not_predicted`, so no
  general-answer readout differs by value.
- E2 still separates H3b from H1, H2a and H2b directly, with no assumption about any other
  assay.

**The finding changes.** It was "H3b is never separated from H2a or H2b". It is now "H3b is
separated from H2a only through an assumption about the citrate synthase assay, and is not
separated from H2b". The reason given for it, "quenching would read as lower activity in every
one", is withdrawn. E2 remains the one experiment that tests H3b without assuming anything about
a second assay. It is not ranked first here for that reason alone. Which experiment runs first
is argued in the README and decided by the researcher.
