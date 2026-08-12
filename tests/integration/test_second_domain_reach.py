"""A second domain reaches every interface without any interface knowing it exists.

PR11 claimed that adding a domain is one line in the composition root and nothing else.
Adipogenesis is the first real chance to check that, and these tests check it the only way
that means anything: by driving the *shipped* service, API and CLI with
``{"domain": "adipogenesis", ...}`` and asserting the answer is the vertical's own.

They also pin the two places the claim needed help. Dispatch was already domain-neutral;
the **store** was not — interfaces seeded one vertical by name, so a second domain
dispatched correctly and then grounded nothing. And the shared `DecisionReport` carries the
first vertical's status vocabulary, so the second domain's verdict has to travel on the
envelope. Both are recorded here as behaviour rather than left as prose.
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
from virtualcell.platform.bootstrap import default_registry, seed_registered_domains
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
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
