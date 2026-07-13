"""API integration tests for the immortalization assessment agent (PR6)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from virtualcell.api.main import app
from virtualcell.reasoning.decision import DecisionReport

_URL = "/agents/immortalization_assessment/run"


def _run(client: TestClient, assessment: dict):
    return client.post(_URL, json={"query": "Assess", "context": {"assessment": assessment}})


def test_agent_is_listed() -> None:
    with TestClient(app) as client:
        resp = client.get("/agents")
        assert resp.status_code == 200
        assert "immortalization_assessment" in resp.json()["agents"]


def test_assessment_request_round_trips() -> None:
    with TestClient(app) as client:
        resp = _run(
            client,
            {
                "intent": "immortalization_assessment",
                "species": "Bos taurus",
                "cell_type": "preadipocyte",
                "PDL_trend": "increasing",
                "DT_trend": "worsening",
                "gammaH2AX": "low",
                "SA_b_gal": "high",
                "p16": "high",
                "p21": "high",
                "adipogenic_retention": "retained",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent"] == "immortalization_assessment"
        result = body["result"]
        assert result["candidate_status"] == "senescence_or_stress_prone"
        assert result["flags"] == ["trend_needed"]
        assert result["missing_axes"] == []
        # The structured result reconstitutes into a DecisionReport.
        DecisionReport.model_validate(result)


def test_mechanism_request_is_grounded() -> None:
    with TestClient(app) as client:
        resp = _run(client, {"intent": "mechanism_explanation", "construct": "TERT_only"})
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["candidate_status"] is None
        targets = {link["target_id"] for link in result["mechanistic_chain"]}
        assert "mechanism:telomere_maintenance" in targets
        assert result["limitations"]
        blob = " ".join(c["statement"] for c in result["supporting_evidence"]).lower()
        assert "directly inhibits p16" not in blob


def test_hypothesis_request_preserves_p53_wording() -> None:
    with TestClient(app) as client:
        resp = _run(client, {"intent": "hypothesis_handling"})
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["candidate_status"] == "insufficient_evidence"
        claims = result["supporting_evidence"]
        p53 = next(c for c in claims if "P53-independent" in c["statement"])
        assert p53["citations"]
        blob = " ".join(c["statement"] for c in claims).lower()
        assert "without p53" not in blob and "p53 loss" not in blob


def test_observations_series_round_trips_with_trajectory() -> None:
    with TestClient(app) as client:
        resp = _run(
            client,
            {
                "intent": "immortalization_assessment",
                "observations": [
                    {"passage": 25, "cumulative_PDL": 22.0, "DT_hours": 42},
                    {"passage": 30, "cumulative_PDL": 25.5, "DT_hours": 80},
                    {"passage": 35, "cumulative_PDL": 27.0, "DT_hours": 100},
                ],
            },
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["trajectory"]["state"] == "progressive_slowdown"
        assert result["derived_input"]["DT_trend"] == "worsening"
        assert result["candidate_status"] == "senescence_or_stress_prone"
        DecisionReport.model_validate(result)


def test_blocked_override_and_usable_counts_round_trip() -> None:
    # A non-monotonic PDL series: the API result exposes the derived trend, the
    # blocked override + reason, and the per-axis usable timepoint counts.
    with TestClient(app) as client:
        resp = _run(
            client,
            {
                "intent": "immortalization_assessment",
                "PDL_trend": "plateau",
                "observations": [
                    {"passage": 20, "cumulative_PDL": 25.0, "DT_hours": 40},
                    {"passage": 25, "cumulative_PDL": 24.0, "DT_hours": 42},
                    {"passage": 30, "cumulative_PDL": 26.0, "DT_hours": 41},
                ],
            },
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "non_monotonic_pdl" in result["trajectory"]["quality_flags"]
        assert result["blocked_overrides"]
        assert "PDL_trend" not in result["derived_input"]
        assert result["trajectory"]["usable_PDL_timepoints"] == 3
        assert result["candidate_status"] == "senescence_or_stress_prone"
        DecisionReport.model_validate(result)


def test_bad_requests_return_422() -> None:
    with TestClient(app) as client:
        # Missing assessment payload.
        assert client.post(_URL, json={"query": "x", "context": {}}).status_code == 422
        # Missing intent.
        assert _run(client, {}).status_code == 422
        # Invalid marker value.
        bad_marker = _run(client, {"intent": "immortalization_assessment", "p16": "nope"})
        assert bad_marker.status_code == 422
        # Invalid construct.
        bad_construct = _run(client, {"intent": "mechanism_explanation", "construct": "BOGUS"})
        assert bad_construct.status_code == 422
        # Impossible observation (negative doubling time) is a client error, not a 500.
        bad_dt = _run(
            client,
            {
                "intent": "immortalization_assessment",
                "observations": [{"passage": 25, "DT_hours": -5}],
            },
        )
        assert bad_dt.status_code == 422
        # Duplicate passage number is rejected too.
        dup = _run(
            client,
            {
                "intent": "immortalization_assessment",
                "observations": [{"passage": 30, "DT_hours": 40}, {"passage": 30, "DT_hours": 80}],
            },
        )
        assert dup.status_code == 422
