"""A second domain reaches every interface without any interface knowing it exists.

PR11 claimed that adding a domain is one line in the composition root and nothing else.
Adipogenesis is the first real chance to check that, and these tests check it the only way
that means anything: by driving the *shipped* service, API and CLI with
``{"domain": "adipogenesis", ...}`` and asserting the answer is the vertical's own.

They also pin the places the claim needed help. Dispatch was already domain-neutral; the
**store** was not — interfaces seeded one vertical by name, so a second domain dispatched
correctly and then grounded nothing. Fixing that first produced a *second* problem worth
testing for: routing and seeding were then declared in two parallel lists, which is the same
drift one level up. And the shared `DecisionReport` carries the first vertical's status
vocabulary, so the second domain's verdict has to travel on the envelope. All of it is
recorded here as behaviour rather than left as prose.
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from virtualcell.api.main import app
from virtualcell.cli import main as cli_main
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.schema import Gene, Interaction, Phenotype, RelationType
from virtualcell.platform.bootstrap import (
    SHIPPED_DOMAINS,
    ShippedDomain,
    default_registry,
    seed_domain,
    seed_registered_domains,
    shipped_domain_names,
)
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.domains import UnknownDomainError
from virtualcell.platform.service import ReasoningService

DIFFERENTIATING = {
    "domain": "adipogenesis",
    "task": "assess_state",
    "experiment": {
        "PPARG": "high",
        "CEBPA": "high",
        "FABP4": "high",
        "lipid_accumulation": "high",
    },
}
MARKERS_ONLY = {
    "domain": "adipogenesis",
    "task": "assess_state",
    "experiment": {"PPARG": "high", "CEBPA": "high"},
}
MECHANISM = {"domain": "adipogenesis", "task": "explain_mechanism", "experiment": {}}


def _store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    return store


def _service(payload: dict) -> ReasoningResponse:
    service = ReasoningService(_store(), default_registry())
    return asyncio.run(service.query(ReasoningQuery.model_validate(payload)))


# --- registration ------------------------------------------------------------


def test_both_domains_are_registered_and_neither_shadows_the_other() -> None:
    registry = default_registry()
    assert registry.domains() == ["adipogenesis", "immortalization"]
    assert registry.tasks("adipogenesis") == ["assess_state", "explain_mechanism"]
    assert "handle_hypothesis" in registry.tasks("immortalization")


def test_adding_the_domain_touched_no_interface() -> None:
    """The PR11 claim, checked structurally: the service, the API route module and the CLI
    still name no vertical."""
    for path in (
        "src/virtualcell/platform/service.py",
        "src/virtualcell/platform/domains.py",
        "src/virtualcell/api/main.py",
        "src/virtualcell/cli.py",
    ):
        tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
        imported = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert not any("adipogenesis" in name for name in imported), path


# --- the same query reaches the same answer through every surface ------------


@pytest.mark.parametrize("payload", [DIFFERENTIATING, MARKERS_ONLY, MECHANISM])
def test_service_api_and_cli_agree(payload: dict, tmp_path, capsys) -> None:
    def semantics(response: ReasoningResponse) -> dict:
        return {
            "summary": response.summary,
            "status": response.decision_support.status,
            "flags": sorted(response.decision_support.flags),
            "supporting": [(c.statement, c.tier.value) for c in response.supporting_evidence],
            "links": [(link.target_id, tuple(link.path)) for link in response.mechanistic_links],
            "missing": response.missing_information,
        }

    service = semantics(_service(payload))

    with TestClient(app) as client:
        api = client.post("/reasoning/query", json=payload)
    assert api.status_code == 200

    request_file = tmp_path / "query.json"
    request_file.write_text(json.dumps(payload), encoding="utf-8")
    assert cli_main(["query", "--input", str(request_file), "--format", "json"]) == 0
    cli = json.loads(capsys.readouterr().out)

    assert semantics(ReasoningResponse.model_validate(api.json())) == service
    assert semantics(ReasoningResponse.model_validate(cli)) == service


def test_the_answer_is_the_vertical_s_own() -> None:
    response = _service(DIFFERENTIATING)
    assert response.domain == "adipogenesis"
    assert response.provenance.pack == "adipogenesis.minimal.v1"
    assert response.decision_support.status == "differentiating"
    assert "adipogenic" in response.summary.lower()


def test_the_second_domain_grounds_because_its_graph_is_seeded_too() -> None:
    """Dispatch was already domain-neutral; the store was not. An interface that seeds one
    vertical by name gives a second domain a correct route to an empty graph."""
    response = _service(MECHANISM)
    assert response.mechanistic_links
    assert any("Adipogenic" in step for link in response.mechanistic_links for step in link.path)


def test_the_domain_status_travels_on_the_envelope_not_the_report() -> None:
    """The finding this vertical produced: ``DecisionReport.candidate_status`` is typed to
    immortalization's vocabulary, so a second domain cannot state its verdict there. The
    platform envelope was already general enough; the report contract was not."""
    response = _service(MARKERS_ONLY)
    assert response.decision_support.status == "insufficient_evidence"
    assert response.decision_support.trend_required  # nothing measured lipid

    native = response.domain_details["decision_report"]
    assert native["candidate_status"] is None  # not borrowed from another domain


def test_the_two_domains_answer_differently_from_the_same_boundary() -> None:
    """The point of a second pack: one query shape, two sciences, no bleed."""
    adipo = _service(DIFFERENTIATING)
    immo = _service(
        {
            "domain": "immortalization",
            "task": "assess_state",
            "experiment": {"PDL_trend": "increasing", "DT_trend": "worsening"},
        }
    )
    assert adipo.decision_support.status != immo.decision_support.status
    assert adipo.provenance.pack != immo.provenance.pack
    assert {link.target_id for link in adipo.mechanistic_links}.isdisjoint(
        {link.target_id for link in immo.mechanistic_links}
    )


# --- failure modes stay typed ------------------------------------------------


def test_an_unsupported_task_for_this_domain_is_distinct_from_an_unknown_domain() -> None:
    with TestClient(app) as client:
        unsupported = client.post(
            "/reasoning/query", json={"domain": "adipogenesis", "task": "handle_hypothesis"}
        )
        unknown = client.post(
            "/reasoning/query", json={"domain": "myogenesis", "task": "assess_state"}
        )
    assert unsupported.status_code != unknown.status_code or (unsupported.json() != unknown.json())


def test_a_contradicting_intent_in_the_payload_is_refused() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/reasoning/query",
            json={
                "domain": "adipogenesis",
                "task": "explain_mechanism",
                "experiment": {"intent": "differentiation_assessment"},
            },
        )
    assert response.status_code >= 400


def test_the_seed_command_can_build_the_second_domain_graph(tmp_path, capsys) -> None:
    saved = tmp_path / "adipo.json"
    assert cli_main(["seed", "adipogenesis", "--save", str(saved)]) == 0
    assert "adipogenesis" in capsys.readouterr().out
    assert saved.exists()


# --- one declaration owns both halves of shipping a domain -------------------


class _FakePack:
    """A third domain that exists only inside this test."""

    domain = "myogenesis"
    supported_tasks: tuple[str, ...] = ("assess_state",)

    def execute(self, query, store) -> ReasoningResponse:
        from virtualcell.platform.contracts import DecisionSupport, QueryProvenance

        return ReasoningResponse(
            domain=self.domain,
            task=query.task,
            summary="Myotube formation was assessed.",
            decision_support=DecisionSupport(status="fusing"),
            provenance=QueryProvenance(
                domain=self.domain,
                task=query.task,
                pack="myogenesis.test.v1",
                engine="myogenesis_test",
                explanation_level=query.explanation_level,
            ),
        )


class _FakeSeed:
    """The graph that domain reasons over."""

    name = "myogenesis_seed"

    def entities(self):
        yield Gene(id="gene:MYOD1", name="MYOD1")
        yield Phenotype(id="phenotype:myotube_formation", name="Myotube formation")

    def interactions(self):
        yield Interaction(
            source_id="gene:MYOD1",
            target_id="phenotype:myotube_formation",
            relation=RelationType.PROMOTES,
            confidence=0.9,
        )


@pytest.mark.parametrize("shipped", SHIPPED_DOMAINS, ids=lambda s: s.name)
def test_every_shipped_domain_is_both_routable_and_seedable(shipped) -> None:
    """The invariant the two parallel lists could violate. Being addressable and having a
    graph to reason over were declared separately, so a pack without a seed dispatched
    correctly and then grounded nothing, and a seed without a pack loaded a graph no query
    could reach. Neither failed loudly."""
    assert default_registry().get(shipped.name) is not None

    store = InMemoryKnowledgeStore()
    entities, _ = seed_domain(shipped.name, store)
    assert entities > 0


def test_the_registry_and_the_seeding_come_from_one_declaration() -> None:
    """Not "the two lists happen to agree" — there is one list, and both derive from it."""
    declared = set(shipped_domain_names())
    assert set(default_registry().domains()) == declared

    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    per_domain = InMemoryKnowledgeStore()
    for name in declared:
        seed_domain(name, per_domain)
    assert {e.id for e in store.all_entities()} == {e.id for e in per_domain.all_entities()}


def test_no_shipped_seed_belongs_to_an_unaddressable_domain() -> None:
    addressable = set(default_registry().domains())
    for shipped in SHIPPED_DOMAINS:
        assert shipped.name in addressable, f"{shipped.seed_source.__name__} is unreachable"


def test_the_domain_name_is_taken_from_the_pack_not_written_twice() -> None:
    """A hand-written key beside the declaration is one more thing that can disagree with
    what the pack actually answers to."""
    for shipped in SHIPPED_DOMAINS:
        assert shipped.name == shipped.pack.domain


def test_declaring_one_domain_twice_fails_loudly() -> None:
    """The quiet outcome is the bad one: last-wins would answer queries with a pack nobody
    chose, over a graph seeded from the other declaration."""
    doubled = (*SHIPPED_DOMAINS, SHIPPED_DOMAINS[0])
    with pytest.raises(ValueError, match="declared more than once"):
        default_registry(doubled)


def test_a_third_domain_needs_exactly_one_declaration() -> None:
    """The PR11 claim, tested rather than asserted: one `ShippedDomain` makes a domain both
    routable and seedable, with no API, CLI, service or contract change."""
    third = ShippedDomain(_FakePack, _FakeSeed)
    domains = (*SHIPPED_DOMAINS, third)

    registry = default_registry(domains)
    assert "myogenesis" in registry.domains()
    assert registry.resolve("myogenesis", "assess_state").domain == "myogenesis"

    store = InMemoryKnowledgeStore()
    seed_registered_domains(store, domains)
    assert store.get("gene:MYOD1") is not None

    # ...and it answers through the shipped service, unchanged.
    service = ReasoningService(store, registry)
    response = asyncio.run(
        service.query(
            ReasoningQuery.model_validate({"domain": "myogenesis", "task": "assess_state"})
        )
    )
    assert response.domain == "myogenesis"
    assert response.decision_support.status == "fusing"


def test_half_a_declaration_is_not_expressible() -> None:
    """The strongest form of the invariant: the two halves cannot drift because a
    declaration missing either one does not construct. There is no check to forget."""
    with pytest.raises(TypeError):
        ShippedDomain(_FakePack)  # a pack with no graph to reason over
    with pytest.raises(TypeError):
        ShippedDomain(seed_source=_FakeSeed)  # a graph no query can reach


def test_a_domain_that_is_not_declared_stays_unknown() -> None:
    registry = default_registry()
    with pytest.raises(UnknownDomainError):
        registry.get("myogenesis")
    with pytest.raises(KeyError):
        seed_domain("myogenesis", InMemoryKnowledgeStore())
