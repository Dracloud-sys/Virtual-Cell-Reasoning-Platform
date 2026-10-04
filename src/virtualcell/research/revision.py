"""What changed between a draft and its revision, and what the new evidence reaches.

A host reads new sources and rewrites part of a plan. `check_research_draft` can check either
draft on its own, and `what_if` can say what in one draft rests on an evidence id, but neither
says what the rewrite *changed*: whether a moved prediction cites what was read, whether a
limit was dropped on the way, or whether parts of the plan the new evidence does not touch
moved too. This module answers those, from the two drafts and the host's stated decisions.

What it does not do, by design:

* **It judges nothing.** Whether a source supports a claim, applies to this system or justifies
  a changed prediction is the host's reading. Roles are reported as the host's, and a decision
  is checked only against what changed, never for whether it is right.
* **It changes nothing.** Both drafts are named by hash. Neither is rewritten, and no predicted
  value is moved, reversed or propagated: a withdrawn source does not make the opposite true, and
  an added one does not make anything true.
* **It does not order the work.** Which change matters most, and what to run first, is not
  computed.

`what_if` is reused for "what rests on the new evidence": the new ids are withdrawn from the
revised draft and the existing dependency trace reports what they reach.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from virtualcell.research.contracts import (
    EvidenceItem,
    EvidenceKind,
    EvidenceRole,
    Prediction,
    ResearchReport,
)
from virtualcell.research.plan import Impact, PlanFinding, WhatIf, _impact

#: Fields of a draft that are lists of statements rather than records with ids.
_STATEMENT_LISTS = ("assumptions", "open_conditions", "confirmed_conditions", "open_items")

#: Changes a `keep` may carry: the target stands on more specific grounds, so what it cites may
#: grow. Any other change is a revision, whatever the decision calls it.
_GROUNDS = frozenset(
    {
        "supporting_evidence_ids",
        "contradicting_evidence_ids",
        "evidence_ids",
        "predictions.evidence_ids",
        "predictions.mechanism_link_ids",
    }
)


class RevisionDecision(BaseModel):
    """What the host (or researcher) decided about one part of the plan, and why.

    Four outcomes, because they are different claims. ``keep``: the part stands, now with more
    specific grounds. ``revise``: an assumption, prediction, control or measurement changed.
    ``hold``: an interpretation is held back or its scope narrowed. ``unchanged_no_new_evidence``:
    nothing relevant was found, so the part stays as it was; this cites no evidence, because there
    is none to cite.
    """

    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(description="A hypothesis, mechanism link or experiment id.")
    decision: Literal["keep", "revise", "hold", "unchanged_no_new_evidence"]
    reason: str
    evidence_ids: list[str] = Field(
        default_factory=list, description="Evidence ids in the revised draft this rests on."
    )
    stated_by: Literal["host", "researcher"] = "host"


class ObjectChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal[
        "hypothesis", "mechanism_link", "experiment", "prediction", "evidence_link", "statement"
    ]
    id: str = Field(
        description=(
            "The object's id. A prediction is experiment|hypothesis|readout|condition|versus; an "
            "evidence link is evidence|target; a statement is its list and its text."
        )
    )
    change: Literal["added", "removed", "modified"]
    fields: list[str] = Field(default_factory=list, description="Fields that differ.")
    cites_new_evidence: list[str] = Field(
        default_factory=list,
        description="New evidence ids the revised object cites directly, or through a cited link.",
    )
    decided_as: list[str] = Field(
        default_factory=list, description="Decisions stated on this object or its experiment."
    )


class ValueChange(BaseModel):
    """A predicted value that moved. Listed on its own: it is the change most easily missed."""

    model_config = ConfigDict(frozen=True)

    prediction: str
    before: str
    after: str
    cites_new_evidence: list[str] = Field(default_factory=list)


class NewEvidenceUse(BaseModel):
    """Where one new evidence id is used in the revised draft. Every role is the host's."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    kind: str
    study: str | None = None
    roles: list[str] = Field(
        default_factory=list, description="target:role for each evidence link naming it."
    )
    supporting_for: list[str] = Field(default_factory=list)
    contradicting_for: list[str] = Field(default_factory=list)
    mechanism_links: list[str] = Field(default_factory=list)
    predictions: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    interpretation_by: Literal["host"] = "host"


