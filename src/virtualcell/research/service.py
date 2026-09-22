"""The research path: a question and some evidence in, a research design out.

No domain, no pack, no registry. The service never looks at `field_of_study` to decide
anything — it is printed into the prompt as context a reader may find useful, and a test
asserts that two questions from unrelated fields take the same code path.

What the service adds beyond passing a prompt through:

**It assembles the evidence with its labels intact**, so the model is told which items are
observations, which are spans someone read, and which are its own earlier guesses.

**It checks the answer against the request.** A report that parses is not a report that
reasoned: a cited id that was never offered, a hypothesis marked `evidence_linked` with
nothing grounded behind it, or a prediction dressed as an observation are all findable by
code, and they travel out with the report as `IntegrityFinding`s rather than being silently
accepted or silently dropped.

What it does **not** do, in this first version: retrieve literature, read the knowledge
graph, or write anything back. The evidence is whatever the caller injected. That is P2's
work and saying otherwise would be the failure this whole exercise exists to avoid.
"""

from __future__ import annotations

import json
from typing import Any

from virtualcell.research.backend import (
    PROMPT_VERSION,
    BackendCallFailed,
    ResearchBackend,
    get_research_backend,
)
from virtualcell.research.contracts import (
    GROUNDED_KINDS,
    DecisionBranch,
    EvidenceItem,
    Hypothesis,
    HypothesisSupport,
    IntegrityFinding,
    ProposedExperiment,
    ResearchProvenance,
    ResearchReport,
    ResearchRequest,
)


def _render_evidence(items: list[EvidenceItem]) -> str:
    """The evidence block, with every item's kind on its face."""
    if not items:
        return "(none supplied)"
    lines: list[str] = []
    for item in items:
        head = f"[{item.id}] ({item.kind.value}) {item.statement}"
        detail: list[str] = []
        if item.locator is not None:
            loc = item.locator
            where = loc.section_title or loc.table_id or loc.figure_id or loc.source_kind.value
            detail.append(f'read from {loc.article.stable_key()} ({where}): "{loc.source_text}"')
        if item.measurement_context:
            detail.append(f"measured: {item.measurement_context}")
        if item.verification is not None:
            detail.append(f"verification: {item.verification.value}")
        if item.derived_from:
            detail.append(f"derived from: {', '.join(item.derived_from)}")
        if item.assumptions:
            detail.append(f"assumes: {'; '.join(item.assumptions)}")
        lines.append(head + ("\n    " + "\n    ".join(detail) if detail else ""))
    return "\n".join(lines)


def build_prompt(request: ResearchRequest) -> str:
    """Assemble the user-side prompt. Pure, so a test can read what the model was asked."""
    parts = [f"QUESTION:\n{request.question}"]
    if request.goal:
        parts.append(f"GOAL:\n{request.goal}")
    if request.field_of_study:
        parts.append(
            f"FIELD (context for the reader; it does not restrict the "
            f"design):\n{request.field_of_study}"
        )
    if request.context:
        rendered = "\n".join(f"- {k}: {v}" for k, v in request.context.items())
        parts.append(f"CONTEXT:\n{rendered}")
    if request.constraints:
        parts.append("CONSTRAINTS:\n" + "\n".join(f"- {c}" for c in request.constraints))
    parts.append(f"EVIDENCE:\n{_render_evidence(request.evidence)}")
    return "\n\n".join(parts)


class ResearchService:
    """Runs one investigation. Injectable backend; no global state."""

    def __init__(self, backend: ResearchBackend | None = None) -> None:
        # Resolved lazily so constructing a service never requires a provider — the failure
        # belongs to the call that needed a model, not to wiring an object.
        self._backend = backend

    def _resolve_backend(self) -> ResearchBackend:
        if self._backend is None:
            self._backend = get_research_backend()
        return self._backend

    def investigate(self, request: ResearchRequest) -> ResearchReport:
        """Produce a research design, or raise a typed failure. Never a fake success."""
        backend = self._resolve_backend()
        prompt = build_prompt(request)

        raw = backend.design(prompt, max_output_tokens=request.budget.max_output_tokens)
        payload = _parse(raw)

        report = _assemble(request, payload, backend)
        report.integrity = check_integrity(request, report)
        return report


