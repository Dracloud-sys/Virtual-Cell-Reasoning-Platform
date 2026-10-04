#!/usr/bin/env python3
"""Make ONE revision to the stored draft, fixing only the 'input'-kind findings.

Fixes applied (both marked kind "input" by check_1):
  1. unsupported_evidence_link (hypotheses[].supporting_evidence_ids):
     For H2,H3,H4,H5,H6 the draft declares support=evidence_linked but
     supporting_evidence_ids is empty. We populate it ONLY with ids that the
     draft's own evidence_links already link to that hypothesis with role
     "supports". No invented ids; no role other than "supports" is used.
  2. unknown_hypothesis_id (experiments[].discriminates):
     Each entry is a pair string like "H1 vs H2". The schema wants one
     hypothesis id per entry. We split every "Hx vs Hy" into its ids and keep
     the unique ids per experiment in first-appearance order. This is the
     host's edit (recorded in notes.md).

NOT fixed (kind "review", left as-is):
  - assumption_without_stated_assumptions on E2:H1:aSMA_in_naive_recipient,
    E3:H1:clonal_bimodality, E4:H1:GATA6_protein. Fixing would require
    inventing assumption text, which the rules forbid.

Nothing else is touched: hypothesis statements, predicted values, bases,
evidence, evidence_links roles, mechanism links, designs and what_if are
left byte-for-byte as stored.
"""

import copy
import json
import re
from pathlib import Path

# As run, SRC and OUT were absolute paths in the session; stored here relative to this file.
HERE = Path(__file__).resolve().parent

SRC = HERE.parent / "records" / "condition_B_payload_1.json"
OUT = HERE / "draft_v2.json"

with open(SRC) as f:
    draft = json.load(f)
d = copy.deepcopy(draft)

# ---- Fix 1: supporting_evidence_ids from evidence_links role="supports" ----
# Build map hypothesis_id -> ordered unique evidence ids with role "supports".
supports = {}
for link in d.get("evidence_links", []):
    if link.get("role") == "supports":
        tgt = link["target_id"]
        supports.setdefault(tgt, [])
        if link["evidence_id"] not in supports[tgt]:
            supports[tgt].append(link["evidence_id"])

TO_FIX = {"H2", "H3", "H4", "H5", "H6"}  # exactly the hypotheses flagged kind=input
fix1_log = {}
for h in d["hypotheses"]:
    if h["id"] in TO_FIX:
        existing = h.get("supporting_evidence_ids", [])
        assert not existing, f"{h['id']} already had supporting ids: {existing}"
        ids = supports.get(h["id"], [])
        assert ids, f"no supports-role evidence_links for {h['id']}"
        h["supporting_evidence_ids"] = ids
        fix1_log[h["id"]] = ids

# ---- Fix 2: split discriminates pair strings into unique hypothesis ids ----
valid_ids = {h["id"] for h in d["hypotheses"]}
pair_re = re.compile(r"^\s*(H\d+)\s+vs\s+(H\d+)\s*$")
fix2_log = {}
for e in d["experiments"]:
    before = list(e.get("discriminates", []))
    out = []
    for entry in before:
        m = pair_re.match(entry)
        if m:
            for hid in (m.group(1), m.group(2)):
                if hid not in out:
                    out.append(hid)
        else:
            # already an id (or something else) -> keep as-is, unique
            if entry not in out:
                out.append(entry)
    # sanity: every produced token is a real hypothesis id
    for t in out:
        assert t in valid_ids, f"{e['id']} produced non-id {t!r}"
    e["discriminates"] = out
    fix2_log[e["id"]] = {"before": before, "after": out}

with open(OUT, "w") as f:
    json.dump(d, f, ensure_ascii=False, indent=1)

# ---- Report what changed, and prove nothing else moved ----
print("FIX1 supporting_evidence_ids added:")
for k, v in fix1_log.items():
    print(f"  {k}: {v}")
print("FIX2 discriminates split:")
for k, v in fix2_log.items():
    print(f"  {k}: {v['before']} -> {v['after']}")

# Confirm every other top-level field is byte-identical to the source.
for key in draft:
    if key in ("hypotheses", "experiments"):
        continue
    same = json.dumps(draft[key], ensure_ascii=False, sort_keys=True) == json.dumps(
        d[key], ensure_ascii=False, sort_keys=True
    )
    print(f"  unchanged[{key}] = {same}")

# Within hypotheses/experiments, confirm only the two intended fields changed.
for a, b in zip(draft["hypotheses"], d["hypotheses"], strict=True):
    for fld in a:
        if fld == "supporting_evidence_ids":
            continue
        assert json.dumps(a[fld], ensure_ascii=False, sort_keys=True) == json.dumps(
            b[fld], ensure_ascii=False, sort_keys=True
        ), (a["id"], fld)
    # new key introduced only where intended
    extra = set(b) - set(a)
    assert extra <= {"supporting_evidence_ids"}, (a["id"], extra)
for a, b in zip(draft["experiments"], d["experiments"], strict=True):
    for fld in a:
        if fld == "discriminates":
            continue
        assert json.dumps(a[fld], ensure_ascii=False, sort_keys=True) == json.dumps(
            b[fld], ensure_ascii=False, sort_keys=True
        ), (a["id"], fld)
print("INVARIANT CHECK: only supporting_evidence_ids and discriminates changed. OK")
print("wrote", OUT)
