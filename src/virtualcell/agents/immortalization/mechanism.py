"""Mechanism & hypothesis DecisionReports from the KG-explain path (PR9-b).

The deterministic assessment builder (``rules.build_decision_report``) answers the four
*assessment* intents but refuses the mechanism (Q5/Q6) and hypothesis (Q9) intents. This
module closes that gap for those intents by composing the two reasoning primitives:

* the **mechanistic chain** is derived from the curated seed graph with
  :func:`~virtualcell.reasoning.explain.explain` — it is auditable and tier-graded, and a
  path through a weak (``ASSOCIATED_WITH`` / ``SUGGESTS``) edge can never exceed
  ``hypothesis``; and
* the domain **limitations / caveats / claim decomposition** are curated, tier-tagged
  statements (the same discipline as the seed graph itself), never machine-invented.

The result is a :class:`DecisionReport` that respects the benchmark's guardrails: TERT
alone is not presented as sufficient, immortalization is never conflated with safety or
function, and the reported spontaneous route stays a *hypothesis* stated as
"P53-independent" — never reduced to a P53-negative claim, never ``CAUSES``.
"""

from __future__ import annotations

from virtualcell.agents.immortalization.models import (
    AssessmentIntent,
    ConstructType,
    ImmortalizationAssessmentInput,
)
from virtualcell.core.evidence import Claim, EvidenceTier
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.reasoning.decision import CandidateStatus, DecisionReport
from virtualcell.reasoning.explain import Explanation, MechanisticLink, explain

# Seed graph node ids (kept in sync with knowledge.sources.immortalization_seed).
_TERT, _CDK4, _PGC1A = "gene:TERT", "gene:CDK4", "gene:PPARGC1A"

_MECHANISM_INTENTS = frozenset(
    {AssessmentIntent.MECHANISM_EXPLANATION, AssessmentIntent.HYPOTHESIS_HANDLING}
)


class UnsupportedMechanismIntentError(ValueError):
    """Raised when this builder is asked to handle a non-mechanism/hypothesis intent."""


def build_mechanism_report(
    store: KnowledgeStore, data: ImmortalizationAssessmentInput
) -> DecisionReport:
    """Assemble a DecisionReport for a mechanism (Q5/Q6) or hypothesis (Q9) intent."""
    if data.intent not in _MECHANISM_INTENTS:
        raise UnsupportedMechanismIntentError(
            f"intent {data.intent.value!r} is not a mechanism/hypothesis intent; use the "
            "assessment builder (rules.build_decision_report) instead"
        )
    if data.intent is AssessmentIntent.MECHANISM_EXPLANATION:
        return _mechanism_report(store, data)
    return _hypothesis_report(store, data)


def _reach(store: KnowledgeStore, seed_ids: list[str], max_hops: int = 3) -> list[MechanisticLink]:
    """Merge the tier-graded mechanistic reach of several seeds, best link per target."""
    best: dict[str, MechanisticLink] = {}
    for seed_id in seed_ids:
        if store.get(seed_id) is None:
            continue
        for link in explain(store, seed_id, max_hops=max_hops).links:
            prior = best.get(link.target_id)
            if prior is None or link.confidence > prior.confidence:
                best[link.target_id] = link
    return sorted(best.values(), key=lambda link: (-link.confidence, link.hops, link.target_id))


# --- mechanism (Q5 / Q6) -----------------------------------------------------

_MECHANISM_SEEDS = {
    ConstructType.TERT_ONLY: [_TERT],
    ConstructType.TERT_PLUS_CDK4: [_TERT, _CDK4],
    ConstructType.UNKNOWN: [_TERT],
}


