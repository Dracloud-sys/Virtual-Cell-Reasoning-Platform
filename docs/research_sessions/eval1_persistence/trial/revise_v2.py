"""Apply the structural (input) fixes from check_v1_compact.json to draft_v1.json.

Only input-kind finding groups are addressed:
  1. unsupported_evidence_link / hypotheses[].supporting_evidence_ids  (H2..H6)
  2. unknown_hypothesis_id / experiments[].discriminates                (E1..E6)
Plus one "review" item where the assumption text is already stated in the draft
for the same hypothesis, experiment and readout logic (E4:H1:GATA6_protein).

No biology is altered: statements, expected values, evidence, evidence_links
roles, mechanism links and experiment designs are untouched.
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = HERE.parent / "records" / "condition_B_payload_1.json"  # draft_v1.json as run
dst = HERE / "draft_v2.json"

draft = json.loads(src.read_text(encoding="utf-8"))

hyp_ids = [h["id"] for h in draft["hypotheses"]]
hyp_id_set = set(hyp_ids)
evidence_kinds = {e["id"]: e["kind"] for e in draft.get("evidence") or []}

# --- Fix 1: supporting_evidence_ids, derived strictly from evidence_links -----
supports = {}
for link in draft.get("evidence_links") or []:
    if link.get("role") != "supports":
        continue
    target = link.get("target_id")
    if target not in hyp_id_set:
        continue  # mechanism-link targets are not hypotheses
    supports.setdefault(target, [])
    eid = link.get("evidence_id")
    if eid not in supports[target]:
        supports[target].append(eid)

FLAGGED = {"H2", "H3", "H4", "H5", "H6"}  # the ids the result named
for h in draft["hypotheses"]:
    if h["id"] not in FLAGGED:
        continue
    ids = [
        e
        for e in supports.get(h["id"], [])
        if evidence_kinds.get(e) in ("user_observation", "retrieved_source")
    ]
    assert ids, h["id"]
    h["supporting_evidence_ids"] = ids

# --- Fix 2: discriminates must be hypothesis ids, one per entry --------------
PAIR = re.compile(r"^\s*(H\d+)\s+vs\s+(H\d+)\s*$")
for exp in draft.get("experiments") or []:
    out = []
    for entry in exp.get("discriminates") or []:
        if entry in hyp_id_set:
            cand = [entry]
        else:
            m = PAIR.match(entry)
            assert m, (exp["id"], entry)
            cand = [m.group(1), m.group(2)]
        for c in cand:
            assert c in hyp_id_set, (exp["id"], c)
            if c not in out:
                out.append(c)
    exp["discriminates"] = out

# --- Fix 3: one review item, using text already in the draft -----------------
# E4/H1 already states, for the same soft-gel condition, that ligand carried on
# the cells is indifferent to the substrate; the GATA6_protein no_change
# prediction in the same experiment rests on that same stated assumption.
SOURCE = ("E4", "H1", "aSMA_on_substrate")
TARGET = ("E4", "H1", "GATA6_protein")
text = None
for exp in draft["experiments"]:
    if exp["id"] != SOURCE[0]:
        continue
    for p in exp.get("predictions") or []:
        if (p.get("hypothesis_id"), p.get("readout")) == (SOURCE[1], SOURCE[2]):
            assumptions = p.get("assumptions") or []
            assert len(assumptions) == 1, assumptions
            text = assumptions[0]
assert text
applied = 0
for exp in draft["experiments"]:
    if exp["id"] != TARGET[0]:
        continue
    for p in exp.get("predictions") or []:
        if (p.get("hypothesis_id"), p.get("readout")) == (TARGET[1], TARGET[2]):
            assert not p.get("assumptions")
            p["assumptions"] = [text]
            applied += 1
assert applied == 1

assert "view" not in draft
dst.write_text(json.dumps(draft, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", dst)
