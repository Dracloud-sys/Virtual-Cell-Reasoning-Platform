"""Revision 2: narrow the parts of revision 1 that said more than the spans read.

Reads `../draft_revised.json` (revision 1, never written) and writes `draft_revised_r2.json` and
`decisions_r2.json`. No new evidence was searched for or read. Every edit is the host's
correction of its own reading, against the spans already in the draft; the comment on each says
which span and which overstatement. Re-running reproduces both files byte for byte.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REVISION_1 = HERE.parent / "draft_revised.json"

OLD_LAP = (
    "Assumption to be tested, not granted: the recombinant TGF-beta1 lot is supplied as mature "
    "active ligand without LAP, so latent TGF-beta1 or LAP found in the medium after washout "
    "was made by the cells."
)
LAP_FREE = (
    "Assumption to be tested, not granted: the recombinant TGF-beta1 lot carries no LAP, so "
    "latent TGF-beta1 or LAP in the medium above arm f did not come from the dose itself."
)
LATENT_ORIGIN = (
    "Latent TGF-beta1 above arm f was secreted by the cells after washout, rather than released "
    "from what the cells or their deposited matrix held from the pulse period. Not tested by "
    "this readout."
)
OLD_PRIOR = "prior-latent-vs-active"
NEW_PRIOR = "prior-latent-form-r2"


def _pred(e1: dict, hypothesis: str, readout: str, condition: str, versus: str) -> dict:
    hits = [
        p
        for p in e1["predictions"]
        if p["hypothesis_id"] == hypothesis
        and p["readout"] == readout
        and p.get("condition") == condition
        and p.get("versus") == versus
    ]
    assert len(hits) == 1, (hypothesis, readout, condition, versus, len(hits))
    return hits[0]


def _link(draft: dict, evidence_id: str, target_id: str) -> dict:
    hits = [
        lk
        for lk in draft["evidence_links"]
        if lk["evidence_id"] == evidence_id and lk["target_id"] == target_id
    ]
    assert len(hits) == 1, (evidence_id, target_id)
    return hits[0]


def build() -> tuple[dict, list[dict]]:
    draft = copy.deepcopy(json.loads(REVISION_1.read_text(encoding="utf-8")))
    e1 = next(e for e in draft["experiments"] if e["id"] == "E1")

    # C1. lit-e60fafae0030 says pSmad2/3 "demonstrated persistent phosphorylation despite
    # removal", with no time points. That is not an observed day-5 vs day-1 no_change, and H2
    # (ligand re-supplied) does not fix whether pSmad2 holds, rises or falls over those days.
    p = _pred(
        e1,
        "H2",
        "pSmad2_nuclear",
        "arm a (vehicle, cells), d5",
        "arm a (vehicle, cells), d1",
    )
    p["expected"] = "not_predicted"
    p["basis"] = "unstated"
    p["evidence_ids"] = []
    p["mechanism_link_ids"] = []
    p["assumptions"] = []
    p["note"] = (
        "The pulse-washout study reports persistent pSmad2/3 after removal (lit-e60fafae0030) "
        "without the time points; that is a persistence observation, not a day-1 vs day-5 "
        "comparison."
    )
    p["unresolved"] = (
        "Under H2 the level over day 1-5 depends on autocrine output against the decay of what "
        "the pulse left; nothing read gives either."
    )

    # C2. A LAP-free dose rules out one origin of latent TGF-beta1 in the medium. It does not
    # say when the latent form was made, whether it came from the cells or their matrix (the
    # plan's own ML8 / H3), whether it is activated, or that it maintains anything.
    draft["assumptions"] = [LAP_FREE if a == OLD_LAP else a for a in draft["assumptions"]]
    for check in e1["assumption_checks"]:
        if check["assumption"] == OLD_LAP:
            check["assumption"] = LAP_FREE
    draft["evidence"] = [ev for ev in draft["evidence"] if ev["id"] != OLD_PRIOR]
    draft["evidence"].append(
        {
            "id": NEW_PRIOR,
            "kind": "model_prior",
            "statement": (
                "Host's general knowledge, not read in any source here: recombinant TGF-beta1 is "
                "commonly supplied as the mature dimer without its latency-associated peptide "
                "(LAP), and cells release TGF-beta1 largely as a latent LAP-bound complex. If the "
                "lot carries no LAP, latent TGF-beta1 or LAP in the medium did not come from the "
                "dose. It would not show when the latent form was made, whether it came from "
                "the cells or from matrix they deposited, whether it was activated, or that it "
                "acts. Replaces prior-latent-vs-active, which said it would mark newly secreted "
                "ligand. A search target: no source for it was returned."
            ),
        }
    )
    vs_free = "arm f (cell-free), d3"
    d3 = "arm a (vehicle, cells), d3"
    h1 = _pred(e1, "H1", "latent_TGFb1_in_CM", d3, vs_free)
    h1["evidence_ids"] = [NEW_PRIOR]
    h1["assumptions"] = [LAP_FREE]
    h2 = _pred(e1, "H2", "latent_TGFb1_in_CM", d3, vs_free)
    h2["evidence_ids"] = [NEW_PRIOR]
    # Kept from revision 1: the prediction still rests on it.
    h2["assumptions"] = [
        LAP_FREE,
        "Newly secreted TGF-beta1 leaves these cells mostly as a latent complex.",
        LATENT_ORIGIN,
    ]
    h2["note"] = (
        "A candidate measurement, not a validated way to tell the source: a rise shows latent "
        "TGF-beta1 from the cells or their matrix, not when it was made, that it was activated, "
        "or that it maintains the phenotype."
    )
    h2["unresolved"] = (
        "Release from the cells' own matrix store (H3, ML8) or from material secreted during the "
        "pulse would give the same rise; a non-TGF-beta1 autocrine mediator would leave it flat "
        "(see E2)."
    )
    h3 = {
        "hypothesis_id": "H3",
        "readout": "latent_TGFb1_in_CM",
        "expected": "not_predicted",
        "condition": d3,
        "versus": vs_free,
        "mechanism_link_ids": ["ML8"],
        "unresolved": (
            "Whether a matrix-held latent pool is released into the medium, rather than activated "
            "in place, is not known from anything read; the cell-free arm has no deposited "
            "matrix, so it does not control for it."
        ),
    }
    e1["predictions"].append(h3)

    branches = e1["branches"]
    branches[1]["implication"] = (
        "Ligand activity beyond what the plastic and medium give back, so carryover on the "
        "plastic alone does not explain it and H1 drops in priority. A rise in latent "
        "TGF-beta1 or LAP over arm f, with the dosing medium free of LAP, says only that a "
        "latent form from the cells or their matrix is present. It does not say it was made "
        "after washout, separate secretion (H2) from matrix release (H3), show activation, or "
        "show it maintains the phenotype; E2 and the plasmin/LTBP arms come next."
    )
    branches[3]["implication"] = (
        "Consistent with signalling being re-supplied, but also with carried-over ligand that is "
        "not cleared or with slow pSmad2 turnover; read it with arm f and the latent readout, "
        "and do not take it as evidence for H2 on its own."
    )
    branches[4]["implication"] = (
        "At that point alpha-SMA stays without pSmad2 at the measured level. Nothing read shows "
        "what holds alpha-SMA without pSmad2: the HA result (ML15) was obtained with pSmad2/3 "
        "still present, so it is not evidence here. H4, H5, H7 and slow alpha-SMA turnover (H8) "
        "all fit this."
    )

    # C3. lit-0650a4586f10: 4-MU / HAS2 siRNA lowered alpha-SMA ("prevented phenotypic
    # activation") while Smad2/3 phosphorylation was unchanged. That shows HA is needed
    # alongside Smad signalling there; it does not show HA holds alpha-SMA with pSmad absent,
    # nor that these experiments were run after TGF-beta1 removal.
    ml15 = next(m for m in draft["mechanism_links"] if m["id"] == "ML15")
    ml15["relation"] = "required_for_with_Smad2/3_phosphorylation_unchanged"
    ml15["target"] = "alpha-SMA expression"
    ml15["conditions"] = [
        "same study and system as ML13",
        "4-methylumbelliferone and HAS2 siRNA lowered alpha-SMA while Smad2/3 phosphorylation "
        "stayed; HA is needed alongside Smad signalling there",
        "not shown: that HA holds alpha-SMA when pSmad2/3 is absent",
        "whether these experiments were during induction or after removal is not stated in "
        "the abstract read",
    ]
    _link(draft, "lit-0650a4586f10", "ML15")["reading"] = (
        "4-MU and HAS2 siRNA lowered alpha-SMA without changing Smad2/3 phosphorylation; the "
        "authors call the HA effect independent of Smad activation. Host: that means HA is "
        "required with pSmad present, not that it substitutes for pSmad."
    )

    # C4. The Sci Rep cells had no TGF-beta1 added by the authors. That is not "no ligand
    # involved": they came from explanted diseased hearts and spent up to 10 passages on
    # plastic in culture medium. The difference is one of origin, induction and culture.
    for eid in ("lit-436033cdfec3", "lit-1ba98dbcd8f3", "lit-758a014077fb"):
        _link(draft, eid, "H4")["reading"] = (
            "Human cardiac fibroblasts from explanted diseased hearts, activated by up to 10 "
            "passages on 3 GPa plastic with no TGF-beta1 pulse added, did not lower alpha-SMA "
            "under SD208, SB431542 (p5-p9) or on 25/2 kPa. Whether endogenous or medium "
            "TGF-beta took part in that activation is not known. A different origin, induction "
            "and culture history; it shows a blockade null can occur without picking H4, not "
            "that ligand was absent."
        )
    _link(draft, "lit-8ad9688ecbdd", "H5")["reading"] = (
        "About 70% of those cells were alpha-SMA-positive on plastic with no TGF-beta added in "
        "that study; the never-treated arm's own baseline on plastic decides how much rise is "
        "measurable."
    )
    p = _pred(
        e1,
        "H4",
        "aSMA_stress_fibre_fraction",
        "arm c (SB431542 continuous), d5",
        "arm a (vehicle), d5",
    )
    p["unresolved"] = (
        "Sources disagree: SD-208 did not reverse the TGF-beta1-induced rat cardiac state "
        "(lit-4003fcca2815), while a fibroblast pulse-washout study reports persistence inhibited "
        "by anti-TGF-beta1 and SB431542 (lit-e60fafae0030, blockade timing not in its abstract). "
        "A null was also reported in chronically activated human cardiac fibroblasts "
        "(lit-758a014077fb), a different origin, induction and culture history, so a null here "
        "does not pick H4 over H5 or H7."
    )
    branches[2]["implication"] = (
        "No ligand route is necessary for maintenance from the time blockade began. This does not "
        "show the state never needed ligand, and does not pick H4: blockade nulls were also "
        "reported in chronically activated human cardiac fibroblasts (different origin and "
        "culture), and a fibroblast pulse-washout study reports the opposite result. E3-E5 "
        "decide among H4, H5 and H7."
    )

    # C5. TGFB1 mRNA alone cannot say where extracellular ligand comes from or whether it acts;
    # that is not the same as carrying no information.
    for hid in ("H1", "H2", "H3"):
        q = _pred(e1, hid, "TGFB1_mRNA_cells", d3, "arm e (never-treated), same day")
        q["note"] = (
            "Predicted alike for H1, H2 and H3, so on its own it does not tell where "
            "extracellular ligand comes from or whether it acts. It still reads whether "
            "signalling-driven transcription continues (H1-H3 against H8), and a flat value "
            "would weigh against transcription-driven autocrine supply, though translation can "
            "change without it (lit-bc7c597aaca4)."
        )

    e1["priority_rationale"] = e1["priority_rationale"].replace(
        "so E1 now measures the latent form and the pSmad2 time course as well.",
        "so E1 adds a latent-form readout as a candidate, with its own dose check, and a pSmad2 "
        "time course.",
    )
    assert "candidate" in e1["priority_rationale"]

    decisions = [
        {
            "target_id": "E1",
            "decision": "revise",
            "reason": (
                "Correction, no new evidence: H2's day-5 vs day-1 pSmad2 value was "
                "not observed and is now not_predicted; the latent readout is a "
                "candidate, its assumptions split into a tested dose check and an "
                "untested origin assumption, H3 added as not_predicted; branches 2-5 "
                "narrowed; mRNA note made specific."
            ),
        },
        {
            "target_id": "ML15",
            "decision": "revise",
            "reason": "Narrowed to what the span shows: HA needed with pSmad2/3 unchanged.",
        },
        {
            "target_id": "H4",
            "decision": "hold",
            "reason": (
                "Still held. The chronically activated human study is read as a different origin "
                "and culture, not as a ligand-free state."
            ),
        },
        {
            "target_id": "H5",
            "decision": "keep",
            "reason": "One reading reworded ('no TGF-beta added in that study'); H5 unchanged.",
        },
    ]
    return draft, decisions


def main() -> None:
    draft, decisions = build()
    for name, payload in (("draft_revised_r2.json", draft), ("decisions_r2.json", decisions)):
        (HERE / name).write_text(
            json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
