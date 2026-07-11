"""Graph grounding for mechanism questions Q5/Q6 (PR5c-1).

Combines the curated `MechanismRule` claims with positive mechanistic paths from
the knowledge graph (`explain`) into a mechanism `DecisionReport`. The report's
prose comes from the curated catalog (which carries the careful negative claims);
the graph only contributes the relation-labelled paths. Mechanism reports carry
**no** candidate status.

Only intent-/construct-relevant targets are kept (an allowlist) so unrelated
`explain` reach (e.g. next-test assays) does not leak into the mechanistic chain.
A rule seed missing from the store is an explicit error, never silently ignored.
"""

from __future__ import annotations

from virtualcell.agents.immortalization.limitations import get_mechanism_rule
from virtualcell.agents.immortalization.models import ConstructType, ImmortalizationAssessmentInput
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.reasoning.decision import DecisionReport
from virtualcell.reasoning.explain import MechanisticLink, explain

_Q5_TARGETS = {"mechanism:telomere_maintenance", "mechanism:replicative_senescence"}
_Q6_TARGETS = _Q5_TARGETS | {
    "mechanism:p16_rb_arrest",
    "mechanism:g1s_progression",
    "phenotype:sustained_proliferation",
}
_ALLOWLIST = {
    ConstructType.TERT_ONLY: _Q5_TARGETS,
    ConstructType.TERT_PLUS_CDK4: _Q6_TARGETS,
}
_CONCLUSION = {
    ConstructType.TERT_ONLY: (
        "TERT supports telomere maintenance and delays telomere-driven replicative "
        "senescence, but does not bypass a competent p16/RB checkpoint."
    ),
    ConstructType.TERT_PLUS_CDK4: (
        "TERT plus CDK4 addresses two distinct proliferation barriers - telomere-driven "
        "arrest and p16/RB checkpoint arrest; sustained proliferation still requires "
        "verifying genomic stability and differentiation."
    ),
}


# Weak/associative relations are non-mechanistic (they belong to the Q9 hypothesis
# route). A mechanism path that traverses one is excluded even if it ends on an
# allowlisted target, so the P53-independent spontaneous route cannot leak into a
# Q5/Q6 chain via a shared target such as sustained_proliferation.
_WEAK_STEPS = ("-associated_with->", "-suggests->", "-suggests_next_test->")


class GroundingError(ValueError):
    """Raised when a rule seed entity is absent from the store."""


def _is_mechanistic(link: MechanisticLink) -> bool:
    return not any(weak in step for step in link.path for weak in _WEAK_STEPS)


def _grounded_links(
    store: KnowledgeStore, seed_ids: list[str], allowlist: set[str]
) -> list[MechanisticLink]:
    selected: list[tuple[int, MechanisticLink]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for order, seed_id in enumerate(seed_ids):
        if store.get(seed_id) is None:
            raise GroundingError(f"rule seed entity not in store: {seed_id}")
        for link in explain(store, seed_id, max_hops=2).links:
            if link.target_id not in allowlist or not _is_mechanistic(link):
                continue
            key = (link.target_id, tuple(link.path))
            if key in seen:
                continue
            seen.add(key)
            selected.append((order, link))
    # Seed order first (so TERT and CDK4 arms both surface), then closeness, then id.
    selected.sort(key=lambda item: (item[0], item[1].hops, item[1].target_id))
    return [link for _, link in selected]


def build_mechanism_report(
    data: ImmortalizationAssessmentInput, store: KnowledgeStore
) -> DecisionReport:
    """Assemble a mechanism DecisionReport (Q5/Q6) from the catalog rule + graph."""
    rule = get_mechanism_rule(data)  # validates mechanism intent + supported construct
    chain = _grounded_links(store, rule.seed_entity_ids, _ALLOWLIST[data.construct_type])

    return DecisionReport(
        conclusion=_CONCLUSION[data.construct_type],
        candidate_status=None,
        flags=[],
        supporting_evidence=rule.supporting_claims,
        contradicting_evidence=[],
        mechanistic_chain=chain,
        limitations=[claim.statement for claim in rule.limitations],
        recommended_validation=rule.recommended_validation,
        next_experiment=rule.next_experiment,
    )