def _mechanism_report(
    store: KnowledgeStore, data: ImmortalizationAssessmentInput
) -> DecisionReport:
    seeds = _MECHANISM_SEEDS[data.construct_type]
    links = _reach(store, seeds)
    explanation = Explanation(seed_id=seeds[0], seed_name="construct", max_hops=3, links=links)

    if data.construct_type is ConstructType.TERT_PLUS_CDK4:
        conclusion = (
            "TERT maintains telomeres and CDK4 functionally bypasses the p16/RB checkpoint; "
            "together they enable sustained proliferation via a non-oncogenic, reproducible route."
        )
        limitations = [
            "Immortalization is not safety or function: genomic stability and differentiation "
            "capacity (essential for cultured meat) must be verified separately."
        ]
        risks = [
            "Do not conflate immortalization with utility: sustained proliferation does not "
            "guarantee a stable karyotype or retained differentiation."
        ]
        next_experiment = [
            "Karyotype / genomic-stability assay",
            "Differentiation assay (adipogenic / myogenic)",
            "Long-term PDL tracking",
        ]
    else:
        conclusion = (
            "TERT maintains telomeres and delays replicative (telomeric) senescence, but does "
            "not by itself bypass the p16/RB checkpoint."
        )
        limitations = [
            "TERT does not bypass p16/RB-mediated arrest; a p16-competent primary cell often "
            "fails to immortalize with TERT alone and additionally requires CDK4."
        ]
        risks = [
            "Do not overstate TERT sufficiency: telomere maintenance alone does not immortalize "
            "a p16-competent primary cell."
        ]
        next_experiment = [
            "Check p16 / CDKN2A status",
            "Telomere length and TERT / telomerase activity assay",
            "Add CDK4 if p16 is high",
        ]

    return DecisionReport.scaffold(
        conclusion=conclusion,
        explanation=explanation,
        candidate_status=None,  # a mechanism question carries no candidate status
        limitations=limitations,
        overinterpretation_risk=risks,
        next_experiment=next_experiment,
    )


# --- hypothesis (Q9) ---------------------------------------------------------


def _hypothesis_report(
    store: KnowledgeStore, data: ImmortalizationAssessmentInput
) -> DecisionReport:
    # The mechanistic reach here runs only through weak (ASSOCIATED_WITH / SUGGESTS) edges,
    # so every link is capped at hypothesis — the graph itself refuses to over-state it.
    links = _reach(store, [_TERT, _PGC1A])
    explanation = Explanation(seed_id=_TERT, seed_name="TERT+PGC1A", max_hops=3, links=links)

    claims = [
        Claim(
            statement="TERT activation is associated with telomere maintenance.",
            tier=EvidenceTier.ESTABLISHED,
            confidence=0.9,
            citations=["kb:gene:TERT"],
        ),
        Claim(
            statement="PGC1A activation is associated with mitochondrial recovery.",
            tier=EvidenceTier.ESTABLISHED,
            confidence=0.85,
            citations=["kb:gene:PPARGC1A"],
        ),
        Claim(
            statement=(
                "The reported spontaneous route occurred without activating P53 (P53-independent)."
            ),
            tier=EvidenceTier.HYPOTHESIS,
            confidence=0.5,
            citations=["Believer Meats, Nature Food 2025"],
            assumptions=["citation_required"],
        ),
        Claim(
            statement=(
                "TERT/PGC1A-associated recovery SUGGESTS a spontaneous-immortalization mechanism."
            ),
            tier=EvidenceTier.HYPOTHESIS,
            confidence=0.5,
            citations=["kb:mechanism:spontaneous_immortalization"],
        ),
    ]

    risks = [
        # Phrased to state the claim as P53-independent WITHOUT using any forbidden
        # reduction ('without P53', 'P53 loss', 'P53 knockout', 'CAUSES ...').
        "State the reported route as P53-independent; it is described as proceeding without "
        "activating P53, which is not the same as P53 being absent, deleted, or inactivated.",
        "The TERT/PGC1A association only SUGGESTS a spontaneous-immortalization mechanism; it "
        "does not establish it, and the direction is not a proven cause.",
    ]

    return DecisionReport.scaffold(
        conclusion=(
            "TERT and PGC1A activation are individually established associations (telomere "
            "maintenance; mitochondrial recovery); their link to the reported spontaneous "
            "immortalization route is a hypothesis, not a confirmed mechanism."
        ),
        explanation=explanation,
        candidate_status=CandidateStatus.INSUFFICIENT_EVIDENCE,
        supporting_evidence=claims,
        overinterpretation_risk=risks,
        recommended_validation=["Direct P53 pathway status", "Long-term proliferation tracking"],
        next_experiment=[
            "Confirm P53 pathway status directly",
            "Long-term PDL tracking of the spontaneous route",
            "Telomere / TERT activity and mitochondrial function assays",
        ],
    )