def _parse(raw: str) -> dict[str, Any]:
    """Read the model's JSON, tolerating a code fence and nothing else.

    A model that returns prose has not produced a design, and guessing at its meaning here
    would manufacture structure nobody generated.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BackendCallFailed(f"the model did not return parseable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise BackendCallFailed("the model returned JSON that is not an object")
    return payload


def _assemble(
    request: ResearchRequest, payload: dict[str, Any], backend: ResearchBackend
) -> ResearchReport:
    hypotheses = [
        Hypothesis(
            id=str(h.get("id", f"H{i + 1}")),
            statement=str(h.get("statement", "")),
            support=HypothesisSupport(h.get("support", HypothesisSupport.UNVERIFIED_CANDIDATE)),
            supporting_evidence_ids=[str(x) for x in h.get("supporting_evidence_ids", [])],
            contradicting_evidence_ids=[str(x) for x in h.get("contradicting_evidence_ids", [])],
            applicability=h.get("applicability") or None,
        )
        for i, h in enumerate(payload.get("hypotheses", []))
    ]
    experiments = [
        ProposedExperiment(
            id=str(e.get("id", f"E{i + 1}")),
            design=str(e.get("design", "")),
            discriminates=[str(x) for x in e.get("discriminates", [])],
            controls=[str(x) for x in e.get("controls", [])],
            measurements=[str(x) for x in e.get("measurements", [])],
            timepoints=[str(x) for x in e.get("timepoints", [])],
            branches=[
                DecisionBranch(
                    outcome=str(b.get("outcome", "")), implication=str(b.get("implication", ""))
                )
                for b in e.get("branches", [])
            ],
            priority_rationale=e.get("priority_rationale") or None,
        )
        for i, e in enumerate(payload.get("experiments", []))
    ]
    return ResearchReport(
        question=request.question,
        restated_question=str(payload.get("restated_question", "")),
        assumptions=[str(x) for x in payload.get("assumptions", [])],
        hypotheses=hypotheses,
        experiments=experiments,
        open_items=[str(x) for x in payload.get("open_items", [])],
        evidence_used=[str(x) for x in payload.get("evidence_used", [])],
        # Verbatim from the request, never from the payload: the model has no channel
        # for an EvidenceItem, so it cannot slip a source record of its own in here.
        evidence_snapshot=[item.model_copy(deep=True) for item in request.evidence],
        provenance=ResearchProvenance(
            backend=backend.name,
            model=getattr(backend, "model", None),
            prompt_version=PROMPT_VERSION,
            model_calls=1,
            evidence_offered=len(request.evidence),
        ),
    )


def check_integrity(request: ResearchRequest, report: ResearchReport) -> list[IntegrityFinding]:
    """Everything about a report that code can check without judging the biology.

    Deliberately not a pass/fail gate. These findings say the report is internally
    inconsistent or cites something that does not exist — which is worth knowing and is
    *not* the same question as whether the design is any good. That second question needs a
    person, and calling this check "validation" would blur the two.
    """
    findings: list[IntegrityFinding] = []
    offered = request.evidence_ids()
    grounded = {item.id for item in request.evidence if item.kind in GROUNDED_KINDS}

    def unknown(ids: list[str], where: str) -> None:
        for ref in ids:
            if ref not in offered:
                findings.append(
                    IntegrityFinding(
                        code="unknown_evidence_id",
                        detail=(
                            f"cites {ref!r}, which was never supplied. The report may be "
                            "resting on something that does not exist."
                        ),
                        where=where,
                    )
                )

    if not report.restated_question.strip():
        findings.append(
            IntegrityFinding(
                code="question_not_restated",
                detail="no measurable restatement of the question was produced",
                where="restated_question",
            )
        )

    for hypothesis in report.hypotheses:
        where = f"hypothesis:{hypothesis.id}"
        unknown(hypothesis.supporting_evidence_ids, where)
        unknown(hypothesis.contradicting_evidence_ids, where)
        cited_grounded = grounded.intersection(hypothesis.supporting_evidence_ids)
        if hypothesis.support is HypothesisSupport.EVIDENCE_LINKED and not cited_grounded:
            findings.append(
                IntegrityFinding(
                    code="unsupported_evidence_link",
                    detail=(
                        "claims to be evidence-linked, but nothing it cites is a user "
                        "observation or a span read from a source. On this session's "
                        "evidence it is an unverified candidate."
                    ),
                    where=where,
                )
            )
        if hypothesis.support is HypothesisSupport.UNVERIFIED_CANDIDATE and cited_grounded:
            findings.append(
                IntegrityFinding(
                    code="understated_evidence_link",
                    detail=(
                        f"is marked unverified yet cites grounded evidence "
                        f"({', '.join(sorted(cited_grounded))}); the label and the citations "
                        "disagree."
                    ),
                    where=where,
                )
            )

    hypothesis_ids = {h.id for h in report.hypotheses}
    for experiment in report.experiments:
        where = f"experiment:{experiment.id}"
        for ref in experiment.discriminates:
            if ref not in hypothesis_ids:
                findings.append(
                    IntegrityFinding(
                        code="unknown_hypothesis_id",
                        detail=f"says it discriminates {ref!r}, which is not a hypothesis here",
                        where=where,
                    )
                )
        if not experiment.branches:
            findings.append(
                IntegrityFinding(
                    code="no_decision_branches",
                    detail=(
                        "proposes an experiment without saying what any result would "
                        "change, so running it decides nothing"
                    ),
                    where=where,
                )
            )
        if not experiment.discriminates:
            findings.append(
                IntegrityFinding(
                    code="discriminates_nothing",
                    detail="names no hypothesis this experiment would tell apart",
                    where=where,
                )
            )

    unknown(report.evidence_used, "evidence_used")
    return findings
