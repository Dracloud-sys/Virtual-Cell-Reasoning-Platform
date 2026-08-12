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
from virtualcell.knowledge.schema import (
    Gene,
    Interaction,
    Pathway,
    Phenotype,
    Protein,
    RelationType,
)
from virtualcell.reasoning.decision import DecisionReport
from virtualcell.reasoning.kernel import (
    INTERPRETATION_CONFIDENCE,
    MEASUREMENT_CONFIDENCE,
    WEAK_STEPS,
    AssertionSafetyError,
    GroundingError,
    all_of,
    assertion_texts,
    forbidden_phrases_in,
    ground_links,
    interpretation_claim,
    measurement_claim,
    relations_in,
    rendered_step,
    step_relations,
    targets_in,
    validate_assertions,
)

# A domain this repository knows nothing about: two genes, one causal arm and one merely
# associative arm, converging on the same phenotype — plus two *non-causal, non-weak*
# relations, which are the case an exclusion-based policy silently admits.
GENE_A, GENE_B = "gene:adipoq", "gene:leptin"
CAUSAL = "pathway:lipid_storage"
ASSOCIATED = "pathway:inflammation"
PHENOTYPE = "phenotype:adipocyte_maturation"
PARTNER = "protein:perilipin"
CO_PATHWAY = "pathway:lipid_droplet_assembly"

# This pack's judgement about which relations may carry a *mechanism* claim. Stated by the
# pack, not the kernel: only promotes/inhibits assert that one thing acts on another.
CAUSAL_RELATIONS = (RelationType.PROMOTES, RelationType.INHIBITS)


def _store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    for entity in (
        Gene(id=GENE_A, name="ADIPOQ"),
        Gene(id=GENE_B, name="LEP"),
        Pathway(id=CAUSAL, name="Lipid storage"),
        Pathway(id=ASSOCIATED, name="Inflammation"),
        Phenotype(id=PHENOTYPE, name="Adipocyte maturation"),
        Protein(id=PARTNER, name="Perilipin"),
        Pathway(id=CO_PATHWAY, name="Lipid droplet assembly"),
    ):
        store.upsert(entity)
    for source, target, relation in (
        (GENE_A, CAUSAL, RelationType.PROMOTES),
        (CAUSAL, PHENOTYPE, RelationType.PROMOTES),
        (GENE_B, ASSOCIATED, RelationType.ASSOCIATED_WITH),
        (ASSOCIATED, PHENOTYPE, RelationType.SUGGESTS),
        # Neither causal nor weak: a binding partner, and a pathway the causal arm merely
        # takes part in. Both would pass a "not weak" filter while asserting nothing about
        # one thing driving another.
        (GENE_A, PARTNER, RelationType.INTERACTS_WITH),
        (CAUSAL, CO_PATHWAY, RelationType.PARTICIPATES_IN),
    ):
        store.add_interaction(
            Interaction(source_id=source, target_id=target, relation=relation, confidence=0.9)
        )
    return store


# --- the boundary is structural ----------------------------------------------