class EvidenceDelta(BaseModel):
    model_config = ConfigDict(frozen=True)

    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    edited: list[str] = Field(
        default_factory=list, description="Same id, different content_hash: the text changed."
    )
    new_spans: int = 0
    new_studies: int = Field(
        default=0, description="Distinct articles among the added spans. One paper counts once."
    )
    new_by_study: dict[str, list[str]] = Field(default_factory=dict)
    unused: list[str] = Field(
        default_factory=list, description="Added ids that nothing in the revised draft cites."
    )


class PlanRevision(BaseModel):
    """A revised draft set beside the draft it revises. Computed; the meaning is the host's."""

    model_config = ConfigDict(frozen=True)

    prior_plan_sha256: str
    revised_plan_sha256: str
    evidence: EvidenceDelta
    new_evidence_use: list[NewEvidenceUse] = Field(default_factory=list)
    changes: list[ObjectChange] = Field(default_factory=list)
    value_changes: list[ValueChange] = Field(default_factory=list)
    unchanged: dict[str, int] = Field(
        default_factory=dict, description="How many objects of each kind are identical."
    )
    unchanged_experiments: list[str] = Field(default_factory=list)
    untraced_changes: list[str] = Field(
        default_factory=list,
        description=(
            "Changes that cite no new evidence and that no decision covers. Not a defect by "
            "itself; a change the new evidence does not reach needs its own reason."
        ),
    )
    undecided_changes: list[str] = Field(
        default_factory=list,
        description="Changed hypotheses, mechanism links and experiments with no decision.",
    )
    decisions: list[RevisionDecision] = Field(default_factory=list)
    resting_on_new_evidence: Impact | None = Field(
        default=None,
        description="what_if on the revised draft with the new ids withdrawn: what rests on them.",
    )
    findings: list[PlanFinding] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)


LIMITS: tuple[str, ...] = (
    "Both drafts are the host's. A change is listed because it differs, not because it is "
    "right, and a change that cites new evidence is not thereby justified by it.",
    "Roles (supports, contradicts, method, scope_limit) and decisions are the host's reading. "
    "That a source exists is not that it supports, limits or contradicts anything.",
    "Nothing is propagated. No predicted value is moved, reversed or inferred here; a withdrawn "
    "source does not make the opposite result true.",
    "Objects are matched by id; predictions by experiment, hypothesis, readout, condition and "
    "reference. "
    "Renaming one reads as a removal and an addition.",
    "Nothing here ranks the changes or the experiments.",
)


def _sha(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _prediction_key(experiment_id: str, p: Prediction) -> str:
    return "|".join([experiment_id, p.hypothesis_id, p.readout, p.condition or "", p.versus or ""])


def _dump(model: BaseModel, exclude: set[str] | None = None) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude=exclude or set())


def _diff_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def _study(item: EvidenceItem) -> str | None:
    if item.kind is EvidenceKind.RETRIEVED_SOURCE and item.locator is not None:
        return item.locator.article.stable_key()
    return None


