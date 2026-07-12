"""Mechanism-rule catalog for immortalization construct questions (PR5b).

Q5/Q6 are mechanism-explanation questions with **no** candidate status. The graph
can express positive relations ("A promotes B") but not the crucial *negative*
claims ("TERT alone does not bypass the p16/RB checkpoint"), so those live here as
a curated rule catalog of evidence-tiered supporting and limitation claims. This
module produces no `MechanisticLink`, calls no `explain`, and has no agent/LLM —
PR5c wires the `seed_entity_ids` into graph grounding.

Evidence discipline: keep "does not bypass"; never say CDK4 "directly inhibits
p16"; do not assert non-oncogenicity as established without a specific citation.
Claims carry internal curated provenance only (no fabricated paper citations).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from virtualcell.agents.immortalization.models import (
    AssessmentIntent,
    ConstructType,
    ImmortalizationAssessmentInput,
)
from virtualcell.core.evidence import Claim, EvidenceTier

_PROVENANCE = ["curated:immortalization_seed"]


def _claim(statement: str, tier: EvidenceTier = EvidenceTier.ESTABLISHED) -> Claim:
    return Claim(statement=statement, tier=tier, confidence=0.9, citations=list(_PROVENANCE))


class MechanismRule(BaseModel):
    """A curated mechanism/limitation rule for a construct (no candidate status)."""

    rule_id: str
    intent: AssessmentIntent
    construct_type: ConstructType
    seed_entity_ids: list[str] = Field(default_factory=list)
    supporting_claims: list[Claim] = Field(default_factory=list)
    limitations: list[Claim] = Field(default_factory=list)
    recommended_validation: list[str] = Field(default_factory=list)
    next_experiment: list[str] = Field(default_factory=list)


class UnsupportedMechanismError(ValueError):
    """Raised for a mechanism input the catalog does not cover."""


_TERT_ONLY_RULE = MechanismRule(
    rule_id="TERT_only_p16_competent",
    intent=AssessmentIntent.MECHANISM_EXPLANATION,
    construct_type=ConstructType.TERT_ONLY,
    seed_entity_ids=[
        "gene:TERT",
        "mechanism:telomere_maintenance",
        "mechanism:replicative_senescence",
        "mechanism:p16_rb_arrest",
    ],
    supporting_claims=[
        _claim(
            "TERT supports telomere maintenance and can delay telomere-driven "
            "replicative senescence."
        ),
    ],
    limitations=[
        _claim("TERT alone does not bypass a competent p16/RB checkpoint."),
    ],
    recommended_validation=[
        "Telomere-maintenance activity",
        "p16/RB checkpoint status",
        "Long-term proliferative stability",
    ],
    next_experiment=[
        "TERT/telomerase activity assay",
        "Telomere-length assay",
        "p16 expression assay",
        "RB phosphorylation or G1/S checkpoint assay",
        "Long-term PDL and DT tracking",
        "Evaluate CDK4 co-expression only if an active p16/RB checkpoint remains a limiting axis.",
    ],
)

_TERT_PLUS_CDK4_RULE = MechanismRule(
    rule_id="TERT_plus_CDK4",
    intent=AssessmentIntent.MECHANISM_EXPLANATION,
    construct_type=ConstructType.TERT_PLUS_CDK4,
    seed_entity_ids=[
        "gene:TERT",
        "gene:CDK4",
        "mechanism:telomere_maintenance",
        "mechanism:p16_rb_arrest",
        "mechanism:g1s_progression",
        "phenotype:sustained_proliferation",
    ],
    supporting_claims=[
        _claim("TERT supports telomere maintenance."),
        _claim(
            "CDK4 can functionally bypass p16/RB-mediated G1 arrest through the RB-E2F/G1-S axis."
        ),
        _claim(
            "CDK4 functionally bypasses the p16/RB checkpoint; it does not directly inhibit p16."
        ),
        _claim(
            "The combination addresses two distinct barriers: telomere-driven arrest "
            "and checkpoint-mediated arrest."
        ),
    ],
    limitations=[
        _claim("Sustained proliferation does not establish genomic stability."),
        _claim("Sustained proliferation does not establish retained differentiation capacity."),
        _claim("The construct combination does not by itself establish non-tumorigenicity."),
    ],
    recommended_validation=[
        "Genomic stability",
        "Adipogenic or myogenic functionality",
        "Long-term proliferative stability",
        "Checkpoint behavior",
    ],
    next_experiment=[
        "Karyotype or genomic-stability assay",
        "Differentiation assay",
        "Long-term PDL/DT tracking",
        "TERT activity and telomere-length assay",
        "p16 expression and RB phosphorylation assay",
    ],
)

_RULES = {
    ConstructType.TERT_ONLY: _TERT_ONLY_RULE,
    ConstructType.TERT_PLUS_CDK4: _TERT_PLUS_CDK4_RULE,
}


def get_mechanism_rule(data: ImmortalizationAssessmentInput) -> MechanismRule:
    """Return the curated mechanism rule for a mechanism-explanation input."""
    if data.intent != AssessmentIntent.MECHANISM_EXPLANATION:
        raise UnsupportedMechanismError(
            "the mechanism catalog handles only the mechanism_explanation intent, "
            f"got {data.intent.value!r}"
        )
    rule = _RULES.get(data.construct_type)
    if rule is None:
        raise UnsupportedMechanismError(
            f"no mechanism rule for construct {data.construct_type.value!r}"
        )
    return rule.model_copy(deep=True)