def _domain_imports(module: pathlib.Path, package: tuple[str, ...]) -> list[str]:
    """Modules under ``virtualcell.agents`` that ``module`` imports, relative ones resolved.

    Relative imports are the hole a naive scan leaves: ``from ....agents import rules``
    carries no module path a prefix check would recognise, so it would pass silently.
    """
    tree = ast.parse(module.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # ``level`` counts dots: 1 is this package, 2 its parent, and so on.
                base = package[: len(package) - node.level + 1]
                names.add(".".join([*base, node.module] if node.module else base))
            else:
                names.add(node.module or "")
    return sorted(
        name
        for name in names
        if name == "virtualcell.agents" or name.startswith("virtualcell.agents.")
    )


def _package_of(module: pathlib.Path, root: pathlib.Path) -> tuple[str, ...]:
    return module.relative_to(root).parent.parts


def test_the_kernel_knows_about_no_domain() -> None:
    """The claim "domain-independent" is only worth making if something checks it. A single
    import from ``agents`` would turn the kernel into a second copy of one vertical.

    ``rglob`` rather than ``glob``: a nested subpackage is exactly where such an import
    would hide from a scan that only looked at the top level.
    """
    root = pathlib.Path("src")
    modules = sorted((root / "virtualcell/reasoning/kernel").rglob("*.py"))
    assert modules, "kernel package not found"

    for module in modules:
        offenders = _domain_imports(module, _package_of(module, root))
        assert not offenders, f"{module} imports a domain: {offenders}"


@pytest.mark.parametrize(
    "statement",
    [
        "from virtualcell.agents.immortalization import rules",
        "import virtualcell.agents.immortalization.rules",
        "from ....agents.immortalization import rules",  # relative: three packages up
        "from ....agents import immortalization",
    ],
)
def test_the_boundary_check_actually_detects_a_leak(tmp_path, statement: str) -> None:
    """A guard nobody has seen fail is a guard nobody knows works. Each of these is a real
    way to reach a vertical from a nested kernel module."""
    root = tmp_path / "src"
    nested = root / "virtualcell/reasoning/kernel/nested"
    nested.mkdir(parents=True)
    leaky = nested / "leaky.py"
    leaky.write_text(statement + "\n", encoding="utf-8")

    assert _domain_imports(leaky, _package_of(leaky, root))


def test_the_boundary_check_does_not_flag_innocent_imports(tmp_path) -> None:
    root = tmp_path / "src"
    nested = root / "virtualcell/reasoning/kernel/nested"
    nested.mkdir(parents=True)
    clean = nested / "clean.py"
    clean.write_text(
        "import re\n"
        "from virtualcell.knowledge.store import KnowledgeStore\n"
        "from ..grounding import ground_links\n",
        encoding="utf-8",
    )

    assert _domain_imports(clean, _package_of(clean, root)) == []


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
        all_of(targets_in({PHENOTYPE, CAUSAL}), relations_in(CAUSAL_RELATIONS)),
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


# --- the relation policy is positive, not an exclusion list -------------------


def test_a_causal_policy_admits_a_promotes_path() -> None:
    chain = ground_links(
        _store(), [GENE_A], all_of(targets_in({CAUSAL}), relations_in(CAUSAL_RELATIONS))
    )
    assert [step_relations(link.path) for link in chain] == [["promotes"]]


@pytest.mark.parametrize(
    ("seed", "target", "relation"),
    [(GENE_A, PARTNER, "interacts_with"), (CAUSAL, CO_PATHWAY, "participates_in")],
)
def test_a_causal_policy_refuses_relations_that_are_not_causal(
    seed: str, target: str, relation: str
) -> None:
    """The defect this replaced: ``interacts_with`` and ``participates_in`` are neither
    causal nor weak, so an exclusion list built from the weak relations admitted them while
    claiming every step was causal. Binding to something and taking part in something are
    real facts that assert nothing about one thing driving another."""
    store = _store()
    reachable = ground_links(store, [seed], targets_in({target}))
    assert [step_relations(link.path) for link in reachable] == [[relation]]  # the graph has it...

    admitted = ground_links(
        store, [seed], all_of(targets_in({target}), relations_in(CAUSAL_RELATIONS))
    )
    assert admitted == []  # ...and the causal policy refuses it


def test_a_mixed_two_hop_path_is_refused_if_any_step_is_not_causal() -> None:
    """Every step must qualify, not just the first. ADIPOQ promotes lipid storage, which
    participates in droplet assembly — the promotes step does not make the second one
    causal, and a policy that checked only for the presence of a causal relation would
    have admitted the whole path."""
    store = _store()
    reachable = ground_links(store, [GENE_A], targets_in({CO_PATHWAY}))
    assert step_relations(reachable[0].path) == ["promotes", "participates_in"]

    admitted = ground_links(
        store, [GENE_A], all_of(targets_in({CO_PATHWAY}), relations_in(CAUSAL_RELATIONS))
    )
    assert admitted == []


def test_a_relation_policy_accepts_enum_members_or_their_values() -> None:
    store = _store()
    by_enum = ground_links(store, [GENE_A], relations_in([RelationType.PROMOTES]))
    by_value = ground_links(store, [GENE_A], relations_in(["promotes"]))
    assert [link.target_id for link in by_enum] == [link.target_id for link in by_value]
    assert by_enum


def test_a_pack_may_admit_any_relation_it_declares() -> None:
    """The kernel holds no opinion about which relations mean what — a pack that wants
    binding partners declares them and gets them."""
    chain = ground_links(
        _store(),
        [GENE_A],
        all_of(targets_in({PARTNER}), relations_in([RelationType.INTERACTS_WITH])),
    )
    assert [link.target_id for link in chain] == [PARTNER]


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
