"""The generic reasoning kernel (PR14a).

Two questions decide whether this extraction was worth doing:

* **Is the boundary real?** Nothing in the kernel may know about a domain — checked
  structurally, not by inspection.
* **Can a pack supply only policy?** Proved by grounding and validating a report for a
  domain that does not exist in this repository, using nothing but the kernel.

The rest pins the behaviour the immortalization vertical used to own privately: seed
order, deduplication, the missing-seed refusal, the assertion scope, and the tier
conventions.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import Gene, Interaction, Pathway, Phenotype, RelationType
from virtualcell.reasoning.decision import DecisionReport
from virtualcell.reasoning.kernel import (
    INTERPRETATION_CONFIDENCE,
    MEASUREMENT_CONFIDENCE,
    WEAK_STEPS,
    AssertionSafetyError,
    GroundingError,
    all_of,
    assertion_texts,
    excludes_weak_relations,
    forbidden_phrases_in,
    ground_links,
    interpretation_claim,
    measurement_claim,
    rendered_step,
    targets_in,
    validate_assertions,
)

# A domain this repository knows nothing about: two genes, one causal arm and one merely
# associative arm, converging on the same phenotype.
GENE_A, GENE_B = "gene:adipoq", "gene:leptin"
CAUSAL = "pathway:lipid_storage"
ASSOCIATED = "pathway:inflammation"
PHENOTYPE = "phenotype:adipocyte_maturation"


def _store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    for entity in (
        Gene(id=GENE_A, name="ADIPOQ"),
        Gene(id=GENE_B, name="LEP"),
        Pathway(id=CAUSAL, name="Lipid storage"),
        Pathway(id=ASSOCIATED, name="Inflammation"),
        Phenotype(id=PHENOTYPE, name="Adipocyte maturation"),
    ):
        store.upsert(entity)
    for source, target, relation in (
        (GENE_A, CAUSAL, RelationType.PROMOTES),
        (CAUSAL, PHENOTYPE, RelationType.PROMOTES),
        (GENE_B, ASSOCIATED, RelationType.ASSOCIATED_WITH),
        (ASSOCIATED, PHENOTYPE, RelationType.SUGGESTS),
    ):
        store.add_interaction(
            Interaction(source_id=source, target_id=target, relation=relation, confidence=0.9)
        )
    return store


# --- the boundary is structural ----------------------------------------------


def test_the_kernel_knows_about_no_domain() -> None:
    """The claim "domain-independent" is only worth making if something checks it. A single
    import from ``agents`` would turn the kernel into a second copy of one vertical."""
    package = pathlib.Path("src/virtualcell/reasoning/kernel")
    modules = sorted(package.glob("*.py"))
    assert modules, "kernel package not found"

    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        offenders = [name for name in imported if name.startswith("virtualcell.agents")]
        assert not offenders, f"{module.name} imports a domain: {offenders}"


def test_weak_steps_are_derived_from_the_relation_vocabulary() -> None:
    """Spelled-out step strings drift silently when a relation is renamed; a policy that
    matches nothing then admits everything it was written to exclude."""
    assert rendered_step(RelationType.ASSOCIATED_WITH) == "-associated_with->"
    assert rendered_step("promotes") == "-promotes->"
    assert set(WEAK_STEPS) == {
        rendered_step(RelationType.ASSOCIATED_WITH),
        rendered_step(RelationType.SUGGESTS),
        rendered_step(RelationType.SUGGESTS_NEXT_TEST),
    }


# --- a pack supplies only policy ---------------------------------------------


def test_a_foreign_domain_grounds_a_mechanism_with_kernel_only() -> None:
    """The acceptance test for the whole extraction: a vertical this repository has never
    seen states which targets and which relations it accepts, and gets a chain."""
    chain = ground_links(
        _store(),
        [GENE_A, GENE_B],
        all_of(targets_in({PHENOTYPE, CAUSAL}), excludes_weak_relations()),
    )

    # The causal arm only, closest first. The associative arm reaches the same phenotype
    # and is refused, because a suggestion is not a mechanism.
    assert [link.target_id for link in chain] == [CAUSAL, PHENOTYPE]
    assert all("-promotes->" in step for link in chain for step in link.path)
    # Tier still follows path length, which the kernel does not override: the direct link
    # is established, and the two-hop link through it is already only a hypothesis.
    assert (chain[0].tier, chain[1].tier) == (EvidenceTier.ESTABLISHED, EvidenceTier.HYPOTHESIS)


def test_a_policy_that_admits_weak_relations_gets_them() -> None:
    """The kernel does not decide what is admissible — a hypothesis-style policy that
    wants the associative arm receives it, tiered as the hypothesis it is."""
    chain = ground_links(_store(), [GENE_B], targets_in({PHENOTYPE, ASSOCIATED}))
    assert {link.target_id for link in chain} == {ASSOCIATED, PHENOTYPE}
    assert all(link.tier is EvidenceTier.HYPOTHESIS for link in chain)


# --- the traversal contract ---------------------------------------------------


def test_seed_order_comes_before_closeness() -> None:
    """So every seed's arm surfaces: one seed's shorter paths must not crowd out
    another's entirely."""
    chain = ground_links(_store(), [GENE_B, GENE_A], targets_in({CAUSAL, ASSOCIATED}))
    assert [link.target_id for link in chain] == [ASSOCIATED, CAUSAL]


