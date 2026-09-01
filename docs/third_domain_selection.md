# Choosing the third domain

Two verticals can share an abstraction by coincidence — the second was written by people who
had just read the first. A third domain is where the `DomainPack` boundary and the reasoning
kernel are actually tested, so the choice matters more than the implementation: pick a domain
whose *decision shape* resembles the first two and the test proves nothing.

## What the first two already are

| | question it answers | shape |
|---|---|---|
| immortalization | *is this line a candidate?* | **prospective** — will this behaviour continue |
| adipogenesis | *did the program run to completion?* | **process completion** — how far along is it |

Both judge a **cell state** from marker readings. A third that also judges a cell state from
marker readings would exercise nothing new.

## Candidates

### A. Myogenic differentiation — rejected

The obvious next vertical for cultured meat, and the worst possible test. PAX7/MYOD/MYOG plus
a fusion index is adipogenesis with the nouns changed: commitment program, functional readout,
same "a marker panel is not a myotube" rule. It would pass on day one and prove only that the
kernel supports the domain it was extracted from twice.

Rejected precisely *because* it would succeed easily.

### B. Mycoplasma contamination — strong, not chosen

A genuinely third shape: a **validity** question rather than a state question — *is a confounder
present that invalidates my other results?* It also carries a reasoning pattern neither existing
vertical has: the meaning of a negative depends on context (a negative PCR from an
antibiotic-treated culture is nearly uninformative).

Not chosen for two reasons. Its mechanism graph is thin — contamination biology does not give
much to ground evidence-graded chains on. And its most interesting edge, that mycoplasma
depresses proliferation, **couples it to the immortalization vertical's own PDL/DT readings**.
A third domain that entangles with the first is a worse generality test, not a better one.

Worth revisiting as a fourth domain, where the coupling becomes a feature.

### C. Genome-edit validation — **chosen**

*Does this clone carry the edit I intended, and can I use it?*

| criterion | how it lands |
|---|---|
| not a clone of either | judges a **molecular claim about a construct**, not a phenotype |
| status vs guidance | edit/assay/clonality decide; off-target breadth and protein expression refine |
| measured-negative vs unmeasured | *"negative at three predicted off-target sites"* is not *"no off-targets"* |
| mechanism reasoning | Cas9 → DSB → NHEJ/HDR → indel/knock-in → loss or gain of function |
| small seed graph | ~20 nodes, entirely disjoint from both existing graphs |
| real decision | the gate every edited line passes before anyone uses it |
| tests the kernel | see below |

It also completes a coherent product story rather than adding a random vertical: **immortalize
the line → edit it → differentiate it**. Three stages of one workflow, three different decision
shapes.

#### The reason it tests the kernel hardest

The other two domains read a value and ask what it means. This one must read **how the value
was measured** before it can say what it means:

```
PCR band              →  a band is not a genotype
Sanger / NGS + alleles →  a genotype
```

A negative from PCR is weak evidence of absence; a negative from NGS is a real finding. Neither
existing vertical has any notion that evidence strength varies by instrument. That is the
sharpest available probe for whether `measurement_claim` / `interpretation_claim` and the tier
conventions generalise, or whether they quietly assume every reading is equally strong.

**Headline rule: a band is not a genotype.** The structural sibling of *"a marker panel is not
a fat cell"* and *"sustained proliferation is not immortalization"*, arrived at from a
completely different direction.

#### The safety boundary it must hold

A confirmed DNA edit says nothing about protein function, and three clean off-target sites say
nothing about the genome. So there is no `functional_knockout` status and no `off_target_free`
status — both are the overclaim this vertical exists to refuse.

## Rule for this milestone

If the third domain needs a kernel change, that change is **not** implemented here. It is
recorded as a discovered abstraction gap, because a kernel bent to fit its third caller on
first contact has not been validated — it has been widened until the test passed.
