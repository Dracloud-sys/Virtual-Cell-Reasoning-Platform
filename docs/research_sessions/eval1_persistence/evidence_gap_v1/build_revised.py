"""Build the revised draft from the original, changing only what the new evidence bears on.

Reads `records/condition_B_payload_2.json` (the original plan, never written) and
`new_evidence.json` (the spans read in this case, byte-for-byte as the server issued them),
and writes `draft_revised.json` and `decisions.json`. Every edit below is the host's; the
comment on each says which span it rests on. Re-running reproduces both files byte for byte.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "records" / "condition_B_payload_2.json"

WEBBER = ["lit-e60fafae0030", "lit-0650a4586f10"]  # JBC 2009, abstract only
AUTOINDUCTION = ["lit-fcd84996ed09", "lit-bc7c597aaca4"]  # Am J Pathol 2006, abstract only
HCF_BLOCK = ["lit-436033cdfec3", "lit-1ba98dbcd8f3", "lit-758a014077fb"]  # Sci Rep 2023, results
HCF_SETUP = ["lit-2f2b31039dc0", "lit-8ad9688ecbdd"]  # same paper, Sec. "Long-term culture"
HCF_DOSES = "lit-a0b6b0ba4b51"  # same paper, "In vitro treatments"
PRIOR_LAP = "prior-latent-vs-active"

LAP_ASSUMPTION = (
    "Assumption to be tested, not granted: the recombinant TGF-beta1 lot is supplied as mature "
    "active ligand without LAP, so latent TGF-beta1 or LAP found in the medium after washout "
    "was made by the cells."
)
RESIDUAL_SEARCHED = (
    "Searched on 2026-10-04 (research_evidence, searches 1 and 4 of 4) for a source measuring "
    "residual exogenous TGF-beta1 after washout; none was returned. Every residual-ligand "
    "expectation is still assumption, not evidence."
)


def _pred(e1: dict, hypothesis: str, readout: str, condition: str) -> dict:
    hits = [
        p
        for p in e1["predictions"]
        if p["hypothesis_id"] == hypothesis
        and p["readout"] == readout
        and p.get("condition") == condition
    ]
    assert len(hits) == 1, (hypothesis, readout, condition, len(hits))
    return hits[0]


def build() -> tuple[dict, list[dict]]:
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    draft = copy.deepcopy(prior)
    draft["evidence"] += json.loads((HERE / "new_evidence.json").read_text(encoding="utf-8"))

    hyp = {h["id"]: h for h in draft["hypotheses"]}
    # H2: the pulse-washout study reports persistence its authors attribute to autocrine
    # TGF-beta1. Abstract only: cell source, washout and how carryover was excluded are unread.
    hyp["H2"]["supporting_evidence_ids"] += WEBBER[:1]
    # H4: the same study reports persistence inhibited by anti-TGF-beta1 and SB431542, the
    # opposite of what H4 needs, in a pulse system. Recorded as contradicting, not as refuting.
    hyp["H4"].setdefault("contradicting_evidence_ids", []).append(WEBBER[0])

    draft["evidence_links"] += [
        {
            "evidence_id": WEBBER[0],
            "target_id": "H2",
            "role": "supports",
            "reading": (
                "Fibroblasts given 10 ng/mL TGF-beta1 for 72 h kept the phenotype up to 120 h "
                "after removal, with persistent pSmad2/3 that the authors attribute to autocrine "
                "TGF-beta1. Abstract only: cell source and species, the washout, how carried-over "
                "ligand was excluded and how synthesis was measured are not stated there."
            ),
        },
        {
            "evidence_id": WEBBER[0],
            "target_id": "H1",
            "role": "scope_limit",
            "reading": (
                "Inhibition by anti-TGF-beta1 antibody and SB431542 cannot tell carried-over from "
                "newly made ligand: both act through the same receptor. Whatever excluded "
                "carryover in that study is in its methods, which were not read."
            ),
        },
        {
            "evidence_id": WEBBER[0],
            "target_id": "H4",
            "role": "contradicts",
            "reading": (
                "In a pulse-and-removal system, persistence was inhibited by ligand and receptor "
                "blockade. When blockade started is not in the abstract."
            ),
        },
        {
            "evidence_id": WEBBER[1],
            "target_id": "ML15",
            "role": "supports",
            "reading": (
                "4-MU and HAS2 siRNA lowered alpha-SMA without changing Smad2/3 phosphorylation; "
                "the authors read HA as a mediator independent of Smad activation."
            ),
        },
        {
            "evidence_id": AUTOINDUCTION[0],
            "target_id": "ML14",
            "role": "supports",
            "reading": (
                "Added TGF-beta1 raised TGF-beta1 mRNA and de novo protein synthesis in PTCs."
            ),
        },
        {
            "evidence_id": AUTOINDUCTION[0],
            "target_id": "H1",
            "role": "method",
            "reading": (
                "If ongoing TGF-beta signalling raises TGFB1 mRNA whatever the ligand's source, a "
                "TGFB1 mRNA rise after washout does not tell carryover (H1) from autocrine (H2). "
                "Shown in epithelial cells, not fibroblasts."
            ),
        },
        {
            "evidence_id": AUTOINDUCTION[1],
            "target_id": "ML14",
            "role": "method",
            "reading": (
                "p38 controlled de novo protein synthesis without changing mRNA, so mRNA alone can "
                "miss a change in secreted ligand; measure the protein in the medium as well."
            ),
        },
        *[
            {
                "evidence_id": eid,
                "target_id": "H4",
                "role": "scope_limit",
                "reading": (
                    "Diseased human cardiac fibroblasts chronically activated on plastic (not a "
                    "TGF-beta1 pulse) did not lower alpha-SMA under SD208, SB431542 (p5-p9) or on "
                    "25/2 kPa. Non-reversal under blockade also arises in a state no ligand "
                    "established, so arm c 'no change' does not pick H4 on its own."
                ),
            }
            for eid in HCF_BLOCK
        ],
        {
            "evidence_id": HCF_BLOCK[0],
            "target_id": "H5",
            "role": "scope_limit",
            "reading": (
                "In that chronically activated system, 25 and 2 kPa did not lower alpha-SMA; a "
                "soft-substrate null there is not about a fresh pulse on plastic."
            ),
        },
        {
            "evidence_id": HCF_SETUP[1],
            "target_id": "H5",
            "role": "method",
            "reading": (
                "About 70% of those cells were alpha-SMA-positive on plastic before any TGF-beta; "
                "the never-treated arm's own baseline on plastic decides how much rise is "
                "measurable."
            ),
        },
        {
            "evidence_id": HCF_SETUP[0],
            "target_id": "H5",
            "role": "scope_limit",
            "reading": (
                "That baseline came from up to 10 passages on 3 GPa polystyrene, from explanted "
                "diseased hearts; it is not the plan's passage 3-5 cells."
            ),
        },
        {
            "evidence_id": HCF_DOSES,
            "target_id": "H4",
            "role": "method",
            "reading": "SB431542 at 10 uM, the same concentration as the plan's arm c.",
        },
    ]

    draft["mechanism_links"] += [
        {
            "id": "ML13",
            "source": "autocrine TGF-beta1 made by the treated fibroblasts",
            "relation": "sustains_after_exogenous_removal",
            "target": "Smad2/3 phosphorylation and the myofibroblast phenotype",
            "evidence_ids": WEBBER[:1],
            "hypothesis_ids": ["H2"],
            "conditions": [
                "fibroblasts, 10 ng/mL TGF-beta1 for 72 h, then removal; up to 120 h observed",
                "cell source, species and washout are not stated in the abstract read",
                "autocrine origin is the authors' interpretation; the methods were not read",
            ],
        },
        {
            "id": "ML14",
            "source": "TGF-beta1 signalling (Smad3 and ERK for mRNA; p38 for translation)",
            "relation": "increases",
            "target": "TGF-beta1 mRNA and de novo TGF-beta1 protein (autoinduction)",
            "evidence_ids": AUTOINDUCTION,
            "hypothesis_ids": ["H1", "H2", "H3"],
            "conditions": [
                "proximal tubular epithelial cells, not fibroblasts",
                "exogenous TGF-beta1 added; dose and time not in the abstract",
            ],
        },
        {
            "id": "ML15",
            "source": "HAS2-dependent hyaluronan pericellular coat",
            "relation": "required_for_independently_of_Smad_phosphorylation",
            "target": "alpha-SMA after TGF-beta1 removal",
            "evidence_ids": WEBBER[1:],
            "hypothesis_ids": ["H2"],
            "conditions": [
                "same study and conditions as ML13",
                "4-methylumbelliferone and HAS2 siRNA; authors' interpretation in the abstract",
            ],
        },
    ]

    e1 = next(e for e in draft["experiments"] if e["id"] == "E1")
    e1["measurements"] += ["TGFB1_mRNA_cells", "latent_TGFb1_in_CM"]
    e1["readouts"] += [
        {
            "name": "TGFB1_mRNA_cells",
            "target": "TGFB1 transcript in the cells",
            "assay": "RT-qPCR",
            "compartment": "cells",
            "timepoint": "day 1, day 3, day 5 after washout",
            "unit": "relative expression",
            "normalization": "two reference genes, per donor",
            "reference": "never-treated cells harvested the same day (arm e)",
        },
        {
            "name": "latent_TGFb1_in_CM",
            "target": (
                "TGF-beta1 that needs activation to be measured (acid-activated minus native), "
                "with LAP measured on the same samples"
            ),
            "assay": "TGF-beta1 ELISA on native and acid-activated medium; LAP (TGF-beta1) ELISA",
            "compartment": "conditioned medium",
            "timepoint": "day 1, day 3, day 5 after washout",
            "unit": "pg/mL",
            "normalization": "per mL of medium and per 10^5 cells at harvest",
            "reference": "cell-free pulsed-and-washed wells (arm f), and the dosing medium",
        },
    ]
    e1["controls"].append(
        "The dosing medium and the cell-free arm f assayed for LAP and latent TGF-beta1, to test "
        "that the recombinant lot carries none."
    )
    e1["assumption_checks"].append(
        {
            "assumption": LAP_ASSUMPTION,
            "readout": "latent_TGFb1_in_CM",
            "expected_if_holds": "absent",
        }
    )

    d3 = "arm a (vehicle, cells), d3"
    never = "arm e (never-treated), same day"
    mrna = "TGFB1_mRNA_cells"
    for hid in ("H1", "H2", "H3"):
        e1["predictions"].append(
            {
                "hypothesis_id": hid,
                "readout": mrna,
                "expected": "increase",
                "condition": d3,
                "versus": never,
                "basis": "mechanism_derived",
                "evidence_ids": AUTOINDUCTION[:1],
                "mechanism_link_ids": ["ML14"],
                "assumptions": [
                    "TGF-beta1 autoinduction shown in epithelial cells also runs in these "
                    "fibroblasts, whatever the ligand's source."
                ],
                "note": "Predicted alike for H1, H2 and H3: this readout does not tell them apart.",
            }
        )
    e1["predictions"].append(
        {
            "hypothesis_id": "H8",
            "readout": mrna,
            "expected": "no_change",
            "condition": d3,
            "versus": never,
            "basis": "assumption",
            "assumptions": ["Nothing is signalling; only slowly turning-over protein remains."],
        }
    )
    vs_free = "arm f (cell-free), d3"
    e1["predictions"] += [
        {
            "hypothesis_id": "H1",
            "readout": "latent_TGFb1_in_CM",
            "expected": "no_change",
            "condition": d3,
            "versus": vs_free,
            "basis": "assumption",
            "evidence_ids": [PRIOR_LAP],
            "mechanism_link_ids": ["ML11"],
            "assumptions": [LAP_ASSUMPTION],
            "unresolved": (
                "Carried-over active ligand adds no latent complex only if the lot carries no "
                "LAP; the dosing-medium check decides it."
            ),
        },
        {
            "hypothesis_id": "H2",
            "readout": "latent_TGFb1_in_CM",
            "expected": "increase",
            "condition": d3,
            "versus": vs_free,
            "basis": "assumption",
            "evidence_ids": [PRIOR_LAP, WEBBER[0]],
            "mechanism_link_ids": ["ML13"],
            "assumptions": [
                LAP_ASSUMPTION,
                "Newly secreted TGF-beta1 leaves these cells mostly as a latent complex.",
            ],
            "unresolved": "If the autocrine mediator is not TGF-beta1, this stays flat (see E2).",
        },
    ]
    e1["predictions"] += [
        {
            "hypothesis_id": "H1",
            "readout": "pSmad2_nuclear",
            "expected": "decrease",
            "condition": "arm a (vehicle, cells), d5",
            "versus": "arm a (vehicle, cells), d1",
            "basis": "assumption",
            "mechanism_link_ids": ["ML11"],
            "assumptions": ["Carried-over ligand is used up or cleared and nothing replaces it."],
        },
        {
            "hypothesis_id": "H2",
            "readout": "pSmad2_nuclear",
            "expected": "no_change",
            "condition": "arm a (vehicle, cells), d5",
            "versus": "arm a (vehicle, cells), d1",
            "basis": "evidence_observed",
            "evidence_ids": WEBBER[:1],
            "mechanism_link_ids": ["ML13"],
            "assumptions": [
                "The persistent pSmad2/3 reported after removal in that study, at time points "
                "its abstract does not give, holds over day 1 to day 5 here."
            ],
        },
    ]
    # H2's day-3 pSmad2 prediction keeps its value; it now also cites the pulse-washout study.
    p = _pred(e1, "H2", "pSmad2_nuclear", d3)
    p["evidence_ids"] = p.get("evidence_ids", []) + WEBBER[:1]
    p["mechanism_link_ids"] = p.get("mechanism_link_ids", []) + ["ML13"]
    # H4 under continuous SB431542: the value follows from H4's own statement and is kept. The
    # sources now disagree on whether blockade reverses a TGF-beta1-induced state, so the
    # reading is held rather than changed.
    p = _pred(e1, "H4", "aSMA_stress_fibre_fraction", "arm c (SB431542 continuous), d5")
    p["unresolved"] = (
        "Sources disagree: SD-208 did not reverse the TGF-beta1-induced rat cardiac state "
        "(lit-4003fcca2815), while a fibroblast pulse-washout study reports persistence inhibited "
        "by anti-TGF-beta1 and SB431542 (lit-e60fafae0030, blockade timing not in its abstract). "
        "A null here is also what a chronically activated human state shows (lit-758a014077fb), "
        "so it does not pick H4 over H5 or H7."
    )

    branches = e1["branches"]
    branches[1]["implication"] = (
        "Cell- or matrix-derived ligand (H2/H3) rather than carryover, and H1 drops in priority. "
        "Only a rise in latent TGF-beta1 or LAP over arm f says the ligand was newly secreted "
        "(H2), and only if the dosing medium carries none; a rise in active ligand alone does not "
        "separate secretion from local activation of a stored pool (H3). E2 and the plasmin/LTBP "
        "arms come next."
    )
    branches[2]["implication"] = (
        "No ligand route is necessary for maintenance from the time blockade began. This does not "
        "show the state never needed ligand, and does not pick H4: chronically activated human "
        "cardiac myofibroblasts also stay alpha-SMA-positive under blockade, and a fibroblast "
        "pulse-washout study reports the opposite result. E3-E5 decide among H4, H5 and H7."
    )
    branches += [
        {
            "outcome": (
                "pSmad2 stays at its day-1 level through day 5 while the cell-free wells are at "
                "the floor."
            ),
            "implication": (
                "Signalling is being re-supplied, which carryover alone does not do; read it with "
                "latent TGF-beta1 to tell secretion (H2) from local activation (H3)."
            ),
        },
        {
            "outcome": "pSmad2 falls to never-treated by day 5; alpha-SMA stress fibres persist.",
            "implication": (
                "Maintenance does not need ongoing Smad2 phosphorylation at that point. Do not "
                "read this as H4 alone: the HA coat was reported to hold alpha-SMA independently "
                "of Smad phosphorylation (ML15), and H5 and H7 also predict it."
            ),
        },
    ]
    e1["priority_rationale"] += (
        " After reading: a fibroblast pulse-washout study reports persistence with ongoing "
        "pSmad2/3 attributed to autocrine TGF-beta1, so whether the ligand after washout is "
        "carried over or newly made decides how every later blockade result is read. "
        "Blockade cannot tell the two apart, and TGFB1 mRNA may not either "
        "(autoinduction), so E1 now measures the latent form and the pSmad2 time course "
        "as well."
    )

    draft["assumptions"].append(RESIDUAL_SEARCHED)
    draft["assumptions"].append(LAP_ASSUMPTION)
    draft["open_items"] = draft.get("open_items", []) + [
        "Read the methods of Webber et al. 2009 (doi 10.1074/jbc.M806989200): cell source, "
        "washout, how carryover was excluded, how synthesis was measured and when blockade began. "
        "Neither this server nor the PubMed full-text tool returned the body.",
        "Find a source on whether the recombinant TGF-beta1 lot carries LAP, or measure it (the "
        "dosing-medium check in E1).",
    ]

    decisions = [
        {
            "target_id": "H1",
            "decision": "unchanged_no_new_evidence",
            "reason": (
                "No source measuring residual exogenous TGF-beta1 after washout was returned in 4 "
                "searches. H1 stays an unverified candidate; what changed is how E1 reads it."
            ),
        },
        {
            "target_id": "ML11",
            "decision": "unchanged_no_new_evidence",
            "reason": "Still no source; the link keeps carrying no evidence id, on purpose.",
        },
        {
            "target_id": "H2",
            "decision": "keep",
            "reason": (
                "A pulse-washout study now stands behind it, at abstract level and with the "
                "carryover question unread."
            ),
            "evidence_ids": WEBBER[:1],
        },
        {
            "target_id": "H4",
            "decision": "hold",
            "reason": (
                "Contradicting and scope-limiting sources were added; the prediction values stay, "
                "and a blockade null is no longer read as picking H4."
            ),
            "evidence_ids": [WEBBER[0], *HCF_BLOCK],
        },
        {
            "target_id": "H5",
            "decision": "keep",
            "reason": "E4 still tests it; the new spans limit where one null applies.",
            "evidence_ids": [HCF_BLOCK[0], HCF_SETUP[1]],
        },
        {
            "target_id": "E1",
            "decision": "revise",
            "reason": (
                "Adds the latent TGF-beta1/LAP readout with its LAP-free check, TGFB1 mRNA "
                "(predicted equal for H1-H3, so not a source marker), a day-1 to day-5 pSmad2 "
                "comparison, and rewrites branches 2 and 3."
            ),
            "evidence_ids": [*WEBBER, *AUTOINDUCTION, *HCF_BLOCK],
        },
        {
            "target_id": "ML13",
            "decision": "revise",
            "reason": "New case-local link for the pulse-washout autocrine reading.",
            "evidence_ids": WEBBER[:1],
        },
        {
            "target_id": "ML14",
            "decision": "revise",
            "reason": "New case-local link: autoinduction, epithelial cells.",
            "evidence_ids": AUTOINDUCTION,
        },
        {
            "target_id": "ML15",
            "decision": "revise",
            "reason": "New case-local link: HA coat independent of Smad phosphorylation.",
            "evidence_ids": WEBBER[1:],
        },
    ]
    return draft, decisions


def main() -> None:
    draft, decisions = build()
    for name, payload in (("draft_revised.json", draft), ("decisions.json", decisions)):
        (HERE / name).write_text(
            json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
