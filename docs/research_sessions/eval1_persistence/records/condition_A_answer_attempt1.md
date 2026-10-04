# 처리 중단 후 지속되는 표현형: 설명을 구분하는 실험 설계

**System (fixed development assumptions from the pack, not confirmed by any user):** primary human fibroblasts (dermal or lung) on standard tissue-culture plastic; recombinant TGF-β1 at about 2–5 ng/mL for 48–72 h, then washout into TGF-β1-free medium; the phenotype that persists is the myofibroblast state, read as α-SMA incorporated into stress fibres and as contractility, still present days after washout. Donor, passage, serum level, substrate stiffness and the exact day of read-out are **not fixed**, and several conclusions below depend on them.

**Evidence basis.** Only sources S1–S8 of the shared pack are cited, by their span ids. Each comes from another cell type or another inducer (rat cardiac fibroblasts, valvular interstitial cells, CAFs, MSCs, Dupuytren and ILD fibroblasts), so they support *expectations*, not results for this system. Where I rely on general laboratory knowledge that is not in the pack, I mark it **[GK]**. The pack contains **no** source that measures residual exogenous TGF-β1 after washout and **no** source that tests paracrine transfer after washout. Predictions for those two explanations therefore rest on stated assumptions, not on evidence.

---

## 1. 목표 (Goal, restated without narrowing)

After TGF-β1 is removed, the myofibroblast phenotype (stress-fibre α-SMA and contractility) is still present. The goal is to design experiments that find out **which processes keep it present**: residual treatment material, signalling between cells, a persistent change of cell state, **or anything else**. The design should also tell how much each process contributes when more than one is acting, because these are not assumed to exclude each other. This includes the possibility that the "persistence" is not a memory of the treatment at all: it could come from the culture conditions, from slow decay, or from a change in which cells make up the population.

---

## 2. 대안 설명 (Alternative explanations)

Mechanisms are listed here. What would be measured comes in Section 3, kept separate.

| ID | Explanation | Proposed mechanism | Pack support |
|---|---|---|---|
| **E1** | **Residual exogenous TGF-β1** | Recombinant ligand is not removed by washing. It stays adsorbed to plastic, to deposited ECM or carrier/serum proteins, or bound at the cell surface or in internalised receptor complexes, and keeps activating TβRI/SMAD2/3 after washout. | **None.** The pack states that no source measures this. **[GK]** only. |
| **E2** | **Self-sustained TGF-β ligand loop (autocrine, or held in the matrix)** | Induced cells make their own TGF-β1 and/or deposit latent TGF-β (LAP/LTBP-1) in their ECM. Contraction or proteases then activate it, while signal degradation (caveolin-1) is reduced. The ligand is new and comes from the cells, not the original dose. | S6 (`lit-8ccc91bd45f9`, `lit-d4c2a13f46ee`): LAP-TGF-β/LTBP-1 up, plasmin down, and caveolin-1 rescue inhibits myofibroblastogenesis. S7 (`lit-91332fe8e2a5`, `lit-ea0d3890720d`): autocrine TGF-β1 signalling in ILD fibroblasts. |
| **E3** | **Paracrine/juxtacrine signalling by factors other than TGF-β** | Treated cells secrete non-TGF-β factors (for example SASP-like IL-1β or IL-6, or other profibrotic factors **[GK]**), or signal through contact, and this keeps neighbours activated. | S5 (`lit-e62f54ed4087`, `lit-90bac4ae80b3`) shows SASP-like secretion after TGF-β1. The pack does **not** test paracrine transfer. |
| **E4** | **Cell-intrinsic persistent state (chromatin / transcription-factor circuit)** | The pulse remodels chromatin accessibility or lamin–chromatin coupling, or it locks in a self-maintaining TF circuit. The state then needs no further extracellular TGF-β. | S3 (`lit