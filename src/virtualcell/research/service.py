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

from pydantic import BaseModel, ValidationError

from virtualcell.research.backend import (
    PROMPT_VERSION,
    BackendCallFailed,
    ModelReply,
    ResearchBackend,
    get_research_backend,
)
from virtualcell.research.contracts import (
    GROUNDED_KINDS,
    DecisionBranch,
    EvidenceItem,
    ExperimentPurpose,
    Hypothesis,
    HypothesisSupport,
    IntegrityFinding,
    ObjectiveCoverage,
    Prediction,
    ProposedExperiment,
    ReadoutSpec,
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
        """Produce a research design, or raise a typed failure. Never a fake success.

        Four steps, in this order and not another: read the reply, **check the reply**,
        assemble a report from what was checked, then check the report. The middle step is
        the one that was missing. Assembling first meant the model's payload was coerced
        on the way in — a ``null`` became a crash halfway through construction, a bare
        string became a list of its own characters, and a key nobody declared vanished —
        so by the time anything looked at the report, the evidence of what the model
        actually said was gone.
        """
        backend = self._resolve_backend()
        prompt = build_prompt(request)

        reply = backend.design(prompt, max_output_tokens=request.budget.max_output_tokens)
        payload = _parse(reply.text)
        checked, reply_findings = validate_report_payload(payload)

        report = _assemble(request, checked, backend, reply)
        report.integrity = reply_findings + check_integrity(request, report)
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


#: The keys the system prompt asks the model for. Deliberately **not** every field of
#: `ResearchReport`: `evidence_snapshot`, `integrity` and `provenance` are written here from
#: the request and the call, and a payload offering one of them is trying to author a record
#: about itself.
_REPORT_KEYS = frozenset(
    {
        "restated_question",
        "assumptions",
        "hypotheses",
        "experiments",
        "open_items",
        "evidence_used",
    }
)

#: Derived from the contracts rather than restated, so a field added to either model is
#: covered here without anyone remembering to come back.
_HYPOTHESIS_KEYS = frozenset(Hypothesis.model_fields)
_EXPERIMENT_KEYS = frozenset(ProposedExperiment.model_fields)
_BRANCH_KEYS = frozenset(DecisionBranch.model_fields)

#: How much of an undeclared value to quote back. Enough to recognise a fabricated
#: citation, short enough not to paste an essay into a finding.
_QUOTE_LIMIT = 120


def _bad(where: str, what: str) -> BackendCallFailed:
    """A malformed-output failure that names the path, so the reply can be found again."""
    return BackendCallFailed(f"the model's reply is malformed at {where}: {what}")


def _as_list(value: Any, where: str) -> list[Any]:
    """A list, or a typed failure. A string is **not** a list, which is the point.

    ``"abc"`` is iterable, so a list comprehension over it silently produced
    ``["a", "b", "c"]`` — three assumptions nobody wrote, each one character long, sitting
    in a report as if the model had listed them.
    """
    if value is None:
        raise _bad(where, "it is null, where a list belongs")
    if not isinstance(value, list):
        raise _bad(where, f"it is a {type(value).__name__}, where a list belongs")
    return value


def _as_str_list(value: Any, where: str) -> list[str]:
    out: list[str] = []
    for index, item in enumerate(_as_list(value, where)):
        if not isinstance(item, str):
            # Coercing would manufacture a value: str(None) is "None" and str(1) is an
            # evidence id that nobody supplied but that reads like one.
            raise _bad(
                f"{where}[{index}]",
                f"it is a {type(item).__name__}, where a string belongs",
            )
        out.append(item)
    return out


def _as_str(value: Any, where: str, *, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise _bad(where, f"it is a {type(value).__name__}, where a string belongs")
    return value


def _as_object(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        raise _bad(where, "it is null, where an object belongs")
    if not isinstance(value, dict):
        raise _bad(where, f"it is a {type(value).__name__}, where an object belongs")
    return value


def _undeclared(obj: dict[str, Any], allowed: frozenset[str], where: str) -> list[IntegrityFinding]:
    """Report keys nobody asked for, rather than dropping them.

    A model that returns ``"certainty": 0.99`` or ``"citation": "Nature 2020"`` alongside a
    hypothesis has said something, and the prompt forbids both. Dropping them made the
    report look like the model had obeyed; the value is quoted back so a reader can see a
    fabricated citation for what it is instead of never learning it was offered.
    """
    findings: list[IntegrityFinding] = []
    for key in sorted(set(obj) - allowed):
        quoted = repr(obj[key])
        if len(quoted) > _QUOTE_LIMIT:
            quoted = quoted[:_QUOTE_LIMIT] + "..."
        findings.append(
            IntegrityFinding(
                code="unexpected_model_field",
                detail=(
                    f"returned {key!r}, which the prompt does not ask for and this report "
                    f"has no field for: {quoted}. It was not used. If it is a citation or "
                    "a confidence, the prompt forbids both and the model supplied one anyway."
                ),
                where=where,
            )
        )
    return findings


def _blank_text(value: str, code_where: str) -> list[IntegrityFinding]:
    if value.strip():
        return []
    return [
        IntegrityFinding(
            code="empty_required_text",
            detail="came back empty, so this entry says nothing a reader could act on",
            where=code_where,
        )
    ]


def _records[R: BaseModel](model: type[R], value: Any, where: str) -> list[R]:
    """Small closed records; the contract validates each one and the failure names the path."""
    out: list[R] = []
    for index, raw in enumerate(_as_list(value, where)):
        try:
            out.append(model.model_validate(_as_object(raw, f"{where}[{index}]")))
        except ValidationError as exc:
            raise _bad(f"{where}[{index}]", str(exc).splitlines()[0]) from exc
    return out


def _predictions(value: Any, where: str) -> list[Prediction]:
    return _records(Prediction, value, where)


def _purposes(value: Any, where: str) -> list[ExperimentPurpose]:
    out: list[ExperimentPurpose] = []
    for index, raw in enumerate(_as_str_list(value, where)):
        try:
            out.append(ExperimentPurpose(raw))
        except ValueError as exc:
            allowed = ", ".join(repr(p.value) for p in ExperimentPurpose)
            raise _bad(f"{where}[{index}]", f"{raw!r} is not one of {allowed}") from exc
    return out


def validate_report_payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[IntegrityFinding]]:
    """Check a report payload before a single field of a report is built from it.

    Public because the MCP draft check needs exactly this, and a second copy would
    drift. Who wrote the payload changes none of these checks: a host LLM writing
    ``"discriminates": "H1"`` and this platform's own backend writing it are the same
    defect, and both silently become ``["H", "1"]`` without this step.

    Two kinds of wrong, kept apart, because they need different answers from the caller:

    * **The reply does not have the shape it was asked for** — a null where a list belongs,
      a string where a list belongs, a support value that is not one of the two. Nothing
      usable can be assembled from that, so it raises `BackendCallFailed` naming the exact
      path. Previously these escaped as a raw ``TypeError``, ``AttributeError`` or
      ``ValueError`` from inside a comprehension, past the CLI's typed handlers.
    * **The reply is well-shaped but says something extra or says nothing** — an undeclared
      key, an empty statement. Those become findings and travel with the report, because
      the useful part of the reply is still there and hiding the rest is how a fabricated
      citation disappears.

    What this deliberately does **not** do is require a number of hypotheses or experiments.
    A model that cannot design an experiment from what it was given and says so is more use
    than one padded up to a quota, and a validator that demanded three of each would be
    asking for the padding.

    Returns the payload with every declared key present and typed, so `_assemble` maps
    rather than coerces.
    """
    findings = _undeclared(payload, _REPORT_KEYS, "reply")

    hypotheses: list[dict[str, Any]] = []
    for index, raw in enumerate(_as_list(payload.get("hypotheses", []), "hypotheses")):
        where = f"hypotheses[{index}]"
        obj = _as_object(raw, where)
        ident = _as_str(obj.get("id"), f"{where}.id", default=f"H{index + 1}") or f"H{index + 1}"
        support = obj.get("support", HypothesisSupport.UNVERIFIED_CANDIDATE.value)
        try:
            support_value = HypothesisSupport(support)
        except ValueError as exc:
            allowed = ", ".join(repr(s.value) for s in HypothesisSupport)
            raise _bad(
                f"{where}.support",
                f"{support!r} is not a support value; the only two are {allowed}",
            ) from exc
        statement = _as_str(obj.get("statement"), f"{where}.statement")
        findings.extend(_undeclared(obj, _HYPOTHESIS_KEYS, f"hypothesis:{ident}"))
        findings.extend(_blank_text(statement, f"hypothesis:{ident}"))
        hypotheses.append(
            {
                "id": ident,
                "statement": statement,
                "support": support_value,
                "supporting_evidence_ids": _as_str_list(
                    obj.get("supporting_evidence_ids", []), f"{where}.supporting_evidence_ids"
                ),
                "contradicting_evidence_ids": _as_str_list(
                    obj.get("contradicting_evidence_ids", []),
                    f"{where}.contradicting_evidence_ids",
                ),
                "applicability": _as_str(obj.get("applicability"), f"{where}.applicability")
                or None,
                "sub_question_ids": _as_str_list(
                    obj.get("sub_question_ids", []), f"{where}.sub_question_ids"
                ),
                "mutually_exclusive_with": _as_str_list(
                    obj.get("mutually_exclusive_with", []), f"{where}.mutually_exclusive_with"
                ),
                "alternative_to": _as_str_list(
                    obj.get("alternative_to", []), f"{where}.alternative_to"
                ),
            }
        )

    experiments: list[dict[str, Any]] = []
    for index, raw in enumerate(_as_list(payload.get("experiments", []), "experiments")):
        where = f"experiments[{index}]"
        obj = _as_object(raw, where)
        ident = _as_str(obj.get("id"), f"{where}.id", default=f"E{index + 1}") or f"E{index + 1}"
        design = _as_str(obj.get("design"), f"{where}.design")
        findings.extend(_undeclared(obj, _EXPERIMENT_KEYS, f"experiment:{ident}"))
        findings.extend(_blank_text(design, f"experiment:{ident}"))
        branches: list[dict[str, str]] = []
        for b_index, raw_branch in enumerate(
            _as_list(obj.get("branches", []), f"{where}.branches")
        ):
            b_where = f"{where}.branches[{b_index}]"
            branch = _as_object(raw_branch, b_where)
            findings.extend(
                _undeclared(branch, _BRANCH_KEYS, f"experiment:{ident} branch {b_index + 1}")
            )
            branches.append(
                {
                    "outcome": _as_str(branch.get("outcome"), f"{b_where}.outcome"),
                    "implication": _as_str(branch.get("implication"), f"{b_where}.implication"),
                }
            )
        experiments.append(
            {
                "id": ident,
                "design": design,
                "discriminates": _as_str_list(
                    obj.get("discriminates", []), f"{where}.discriminates"
                ),
                "controls": _as_str_list(obj.get("controls", []), f"{where}.controls"),
                "measurements": _as_str_list(obj.get("measurements", []), f"{where}.measurements"),
                "timepoints": _as_str_list(obj.get("timepoints", []), f"{where}.timepoints"),
                "branches": branches,
                "priority_rationale": _as_str(
                    obj.get("priority_rationale"), f"{where}.priority_rationale"
                )
                or None,
                "predictions": _predictions(obj.get("predictions", []), f"{where}.predictions"),
                "readouts": _records(ReadoutSpec, obj.get("readouts", []), f"{where}.readouts"),
                "purposes": _purposes(obj.get("purposes", []), f"{where}.purposes"),
                "objective_coverage": _records(
                    ObjectiveCoverage,
                    obj.get("objective_coverage", []),
                    f"{where}.objective_coverage",
                ),
            }
        )

    checked = {
        "restated_question": _as_str(payload.get("restated_question"), "restated_question"),
        "assumptions": _as_str_list(payload.get("assumptions", []), "assumptions"),
        "hypotheses": hypotheses,
        "experiments": experiments,
        "open_items": _as_str_list(payload.get("open_items", []), "open_items"),
        "evidence_used": _as_str_list(payload.get("evidence_used", []), "evidence_used"),
    }
    return checked, findings


def _assemble(
    request: ResearchRequest,
    payload: dict[str, Any],
    backend: ResearchBackend,
    reply: ModelReply,
) -> ResearchReport:
    """Map a **checked** payload onto the report contract.

    Nothing here coerces: `validate_report_payload` has already established every type, so a
    ``str()`` call in this function would be either dead or a second, quieter validator.
    """
    return ResearchReport(
        question=request.question,
        restated_question=payload["restated_question"],
        assumptions=payload["assumptions"],
        hypotheses=[Hypothesis(**h) for h in payload["hypotheses"]],
        experiments=[
            ProposedExperiment(**{**e, "branches": [DecisionBranch(**b) for b in e["branches"]]})
            for e in payload["experiments"]
        ],
        open_items=payload["open_items"],
        evidence_used=payload["evidence_used"],
        # Verbatim from the request, never from the payload: the model has no channel
        # for an EvidenceItem, so it cannot slip a source record of its own in here.
        evidence_snapshot=[item.model_copy(deep=True) for item in request.evidence],
        provenance=ResearchProvenance(
            backend=backend.name,
            model=getattr(backend, "model", None),
            model_served=reply.model_served,
            prompt_version=PROMPT_VERSION,
            model_calls=1,
            max_request_attempts=reply.max_request_attempts,
            timeout_seconds=reply.timeout_seconds,
            elapsed_seconds=reply.elapsed_seconds,
            stop_reason=reply.stop_reason,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            evidence_offered=len(request.evidence),
        ),
    )


def _duplicate_ids(ids: list[str], noun: str, findings: list[IntegrityFinding]) -> None:
    """Report a reused id. Every citation to it is ambiguous, and silently so.

    `ResearchRequest` already refuses duplicate *evidence* ids, but the model's own
    hypothesis and experiment ids went unchecked: two hypotheses called ``H1`` were both
    accepted, and an experiment saying it discriminates ``H1`` then named neither one in
    particular — while `check_integrity` confirmed the id existed.
    """
    seen: set[str] = set()
    for ident in ids:
        if ident in seen:
            findings.append(
                IntegrityFinding(
                    code=f"duplicate_{noun}_id",
                    detail=(
                        f"the id {ident!r} is used by more than one {noun}, so every "
                        "citation of it names two things and resolves to neither"
                    ),
                    where=f"{noun}:{ident}",
                )
            )
        seen.add(ident)


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

    if not report.hypotheses and not report.experiments:
        # A restatement on its own used to be an ordinary success: no hypotheses, no
        # experiments, no findings, exit 0. A caller reading the exit code was told a
        # design had been produced when the reply contained none. The two cases are kept
        # apart because they need different responses — one is a model that declined and
        # said what it would need, the other is a model that returned an empty shell.
        if report.open_items:
            findings.append(
                IntegrityFinding(
                    code="design_withheld",
                    detail=(
                        "no hypotheses and no experiments were produced; the reply states "
                        "what is missing in its open items instead. That may be the right "
                        "answer, but it is not a design and must not be read as one."
                    ),
                    where="report",
                )
            )
        else:
            findings.append(
                IntegrityFinding(
                    code="no_design_produced",
                    detail=(
                        "no hypotheses, no experiments and nothing said about why. The "
                        "reply parsed; it contains no design."
                    ),
                    where="report",
                )
            )

    _duplicate_ids([h.id for h in report.hypotheses], "hypothesis", findings)
    _duplicate_ids([e.id for e in report.experiments], "experiment", findings)

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