def test_the_same_reasoning_reached_twice_is_listed_once() -> None:
    """Two seeds finding one path is one piece of reasoning; listing it twice would read
    as corroboration it is not."""
    chain = ground_links(_store(), [GENE_A, GENE_A], targets_in({PHENOTYPE, CAUSAL}))
    assert len(chain) == len({(link.target_id, tuple(link.path)) for link in chain})


def test_an_absent_seed_is_an_error_not_an_empty_chain() -> None:
    """A broken policy must not present as a graph that was consulted and had nothing
    to say."""
    with pytest.raises(GroundingError, match="not in store"):
        ground_links(_store(), ["gene:does_not_exist"], targets_in({PHENOTYPE}))


def test_grounding_is_deterministic() -> None:
    store = _store()
    policy = targets_in({PHENOTYPE, CAUSAL, ASSOCIATED})
    first = ground_links(store, [GENE_A, GENE_B], policy)
    second = ground_links(store, [GENE_A, GENE_B], policy)
    assert [(link.target_id, link.path) for link in first] == [
        (link.target_id, link.path) for link in second
    ]


# --- assertion safety ---------------------------------------------------------


def _report(**over) -> DecisionReport:
    fields = {
        "conclusion": "ADIPOQ supports lipid storage.",
        "supporting_evidence": [measurement_claim("Lipid droplets accumulated.")],
        "contradicting_evidence": [],
        "limitations": ["Association does not mean ADIPOQ causes maturation."],
        "overinterpretation_risk": ["Do not claim ADIPOQ causes maturation."],
    }
    fields.update(over)
    return DecisionReport(**fields)


def test_guidance_that_names_a_forbidden_phrase_is_not_a_violation() -> None:
    """The scope rule that matters most: ``limitations`` and ``overinterpretation_risk``
    quote the forbidden phrasing in order to prohibit it. A scanner that flags them has
    punished the report for being careful."""
    report = _report()
    assert "causes maturation" in " ".join(report.limitations).lower()
    assert forbidden_phrases_in(report, ["causes maturation"]) == []
    validate_assertions(report, ["causes maturation"])  # must not raise


def test_the_same_phrase_asserted_in_the_conclusion_is_a_violation() -> None:
    report = _report(conclusion="ADIPOQ causes maturation.")
    assert forbidden_phrases_in(report, ["causes maturation"]) == ["causes maturation"]
    with pytest.raises(AssertionSafetyError, match="causes maturation"):
        validate_assertions(report, ["causes maturation"])


def test_an_evidence_claim_is_an_assertion_too() -> None:
    """Where a narrative layer would later land, so it is in scope."""
    report = _report(supporting_evidence=[measurement_claim("ADIPOQ causes maturation.")])
    assert forbidden_phrases_in(report, ["causes maturation"])


def test_the_assertion_scope_is_exactly_conclusion_plus_evidence() -> None:
    report = _report(
        supporting_evidence=[measurement_claim("S")],
        contradicting_evidence=[measurement_claim("C")],
    )
    assert assertion_texts(report) == ["ADIPOQ supports lipid storage.", "S", "C"]


def test_matching_ignores_case() -> None:
    assert forbidden_phrases_in(_report(conclusion="ADIPOQ CAUSES MATURATION."), ["causes"])


def test_a_pack_may_supply_its_own_error_type() -> None:
    """So a safety failure stays attributable to the domain whose policy was violated."""

    class AdipogenesisSafetyError(AssertionSafetyError):
        pass

    with pytest.raises(AdipogenesisSafetyError):
        validate_assertions(
            _report(conclusion="ADIPOQ causes maturation."),
            ["causes maturation"],
            error=AdipogenesisSafetyError,
        )


# --- the tier conventions -----------------------------------------------------


def test_an_observation_is_established_and_carries_its_assumption() -> None:
    claim = measurement_claim("Lipid droplets accumulated.")
    assert claim.tier is EvidenceTier.ESTABLISHED
    assert claim.confidence == MEASUREMENT_CONFIDENCE
    assert claim.assumptions == ["Input measurements are valid and quality-controlled."]


def test_a_conclusion_drawn_from_an_observation_is_a_hypothesis() -> None:
    """Reading meaning into an observation adds a step that can be wrong even when the
    observation is right, so it is never as strong as the observation."""
    claim = interpretation_claim("The culture is maturing.")
    assert claim.tier is EvidenceTier.HYPOTHESIS
    assert claim.confidence == INTERPRETATION_CONFIDENCE
    assert INTERPRETATION_CONFIDENCE < MEASUREMENT_CONFIDENCE


def test_a_measurement_is_confident_but_never_certain() -> None:
    assert MEASUREMENT_CONFIDENCE < 1.0
