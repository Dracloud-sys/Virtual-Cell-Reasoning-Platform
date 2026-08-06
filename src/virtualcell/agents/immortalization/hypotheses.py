"""Q9 hypothesis policy: the PGC1A/TERT spontaneous-immortalization route (PR5c-2).

Kept separate from ``grounding.py`` because Q5/Q6 are strong-relation *mechanism*
questions while Q9 is a weak-relation *hypothesis* question with strict wording and
citation requirements. The policy:

* separates the established context (TERT/PGC1A supporting mechanisms) from the weak
  reported spontaneous route;
* preserves "P53-independent" exactly and never rewrites it as P53 loss/knockout/absence;
* never promotes ``ASSOCIATED_WITH`` / ``SUGGESTS`` to causation;
* keeps a required citation on the reported-route claim;
* fixes ``candidate_status`` to ``insufficient_evidence`` **by policy** (this is the
  benchmark's requirement for the hypothesis intent, not a `baseline_status` result).

Grounding admits a link only if both its target *and* the relations on its path match
a per-target signature, so neither an unrelated suggestion nor the strong Q6
CDK4 -> G1/S -> proliferation path can enter a Q9 report.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from virtualcell.agents.immortalization.grounding import GroundingError as GroundingError
from virtualcell.agents.immortalization.models import (
    AssessmentIntent,
    ImmortalizationAssessmentInput,
)
from virtualcell.core.evidence import Claim, EvidenceTier
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.reasoning.decision import CandidateStatus, DecisionReport
from virtualcell.reasoning.explain import MechanisticLink
from virtualcell.reasoning.kernel import (
    WEAK_STEPS,
    ground_links,
    validate_assertions,
)
from virtualcell.reasoning.kernel import (
    assertion_texts as assertion_texts,  # re-exported: the benchmark scores this scope
)
from virtualcell.reasoning.kernel import (
    forbidden_phrases_in as _forbidden_phrases_in,
)

_PROVENANCE = ["curated:immortalization_seed"]
# Rendered weak-relation steps, derived from the relation vocabulary by the kernel, used
# to distinguish established context paths from the weak spontaneous route.
_WEAK_STEPS = WEAK_STEPS
_FORBIDDEN = (
    "without p53",
    "p53 loss",
    "p53 knockout",
    "p53 deletion",
    "causes spontaneous immortalization",
    "tert causes spontaneous immortalization",
    "pgc1a causes spontaneous immortalization",
)


class HypothesisRule(BaseModel):
    rule_id: str
    intent: AssessmentIntent
    seed_entity_ids: list[str] = Field(default_factory=list)
    required_claims: list[Claim] = Field(default_factory=list)
    allowed_target_ids: set[str] = Field(default_factory=set)
    forbidden_phrasings: list[str] = Field(default_factory=list)


class UnsupportedHypothesisError(ValueError):
    """Raised when the hypothesis policy is asked to handle a non-hypothesis intent."""


class HypothesisSafetyError(ValueError):
    """Raised when a hypothesis report contains forbidden P53/causal phrasing."""


_Q9_RULE = HypothesisRule(
    rule_id="PGC1A_TERT_spontaneous",
    intent=AssessmentIntent.HYPOTHESIS_HANDLING,
    # TP53 is deliberately not a seed: Q9 preserves the reported route's wording,
    # it does not explore TP53 downstream mechanisms.
    seed_entity_ids=["gene:TERT", "gene:PPARGC1A", "mechanism:spontaneous_immortalization"],
    required_claims=[
        Claim(
            statement="TERT activation is associated with telomere maintenance.",
            tier=EvidenceTier.ESTABLISHED,
            confidence=0.9,
            citations=list(_PROVENANCE),
        ),
        Claim(
            statement="PGC1A activation is associated with recovery of mitochondrial function.",
            tier=EvidenceTier.ESTABLISHED,
            confidence=0.85,
            citations=list(_PROVENANCE),
        ),
        Claim(
            statement=(
                "The reported spontaneous immortalization-associated recovery route was "
                "described as P53-independent, without activating P53."
            ),
            tier=EvidenceTier.HYPOTHESIS,
            confidence=0.55,
            citations=["Believer Meats, Nature Food 2025; curated as P53-independent"],
        ),
        Claim(
            statement=(
                "TERT/PGC1A-associated recovery suggests a possible spontaneous "
                "immortalization mechanism but does not establish causation."
            ),
            tier=EvidenceTier.HYPOTHESIS,
            confidence=0.5,
            citations=list(_PROVENANCE),
        ),
    ],
    allowed_target_ids={
        "mechanism:telomere_maintenance",
        "mechanism:mitochondrial_function",
        "mechanism:spontaneous_immortalization",
        "phenotype:sustained_proliferation",
    },
    forbidden_phrasings=list(_FORBIDDEN),
)

_CONCLUSION = (
    "The observations are compatible with a reported TERT/PGC1A-associated recovery "
    "hypothesis, but current evidence is insufficient to establish spontaneous "
    "immortalization or causation."
)
_LIMITATIONS = [
    "Association does not establish causation.",
    "P53-independent does not mean P53 loss, knockout, or absence.",
    "TERT/PGC1A activation alone does not confirm immortalization.",
]
_UNCERTAINTY = [
    "The spontaneous route is based on limited context-specific evidence.",
    "Species, cell type, passage history, and long-term stability remain relevant.",
]
_RISK = [
    "Do not rewrite P53-independent as P53 loss or absence.",
    "Do not promote ASSOCIATED_WITH or SUGGESTS relations to causation.",
]
_VALIDATION = [
    "Long-term proliferative stability",
    "Telomere-maintenance activity",
    "Mitochondrial functional recovery",
    "P53 pathway status without assuming loss",
]
_NEXT = [
    "Long-term PDL and DT tracking",
    "TERT activity and telomere-length assay",
    "PGC1A expression and mitochondrial-function assay",
    "P53 pathway activity assay",
    "Genomic-stability and differentiation assays",
]


def _path_matches_signature(target_id: str, path: list[str]) -> bool:
    """Per-target relation signature: which relations a path to this target must use."""
    steps = " ".join(path)
    if target_id in ("mechanism:telomere_maintenance", "mechanism:mitochondrial_function"):
        # Established supporting context: a pure promotes path only, so a redundant
        # detour back through the weak spontaneous route is not admitted here.
        return "-promotes->" in steps and not any(w in steps for w in _WEAK_STEPS)
    if target_id == "mechanism:spontaneous_immortalization":
        return "-associated_with->" in steps
    if target_id == "phenotype:sustained_proliferation":
        # Only via the spontaneous route (associated_with then suggests); this excludes
        # the strong Q6 CDK4 -> G1/S -> proliferation path.
        return "-associated_with->" in steps and "-suggests->" in steps
    return False


def _grounded_links(store: KnowledgeStore, rule: HypothesisRule) -> list[MechanisticLink]:
    """Ground the hypothesis rule under its per-target relation signature."""
    return ground_links(
        store,
        rule.seed_entity_ids,
        lambda link: (
            link.target_id in rule.allowed_target_ids
            and _path_matches_signature(link.target_id, link.path)
        ),
    )


def forbidden_phrases_in(report: DecisionReport) -> list[str]:
    """Forbidden P53/causal phrasings actually *asserted* by ``report`` (may be empty).

    The phrase list is this domain's policy; the scope it is checked against — conclusion
    and evidence claims only, never the safety-guidance fields that quote these phrases in
    order to prohibit them — belongs to the kernel and is shared with every vertical.
    """
    return _forbidden_phrases_in(report, _FORBIDDEN)


def validate_hypothesis_report(report: DecisionReport) -> None:
    """Fail if forbidden P53/causal phrasing appears in an *assertion* field."""
    validate_assertions(
        report, _FORBIDDEN, error=HypothesisSafetyError, context="hypothesis report"
    )


def build_hypothesis_report(
    data: ImmortalizationAssessmentInput, store: KnowledgeStore
) -> DecisionReport:
    """Assemble the Q9 hypothesis DecisionReport (status fixed by policy)."""
    if data.intent != AssessmentIntent.HYPOTHESIS_HANDLING:
        raise UnsupportedHypothesisError(
            "the hypothesis policy handles only the hypothesis_handling intent, "
            f"got {data.intent.value!r}"
        )

    chain = _grounded_links(store, _Q9_RULE)
    report = DecisionReport(
        conclusion=_CONCLUSION,
        # Policy status required by the benchmark for the hypothesis intent - NOT a
        # baseline_status assessment result.
        candidate_status=CandidateStatus.INSUFFICIENT_EVIDENCE,
        flags=[],
        supporting_evidence=[c.model_copy(deep=True) for c in _Q9_RULE.required_claims],
        contradicting_evidence=[],
        mechanistic_chain=chain,
        limitations=list(_LIMITATIONS),
        uncertainty=list(_UNCERTAINTY),
        overinterpretation_risk=list(_RISK),
        recommended_validation=list(_VALIDATION),
        next_experiment=list(_NEXT),
    )
    validate_hypothesis_report(report)
    return report
