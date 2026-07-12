"""Tests for the curated immortalization seed graph (PR3 draft)."""

from __future__ import annotations

from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.reasoning.explain import explain

# Phrasings the benchmark forbids (Q9): the spontaneous route is P53-independent,
# never "P53 loss / without P53", and associations must not be stated as CAUSES.
_FORBIDDEN = ["without p53", "p53 loss", "p53 knockout", "causes spontaneous"]


def _seeded() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(ImmortalizationSeedSource(), store)
    return store


def test_seed_loads_expected_shape() -> None:
    store = _seeded()
    n_entities, n_interactions = load_into(ImmortalizationSeedSource(), InMemoryKnowledgeStore())
    assert (n_entities, n_interactions) == (26, 28)
    for eid in (
        "gene:TERT",
        "gene:CDK4",
        "gene:CDKN2A",
        "mechanism:telomere_maintenance",
        "phenotype:sustained_proliferation",
        "marker:gammaH2AX",
    ):
        assert store.get(eid) is not None
    # p16/p21 are searchable as markers via gene aliases.
    assert "p16" in store.get("gene:CDKN2A").aliases
    assert "p21" in store.get("gene:CDKN1A").aliases


def test_cdk4_bypasses_p16_and_drives_proliferation() -> None:
    store = _seeded()
    reach = {link.target_id: link for link in explain(store, "gene:CDK4", max_hops=2).links}
    # CDK4 -inhibits-> p16-RB arrest, -promotes-> G1/S, then -> sustained proliferation.
    assert "mechanism:p16_rb_arrest" in reach
    assert "mechanism:g1s_progression" in reach
    assert reach["phenotype:sustained_proliferation"].hops == 2


def test_tert_arm_reaches_telomere_maintenance() -> None:
    store = _seeded()
    reach = {link.target_id: link for link in explain(store, "gene:TERT", max_hops=1).links}
    assert reach["mechanism:telomere_maintenance"].hops == 1


def test_spontaneous_route_is_weak_and_p53_independent() -> None:
    store = _seeded()
    # The spontaneous mechanism is reached only via weak ASSOCIATED_WITH/SUGGESTS edges.
    relations_into_spontaneous = {
        edge.relation
        for eid in ("gene:TERT", "gene:PPARGC1A")
        for edge in store.edges(eid)
        if edge.target_id == "mechanism:spontaneous_immortalization"
    }
    assert relations_into_spontaneous == {"associated_with"}

    # The gap PR3 surfaced, now fixed by PR4a: this 1-hop weak edge must read as
    # hypothesis, never established.
    spon = next(
        link
        for link in explain(store, "gene:TERT", max_hops=1).links
        if link.target_id == "mechanism:spontaneous_immortalization"
    )
    assert spon.hops == 1
    assert spon.tier == EvidenceTier.HYPOTHESIS

    # No forbidden phrasing anywhere in the seed's text or edge evidence.
    texts = [f"{e.name} {e.description or ''}" for e in store.all_entities()]
    texts += [" ".join(i.evidence) for i in store.all_interactions()]
    blob = " ".join(texts).lower()
    for phrase in _FORBIDDEN:
        assert phrase not in blob, f"forbidden phrasing present: {phrase!r}"


def test_immortalization_candidate_suggests_safety_tests() -> None:
    store = _seeded()
    next_tests = {
        edge.target_id
        for edge in store.edges("phenotype:sustained_proliferation")
        if edge.relation == "suggests_next_test"
    }
    assert next_tests == {
        "assay:karyotype",
        "assay:differentiation",
        "assay:telomere_length",
        "assay:tert_activity",
    }


def test_reviewed_edge_refinements() -> None:
    store = _seeded()
    interactions = store.all_interactions()

    # CDK4 -> p16-RB arrest carries the "functional bypass" caveat in its evidence.
    cdk4_bypass = next(
        i
        for i in interactions
        if i.source_id == "gene:CDK4" and i.target_id == "mechanism:p16_rb_arrest"
    )
    assert any("bypass" in note for note in cdk4_bypass.evidence)

    # Direction fixed: the differentiation assay INDICATES loss of differentiation,
    # and there is no CONTRADICTS edge in the seed anymore.
    diff_targets = {
        e.target_id for e in store.edges("assay:differentiation") if e.relation == "indicates"
    }
    assert "phenotype:loss_of_differentiation" in diff_targets
    assert all(i.relation != "contradicts" for i in interactions)