def compare_revision(
    prior: ResearchReport,
    revised: ResearchReport,
    decisions: list[RevisionDecision] | None = None,
) -> PlanRevision:
    """Set `revised` beside `prior`. Both reports carry their evidence in `evidence_snapshot`."""
    decisions = list(decisions or [])
    findings: list[PlanFinding] = []
    before_ev = {e.id: e for e in prior.evidence_snapshot}
    after_ev = {e.id: e for e in revised.evidence_snapshot}
    new_ids = [i for i in after_ev if i not in before_ev]
    new = set(new_ids)
    edited = [
        i
        for i in after_ev
        if i in before_ev and before_ev[i].content_hash != after_ev[i].content_hash
    ]

    links_after = {m.id: m for m in revised.mechanism_links}
    link_new = {lid: sorted(new & set(m.evidence_ids)) for lid, m in links_after.items()}

    by_target: dict[str, list[str]] = {}
    exp_of: dict[str, str] = {}
    for d in decisions:
        by_target.setdefault(d.target_id, []).append(d.decision)

    changes: list[ObjectChange] = []
    unchanged: dict[str, int] = {}

    def record(kind, key, b, a, cites, decided):
        if b == a:
            unchanged[kind] = unchanged.get(kind, 0) + 1
            return
        change = "added" if b is None else "removed" if a is None else "modified"
        fields = _diff_fields(b or {}, a or {}) if change == "modified" else []
        changes.append(
            ObjectChange(
                kind=kind,
                id=key,
                change=change,
                fields=fields,
                cites_new_evidence=sorted(set(cites)),
                decided_as=decided,
            )
        )

    # hypotheses
    hb = {h.id: h for h in prior.hypotheses}
    ha = {h.id: h for h in revised.hypotheses}
    for hid in dict.fromkeys([*hb, *ha]):
        a = ha.get(hid)
        cites = []
        if a is not None:
            cited = a.supporting_evidence_ids + a.contradicting_evidence_ids
            cites = [e for e in cited if e in new]
            cites += [
                lk.evidence_id
                for lk in revised.evidence_links
                if lk.target_id == hid and lk.evidence_id in new
            ]
        record(
            "hypothesis",
            hid,
            _dump(hb[hid]) if hid in hb else None,
            _dump(a) if a is not None else None,
            cites,
            by_target.get(hid, []),
        )

    # mechanism links
    mb = {m.id: m for m in prior.mechanism_links}
    for lid in dict.fromkeys([*mb, *links_after]):
        a = links_after.get(lid)
        cites = list(link_new.get(lid, []))
        if a is not None:
            cites += [
                lk.evidence_id
                for lk in revised.evidence_links
                if lk.target_id == lid and lk.evidence_id in new
            ]
        record(
            "mechanism_link",
            lid,
            _dump(mb[lid]) if lid in mb else None,
            _dump(a) if a is not None else None,
            cites,
            by_target.get(lid, []),
        )

    # experiments (without predictions) and predictions
    eb = {e.id: e for e in prior.experiments}
    ea = {e.id: e for e in revised.experiments}
    value_changes: list[ValueChange] = []
    for eid in dict.fromkeys([*eb, *ea]):
        b, a = eb.get(eid), ea.get(eid)
        record(
            "experiment",
            eid,
            _dump(b, {"predictions"}) if b is not None else None,
            _dump(a, {"predictions"}) if a is not None else None,
            [],
            by_target.get(eid, []),
        )
        pb = {_prediction_key(eid, p): p for p in (b.predictions if b else [])}
        pa = {_prediction_key(eid, p): p for p in (a.predictions if a else [])}
        for key in dict.fromkeys([*pb, *pa]):
            pred = pa.get(key)
            cites = []
            if pred is not None:
                cites = [e for e in pred.evidence_ids if e in new]
                cites += [e for lid in pred.mechanism_link_ids for e in link_new.get(lid, [])]
            exp_of[key] = eid
            record(
                "prediction",
                key,
                _dump(pb[key]) if key in pb else None,
                _dump(pred) if pred is not None else None,
                cites,
                by_target.get(eid, []),
            )
            if key in pb and pred is not None and pb[key].expected != pred.expected:
                value_changes.append(
                    ValueChange(
                        prediction=key,
                        before=pb[key].expected.value,
                        after=pred.expected.value,
                        cites_new_evidence=sorted(set(cites)),
                    )
                )

    # evidence links, keyed by evidence and target so a changed role reads as modified
    lb = {f"{lk.evidence_id}|{lk.target_id}": lk for lk in prior.evidence_links}
    la = {f"{lk.evidence_id}|{lk.target_id}": lk for lk in revised.evidence_links}
    for key in dict.fromkeys([*lb, *la]):
        a = la.get(key)
        record(
            "evidence_link",
            key,
            _dump(lb[key]) if key in lb else None,
            _dump(a) if a is not None else None,
            [a.evidence_id] if a is not None and a.evidence_id in new else [],
            by_target.get(key.split("|", 1)[1], []),
        )

    # statement lists: added and removed only, never "modified", so a dropped limit stays visible
    for name in _STATEMENT_LISTS:
        before, after = getattr(prior, name), getattr(revised, name)
        for text, change in [(t, "removed") for t in before if t not in after] + [
            (t, "added") for t in after if t not in before
        ]:
            changes.append(ObjectChange(kind="statement", id=f"{name}: {text}", change=change))
        unchanged["statement"] = unchanged.get("statement", 0) + sum(t in after for t in before)

    # per-prediction assumptions that were dropped are limits too
    for c in changes:
        if c.kind == "prediction" and c.change == "modified" and "assumptions" in c.fields:
            eid = exp_of[c.id]
            old = {_prediction_key(eid, p): p for p in eb[eid].predictions}[c.id]
            new_p = {_prediction_key(eid, p): p for p in ea[eid].predictions}[c.id]
            for text in old.assumptions:
                if text not in new_p.assumptions:
                    findings.append(
                        PlanFinding(
                            code="prediction_assumption_removed",
                            where=f"prediction:{c.id}",
                            detail=f"the revision drops the stated assumption {text!r}.",
                            field="assumptions",
                            value=text,
                        )
                    )

    # a decision covers an object if it names it, or (for a prediction) its experiment
    decided = set(by_target)

    def covered(c: ObjectChange) -> bool:
        if c.kind == "prediction":
            return exp_of[c.id] in decided
        if c.kind == "evidence_link":
            return c.id.split("|", 1)[1] in decided
        return c.id in decided

    untraced = [
        f"{c.kind}:{c.id}"
        for c in changes
        if c.kind != "statement" and not c.cites_new_evidence and not covered(c)
    ]
    # what changed on each decidable target: its own fields, and its predictions' fields
    target_fields: dict[str, set[str]] = {}
    for c in changes:
        if c.kind in ("hypothesis", "mechanism_link", "experiment"):
            target_fields.setdefault(c.id, set()).update(c.fields or [c.change])
        elif c.kind == "prediction":
            target_fields.setdefault(exp_of[c.id], set()).update(
                [f"predictions.{f}" for f in c.fields] or ["predictions"]
            )
    undecided = sorted(i for i in target_fields if i not in decided)

    findings += _decision_findings(decisions, revised, target_fields, new, after_ev)
    findings += _promoted_support(revised, new)

    use = _new_evidence_use(revised, new_ids, after_ev, decisions)
    studies: dict[str, list[str]] = {}
    for i in new_ids:
        key = _study(after_ev[i])
        if key is not None:
            studies.setdefault(key, []).append(i)
    impact = _impact(revised, WhatIf(remove_evidence_ids=new_ids)) if new_ids else None
    return PlanRevision(
        prior_plan_sha256=_sha(prior.model_dump(mode="json")),
        revised_plan_sha256=_sha(revised.model_dump(mode="json")),
        evidence=EvidenceDelta(
            added=new_ids,
            removed=[i for i in before_ev if i not in after_ev],
            edited=edited,
            new_spans=sum(len(v) for v in studies.values()),
            new_studies=len(studies),
            new_by_study=studies,
            unused=[u.evidence_id for u in use if _unused(u)],
        ),
        new_evidence_use=use,
        changes=changes,
        value_changes=value_changes,
        unchanged=unchanged,
        unchanged_experiments=[e for e in ea if e in eb and e not in target_fields],
        untraced_changes=untraced,
        undecided_changes=undecided,
        decisions=decisions,
        resting_on_new_evidence=impact,
        findings=findings,
        limits=list(LIMITS),
    )


