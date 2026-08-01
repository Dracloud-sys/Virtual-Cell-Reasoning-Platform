"""Product-path parity and safety across the PR11 boundary.

Proves that the four ways to reach immortalization reasoning — the unified service, the
domain pack directly, the FastAPI endpoint, and the CLI — carry **equivalent scientific
content**, and that PR10's epistemic safeguards survive the generic envelope.

Comparison is on normalised semantic fields (status, claims, tiers, citations,
limitations, mechanistic links, validations, next experiments), never on formatting.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
from virtualcell.api.main import app
from virtualcell.cli import main as cli_main
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.platform.bootstrap import default_registry
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.packs.immortalization import ImmortalizationDomainPack
from virtualcell.platform.service import ReasoningService

# The three semantic cases the PR10 corrections concern.
CASES = {
    "Q5": {
        "domain": "immortalization",
        "task": "explain_mechanism",
        "experiment": {"construct": "TERT_only"},
    },
    "Q6": {
        "domain": "immortalization",
        "task": "explain_mechanism",
        "experiment": {"construct": "TERT_plus_CDK4"},
    },
    "Q9": {"domain": "immortalization", "task": "handle_hypothesis", "experiment": {}},
    "assess": {
        "domain": "immortalization",
        "task": "assess_state",
        "experiment": {
            "intent": "immortalization_assessment",
            "PDL_trend": "increasing",
            "DT_trend": "worsening",
        },
    },
}


def _store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(ImmortalizationSeedSource(), store)
    return store


def _service_response(payload: dict) -> ReasoningResponse:
    service = ReasoningService(_store(), default_registry())
    return asyncio.run(service.query(ReasoningQuery.model_validate(payload)))


def _semantics(response: ReasoningResponse) -> dict:
    """The scientific content that must be identical across interfaces."""
    return {
        "status": response.decision_support.status,
        "flags": sorted(response.decision_support.flags),
        "trend_required": response.decision_support.trend_required,
        "supporting": [
            (c.statement, c.tier.value, tuple(c.citations)) for c in response.supporting_evidence
        ],
        "contradicting": [
            (c.statement, c.tier.value, tuple(c.citations)) for c in response.contradicting_evidence
        ],
        "mechanistic": [
            (link.target_id, link.tier.value, tuple(link.path))
            for link in response.mechanistic_links
        ],
        "limitations": response.limitations,
        "validation": response.recommended_validation,
        "next_experiments": response.recommended_next_experiments,
        "risks": response.overinterpretation_risks,
        "missing": response.missing_information,
    }


def _from_dict(payload: dict) -> dict:
    return _semantics(ReasoningResponse.model_validate(payload))


# --- the adapter must not reinterpret the agent -------------------------------


@pytest.mark.parametrize("label", sorted(CASES))
def test_pack_preserves_the_agent_report(label: str) -> None:
    payload = CASES[label]
    store = _store()

    # What the product path produces directly...
    experiment = dict(payload["experiment"])
    intent = {
        "explain_mechanism": "mechanism_explanation",
        "handle_hypothesis": "hypothesis_handling",
    }.get(payload["task"], experiment.pop("intent", "immortalization_assessment"))
    experiment.pop("intent", None)
    report = ImmortalizationAssessmentAgent(store=store).assess(
        input_from_scenario(intent, experiment)
    )

    # ...must survive the generic envelope unchanged.
    response = ImmortalizationDomainPack().execute(ReasoningQuery.model_validate(payload), store)

    assert response.summary == report.conclusion
    assert response.decision_support.status == (
        report.candidate_status.value if report.candidate_status else None
    )
    assert [c.model_dump() for c in response.supporting_evidence] == [
        c.model_dump() for c in report.supporting_evidence
    ]
    assert [c.model_dump() for c in response.contradicting_evidence] == [
        c.model_dump() for c in report.contradicting_evidence
    ]
    assert [link.model_dump() for link in response.mechanistic_links] == [
        link.model_dump() for link in report.mechanistic_chain
    ]
    assert response.limitations == report.limitations
    assert response.recommended_validation == report.recommended_validation
    assert response.recommended_next_experiments == report.next_experiment
    assert response.overinterpretation_risks == report.overinterpretation_risk
    # And the native report is preserved verbatim for traceability.
    assert response.domain_details["decision_report"] == report.model_dump(mode="json")


# --- API / CLI / service parity ----------------------------------------------


@pytest.mark.parametrize("label", sorted(CASES))
def test_api_matches_the_service(label: str) -> None:
    payload = CASES[label]
    with TestClient(app) as client:
        api = client.post("/reasoning/query", json=payload)
    assert api.status_code == 200
    assert _from_dict(api.json()) == _semantics(_service_response(payload))


@pytest.mark.parametrize("label", sorted(CASES))
def test_cli_matches_the_service(label: str, tmp_path, capsys) -> None:
    request_file = tmp_path / "query.json"
    request_file.write_text(json.dumps(CASES[label]), encoding="utf-8")

    exit_code = cli_main(["query", "--input", str(request_file), "--format", "json"])
    assert exit_code == 0
    emitted = json.loads(capsys.readouterr().out)

    assert _from_dict(emitted) == _semantics(_service_response(CASES[label]))


@pytest.mark.parametrize("label", sorted(CASES))
def test_all_four_paths_agree(label: str, tmp_path, capsys) -> None:
    payload = CASES[label]
    service = _semantics(_service_response(payload))
    pack = _semantics(
        ImmortalizationDomainPack().execute(ReasoningQuery.model_validate(payload), _store())
    )

    with TestClient(app) as client:
        api = _from_dict(client.post("/reasoning/query", json=payload).json())

    request_file = tmp_path / "q.json"
    request_file.write_text(json.dumps(payload), encoding="utf-8")
    cli_main(["query", "--input", str(request_file), "--format", "json"])
    cli = _from_dict(json.loads(capsys.readouterr().out))

    assert service == pack == api == cli


def test_repeated_queries_are_deterministic() -> None:
    payload = CASES["Q6"]
    assert _semantics(_service_response(payload)) == _semantics(_service_response(payload))


# --- structured failures ------------------------------------------------------


def test_api_distinguishes_unknown_domain_from_unsupported_task() -> None:
    with TestClient(app) as client:
        unknown = client.post(
            "/reasoning/query", json={"domain": "adipogenesis", "task": "assess_state"}
        )
        unsupported = client.post(
            "/reasoning/query", json={"domain": "immortalization", "task": "predict_yield"}
        )
        invalid = client.post(
            "/reasoning/query",
            json={"domain": "immortalization", "task": "assess_state", "explanation_level": "phd"},
        )

    assert unknown.status_code == 404
    assert unknown.json()["detail"]["error"] == "unknown_domain"
    assert unsupported.status_code == 422
    assert unsupported.json()["detail"]["error"] == "unsupported_task"
    assert invalid.status_code == 422  # transport-level validation


def test_api_does_not_leak_stack_traces() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/reasoning/query",
            json={
                "domain": "immortalization",
                "task": "assess_state",
                "experiment": {"p16": "not-a-marker-value"},
            },
        )
    assert response.status_code == 422
    body = response.text.lower()
    assert "traceback" not in body and 'file "' not in body


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"domain": "adipogenesis", "task": "assess_state"}, 2),
        ({"domain": "immortalization", "task": "predict_yield"}, 2),
        ({"domain": "immortalization"}, 1),
    ],
)
def test_cli_exit_codes_for_invalid_requests(payload, expected, tmp_path, capsys) -> None:
    request_file = tmp_path / "bad.json"
    request_file.write_text(json.dumps(payload), encoding="utf-8")
    assert cli_main(["query", "--input", str(request_file)]) == expected


def test_api_lists_domains_without_naming_one_in_the_route() -> None:
    with TestClient(app) as client:
        body = client.get("/reasoning/domains").json()
    assert body["domains"]["immortalization"] == [
        "assess_state",
        "explain_mechanism",
        "handle_hypothesis",
    ]
