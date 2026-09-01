"""Immortalization domain pack — the first reference vertical (PR11).

A thin adapter, and deliberately nothing more. It maps a generic
:class:`~virtualcell.platform.contracts.ReasoningQuery` onto the *actual product path*
(``ImmortalizationAssessmentAgent.assess``, the same entry point the API, CLI and
benchmark use) and converts the resulting ``DecisionReport`` into the generic envelope.

It contains **no** scientific rules: no thresholds, no status derivation, no claim
construction, no tier decisions. Everything scientific comes from the agent and the
policies behind it (``rules`` / ``grounding`` / ``hypotheses``), unchanged. The
conversion is lossless — the full report is preserved verbatim in ``domain_details`` —
so PR10's claim boundaries, evidence tiers, citations, and the Q5/Q6/Q9 corrections
survive the boundary intact.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
from virtualcell.agents.immortalization.models import (
    ConstructType,
    GenomicStabilityValue,
    ImmortalizationAssessmentInput,
    MarkerValue,
    RetentionValue,
)
from virtualcell.core.consumption import ConsumptionReport
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.platform.contracts import (
    DecisionSupport,
    ExplanationLevel,
    QueryProvenance,
    ReasoningQuery,
    ReasoningResponse,
)
from virtualcell.platform.description import (
    AxisDescription,
    AxisKind,
    DomainDescription,
    TaskDescription,
    ValueType,
    derive_consumption,
)
from virtualcell.platform.domains import QueryValidationError
from virtualcell.reasoning.decision import AssessmentFlag, CandidateStatus, DecisionReport

DOMAIN = "immortalization"
PACK_ID = "immortalization.reference.v1"
ENGINE = "immortalization_assessment"

# Platform task -> the vertical's own intent vocabulary. ``assess_state`` covers the four
# assessment intents and takes the specific one from the normalised experiment payload
# (preserving the PR10 input shape); the mechanism and hypothesis tasks are fixed because
# they name a single intent each.
TASK_ASSESS = "assess_state"
TASK_MECHANISM = "explain_mechanism"
TASK_HYPOTHESIS = "handle_hypothesis"

_FIXED_INTENT = {
    TASK_MECHANISM: "mechanism_explanation",
    TASK_HYPOTHESIS: "hypothesis_handling",
}
_DEFAULT_ASSESS_INTENT = "immortalization_assessment"
# The flag that means "a single snapshot is not enough here" — surfaced on the envelope
# because it is a decision the caller must act on.
_TREND_FLAG = "trend_needed"

# --- axis declaration: one statement, read by both the description and the ledger ---
#
# PR17 stated the axes twice - as Pydantic fields on the assessment input and again as private
# `_STATUS_AXES` / `_GUIDANCE_AXES` tuples - with nothing keeping the two in step. This is now
# the single declaration: `describe()` returns it and `_consumption()` derives from it, so the
# pack cannot advertise one thing and report another.
#
# The status/guidance split is PR16's, unchanged. Genomic stability and differentiation
# retention raise flags, add evidence and change the plan, and never the verdict.

_MARKER_VOCAB = tuple(v.value for v in MarkerValue)
_STATUS_PURPOSES = ("candidate_status", "evidence")
_UNKNOWN = "unknown"


def _marker(name: str, description: str) -> AxisDescription:
    return AxisDescription(
        name=name,
        description=description,
        value_type=ValueType.CATEGORICAL,
        vocabulary=_MARKER_VOCAB,
        kind=AxisKind.STATUS,
        unmeasured_value=_UNKNOWN,
        used_for=_STATUS_PURPOSES,
    )


_SENESCENCE_AXES: tuple[str, ...] = ("gammaH2AX", "SA_b_gal", "p16", "p21")

_AXES: tuple[AxisDescription, ...] = (
    _marker("PDL_trend", "Population-doubling-level trend across passages."),
    _marker("DT_trend", "Doubling-time trend across passages."),
    _marker("gammaH2AX", "Double-strand-break marker."),
    _marker("SA_b_gal", "Senescence-associated beta-galactosidase staining."),
    _marker("p16", "CDKN2A/p16 level."),
    _marker("p21", "CDKN1A/p21 level."),
    AxisDescription(
        name="observations",
        description=(
            "A passage series. When it is long enough and clean enough, a derived trend "
            "overrides the snapshot label for the same axis; a blocked override is reported "
            "rather than silently applied."
        ),
        value_type=ValueType.SERIES,
        kind=AxisKind.STATUS,
        used_for=("trajectory", "PDL_trend", "DT_trend", "candidate_status"),
    ),
    AxisDescription(
        name="adipogenic_retention",
        description=(
            "Whether the line still differentiates. Reported beside the verdict and never "
            "through it: a line can proliferate indefinitely and be useless."
        ),
        value_type=ValueType.CATEGORICAL,
        vocabulary=tuple(v.value for v in RetentionValue),
        kind=AxisKind.GUIDANCE,
        unmeasured_value=_UNKNOWN,
        used_for=(
            "flag:functionality_compromised",
            "evidence",
            "overinterpretation_risk",
            "recommended_validation",
            "next_experiment",
        ),
    ),
    AxisDescription(
        name="genomic_stability",
        description=(
            "Karyotype-level stability. One axis, not two: karyotyping is the assay that "
            "measures it, and typing both would create two authorities over one fact."
        ),
        value_type=ValueType.CATEGORICAL,
        vocabulary=tuple(v.value for v in GenomicStabilityValue),
        kind=AxisKind.GUIDANCE,
        unmeasured_value=_UNKNOWN,
        used_for=(
            "flag:genomic_instability_detected",
            "evidence",
            "overinterpretation_risk",
            "recommended_validation",
            "next_experiment",
        ),
    ),
    AxisDescription(
        name="construct",
        canonical_name="construct_type",
        description="The engineered immortalization construct; selects a mechanism rule.",
        value_type=ValueType.CATEGORICAL,
        vocabulary=tuple(v.value for v in ConstructType),
        kind=AxisKind.GUIDANCE,
        unmeasured_value=_UNKNOWN,
        used_for=(
            "mechanistic_chain",
            "limitations",
            "recommended_validation",
            "next_experiment",
        ),
    ),
    AxisDescription(
        name="species",
        description="Recorded for provenance; no deterministic builder reads it.",
        value_type=ValueType.TEXT,
        kind=AxisKind.CONTEXT,
    ),
    AxisDescription(
        name="cell_type",
        description="Recorded for provenance; no deterministic builder reads it.",
        value_type=ValueType.TEXT,
        kind=AxisKind.CONTEXT,
    ),
)

_ASSESS_AXES = tuple(
    a.name for a in _AXES if a.kind is not AxisKind.CONTEXT and a.name != "construct"
)

DESCRIPTION = DomainDescription(
    domain=DOMAIN,
    summary=(
        "Judges whether a cell line is an immortalization *candidate* from proliferation and "
        "senescence markers. It never calls immortalization confirmed, and it keeps three "
        "questions apart: whether the line keeps dividing, whether it is still useful, and "
        "whether its genome is stable."
    ),
    tasks=(
        TaskDescription(
            name=TASK_ASSESS,
            purpose="judges candidacy from measured proliferation and senescence markers",
            required_axes=_SENESCENCE_AXES,
            reads_axes=_ASSESS_AXES,
            example={
                "PDL_trend": "increasing",
                "DT_trend": "stable",
                "gammaH2AX": "low",
                "p16": "low",
            },
        ),
        TaskDescription(
            name=TASK_MECHANISM,
            purpose="explains what a construct does, from the curated mechanism catalog",
            reads_axes=("construct",),
            example={"construct": "TERT_plus_CDK4"},
        ),
        TaskDescription(
            name=TASK_HYPOTHESIS,
            purpose=(
                "answers from a fixed, citation-bound policy whose status and claims are the "
                "same for every input; no submitted value can move it"
            ),
            reads_measurements=False,
        ),
    ),
    axes=_AXES,
    status_vocabulary=tuple(v.value for v in CandidateStatus),
    flags=tuple(v.value for v in AssessmentFlag),
)


class ImmortalizationDomainPack:
    """Connects the immortalization vertical to the generic query boundary."""

    domain = DOMAIN
    supported_tasks: tuple[str, ...] = (TASK_ASSESS, TASK_MECHANISM, TASK_HYPOTHESIS)

    def describe(self) -> DomainDescription:
        return DESCRIPTION

    def validate_experiment(self, task: str, experiment: Mapping[str, Any]) -> None:
        """Run this domain's real input validation and discard the result.

        The same call ``execute`` makes, so a description checked against it is checked
        against production and not against a second, more forgiving copy.
        """
        self._to_assessment_input(
            ReasoningQuery(domain=self.domain, task=task, experiment=dict(experiment))
        )

    def execute(self, query: ReasoningQuery, store: KnowledgeStore) -> ReasoningResponse:
        data = self._to_assessment_input(query)
        report = ImmortalizationAssessmentAgent(store=store).assess(data)
        response = self._to_response(query, report, data)
        response.measurement_consumption = self._consumption(query, data)
        return response

    # --- measurement consumption (derived from the declaration above) --------

    def _consumption(
        self, query: ReasoningQuery, data: ImmortalizationAssessmentInput
    ) -> ConsumptionReport:
        def has_reading(axis: AxisDescription) -> bool:
            if axis.name == "observations":
                return bool(data.observations)
            return str(getattr(data, axis.resolved_name, None)) not in (_UNKNOWN, "None", "")

        return derive_consumption(
            DESCRIPTION, task=query.task, experiment=query.experiment, has_reading=has_reading
        )

    # --- request adaptation --------------------------------------------------

    def _to_assessment_input(self, query: ReasoningQuery):
        experiment = dict(query.experiment)
        payload_intent = experiment.pop("intent", None)
        fixed = _FIXED_INTENT.get(query.task)

        if fixed is not None:
            # A task that names one intent must not be silently overruled by a
            # contradicting payload: dropping the intent would answer a different
            # scientific question than the caller asked for.
            if payload_intent is not None and payload_intent != fixed:
                raise QueryValidationError(
                    f"task {query.task!r} implies intent {fixed!r}, but the experiment "
                    f"payload declares intent {payload_intent!r}; remove the conflicting "
                    "intent or use the task that matches it"
                )
            intent = fixed
        else:
            intent = payload_intent or _DEFAULT_ASSESS_INTENT
            # `assess_state` covers only the assessment intents; a mechanism/hypothesis
            # intent smuggled in here would bypass the task the caller selected.
            if intent in _FIXED_INTENT.values():
                raise QueryValidationError(
                    f"intent {intent!r} is not an assessment intent; use task "
                    f"{next(t for t, i in _FIXED_INTENT.items() if i == intent)!r}"
                )

        try:
            return input_from_scenario(intent, experiment)
        except (ValidationError, ValueError) as exc:
            raise QueryValidationError(
                f"invalid immortalization experiment payload: {exc}"
            ) from exc

    # --- response conversion (normalise; never reinterpret) ------------------

    def _to_response(
        self,
        query: ReasoningQuery,
        report: DecisionReport,
        data: ImmortalizationAssessmentInput,
    ) -> ReasoningResponse:
        flags = [f.value for f in report.flags]
        return ReasoningResponse(
            domain=self.domain,
            task=query.task,
            summary=report.conclusion,
            observations=self._observations(report, data),
            # Input conflicts and withheld overrides are acquisition/QC findings, not
            # biological conclusions, so they are reported as such.
            quality_findings=[*report.input_conflicts, *report.blocked_overrides],
            interpretations=list(report.conflict_explanation),
            # Immortalization expresses hypotheses as HYPOTHESIS-tier claims inside its
            # evidence rather than as free-standing statements, so this stays empty
            # instead of being filled with a restatement.
            hypotheses=[],
            supporting_evidence=[c.model_copy(deep=True) for c in report.supporting_evidence],
            contradicting_evidence=[c.model_copy(deep=True) for c in report.contradicting_evidence],
            mechanistic_links=[link.model_copy(deep=True) for link in report.mechanistic_chain],
            missing_information=list(report.missing_axes),
            uncertainties=list(report.uncertainty),
            limitations=list(report.limitations),
            overinterpretation_risks=list(report.overinterpretation_risk),
            decision_support=DecisionSupport(
                status=report.candidate_status.value if report.candidate_status else None,
                flags=flags,
                trend_required=_TREND_FLAG in flags,
            ),
            recommended_validation=list(report.recommended_validation),
            recommended_next_experiments=list(report.next_experiment),
            provenance=QueryProvenance(
                domain=self.domain,
                task=query.task,
                pack=PACK_ID,
                engine=ENGINE,
                explanation_level=query.explanation_level,
                literature_requested=query.allow_literature,
                deterministic=True,
            ),
            # Verbatim, so normalisation can never lose or reshape the domain report —
            # and the validated input beside it, so the judgment is auditable against
            # exactly what the assessment consumed.
            domain_details={
                "decision_report": report.model_dump(mode="json"),
                "assessment_input": data.model_dump(mode="json"),
            },
        )

    @staticmethod
    def _observations(report: DecisionReport, data: ImmortalizationAssessmentInput) -> list[str]:
        """The marker values the assessment actually consumed.

        Reports the **validated** snapshot inputs (``PDL_trend``, ``DT_trend``, ``p16``,
        ``p21``, ``gammaH2AX``, ``SA_b_gal``, ``adipogenic_retention``) rather than only
        ``derived_input``, which is populated solely when a raw passage series overrode a
        snapshot label — so a snapshot-only assessment would otherwise report *no*
        observations at all and the judgment would be unauditable.

        A derived value takes precedence where one exists, and is marked as such. Values
        are copied verbatim: unmeasured axes are omitted rather than guessed, and nothing
        is reinterpreted.
        """
        derived = dict(report.derived_input)
        observations: list[str] = []
        for axis, value in sorted(data.marker_dict().items()):
            text = str(value)
            if text in ("unknown", "None"):  # never measured: say nothing about it
                continue
            if axis in derived:
                observations.append(f"{axis}={derived[axis]} (derived from series)")
            else:
                observations.append(f"{axis}={text}")
        # Any derived axis outside the snapshot marker set (defensive; keeps parity if
        # the vertical adds an axis later).
        for axis, value in sorted(derived.items()):
            if axis not in data.marker_dict():
                observations.append(f"{axis}={value} (derived from series)")

        trajectory: dict[str, Any] | None = report.trajectory
        if trajectory and trajectory.get("state"):
            observations.append(f"trajectory={trajectory['state']}")
        return observations


def explanation_levels() -> list[str]:
    """The validated explanation levels (exposed for CLI/API help text)."""
    return [level.value for level in ExplanationLevel]