def _unused(u: NewEvidenceUse) -> bool:
    return not (
        u.roles or u.supporting_for or u.contradicting_for or u.mechanism_links or u.predictions
    )


def _new_evidence_use(revised, new_ids, after_ev, decisions) -> list[NewEvidenceUse]:
    out = []
    for i in new_ids:
        out.append(
            NewEvidenceUse(
                evidence_id=i,
                kind=after_ev[i].kind.value,
                study=_study(after_ev[i]),
                roles=[
                    f"{lk.target_id}:{lk.role.value}"
                    for lk in revised.evidence_links
                    if lk.evidence_id == i
                ],
                supporting_for=[h.id for h in revised.hypotheses if i in h.supporting_evidence_ids],
                contradicting_for=[
                    h.id for h in revised.hypotheses if i in h.contradicting_evidence_ids
                ],
                mechanism_links=[m.id for m in revised.mechanism_links if i in m.evidence_ids],
                predictions=[
                    _prediction_key(e.id, p)
                    for e in revised.experiments
                    for p in e.predictions
                    if i in p.evidence_ids
                ],
                decisions=[d.target_id for d in decisions if i in d.evidence_ids],
            )
        )
    return out


def _decision_findings(decisions, revised, target_fields, new, after_ev) -> list[PlanFinding]:
    known = {h.id for h in revised.hypotheses}
    known |= {m.id for m in revised.mechanism_links}
    known |= {e.id for e in revised.experiments}
    out: list[PlanFinding] = []
    for d in decisions:
        where = f"decision:{d.target_id}"
        if d.target_id not in known:
            out.append(
                PlanFinding(
                    code="decision_target_unknown",
                    where=where,
                    detail="names no hypothesis, mechanism link or experiment in the revision.",
                    field="target_id",
                    value=d.target_id,
                )
            )
        for eid in d.evidence_ids:
            if eid not in after_ev:
                out.append(
                    PlanFinding(
                        code="decision_evidence_unknown",
                        where=where,
                        detail=f"cites {eid!r}, which the revised draft does not hold.",
                        field="evidence_ids",
                        value=eid,
                    )
                )
        if d.decision == "unchanged_no_new_evidence" and d.evidence_ids:
            out.append(
                PlanFinding(
                    code="no_new_evidence_decision_cites_evidence",
                    where=where,
                    detail="says nothing relevant was found, yet cites evidence.",
                )
            )
        changed = target_fields.get(d.target_id, set())
        beyond = sorted(changed - _GROUNDS) if d.decision == "keep" else sorted(changed)
        if d.decision in ("keep", "unchanged_no_new_evidence") and beyond:
            out.append(
                PlanFinding(
                    code="decision_says_unchanged_but_changed",
                    where=where,
                    detail=(
                        f"is {d.decision!r}, but the target differs from the prior draft in "
                        f"{beyond}."
                    ),
                    value=d.decision,
                )
            )
        if d.decision == "revise" and d.target_id in known and not changed:
            out.append(
                PlanFinding(
                    code="revise_without_change",
                    where=where,
                    detail="is 'revise', but the target is identical to the prior draft.",
                )
            )
        if d.decision in ("keep", "revise") and d.evidence_ids and not set(d.evidence_ids) & new:
            out.append(
                PlanFinding(
                    code="decision_cites_no_new_evidence",
                    where=where,
                    detail="cites only evidence the prior draft already held.",
                )
            )
    return out


def _promoted_support(revised: ResearchReport, new: set[str]) -> list[PlanFinding]:
    """A new id the host linked as method, contradicts or scope_limit, also listed as support."""
    out: list[PlanFinding] = []
    for h in revised.hypotheses:
        for lk in revised.evidence_links:
            if (
                lk.target_id == h.id
                and lk.evidence_id in new
                and lk.role is not EvidenceRole.SUPPORTS
                and lk.evidence_id in h.supporting_evidence_ids
            ):
                out.append(
                    PlanFinding(
                        code="non_supporting_role_listed_as_support",
                        where=f"hypothesis:{h.id}",
                        detail=(
                            f"{lk.evidence_id!r} is linked as {lk.role.value!r} but also listed in "
                            "supporting_evidence_ids; one of the two is not what the host means."
                        ),
                        field="supporting_evidence_ids",
                        value=lk.evidence_id,
                    )
                )
    return out
