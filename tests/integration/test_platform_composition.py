"""PR11 review fixes: real composition, typed timeouts, auditability, strict contracts.

Covers the six blocking gaps found in review:

1. the literature agent is wired into the *real* API and CLI composition paths;
2. a genuine transport timeout is distinguishable from a generic provider error, end to
   end (``UrllibTransport`` -> provider -> agent -> bundle -> orchestrator -> service);
3. snapshot observations actually consumed by the assessment survive into the response;
4. contradictory task/intent combinations are rejected, not silently resolved;
5. ``LiteratureOutcome`` structurally forbids evidence on a non-success status;
6. unknown top-level request fields are rejected rather than silently defaulted.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from virtualcell import cli as cli_module
from virtualcell.agents.literature_discovery.agent import LiteratureDiscoveryAgent
from virtualcell.api.main import app
from virtualcell.cli import main as cli_main
from virtualcell.core.agent import AgentContext
from virtualcell.core.evidence import Claim, EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.literature.contracts import (
    ArticleIdentifier,
    ArticleRecord,
    DiscoveryRunStatus,
    LiteratureSearchResult,
    ProviderProvenance,
)
from virtualcell.literature.providers.base import (
    ProviderError,
    ProviderTimeoutError,
    UrllibTransport,
)
from virtualcell.literature.providers.europe_pmc import EuropePmcProvider
from virtualcell.platform.bootstrap import default_registry
from virtualcell.platform.contracts import (
    LiteratureOutcome,
    LiteratureStatus,
    ReasoningQuery,
    ReasoningResponse,
)
from virtualcell.platform.domains import QueryValidationError
from virtualcell.platform.packs.immortalization import ImmortalizationDomainPack
from virtualcell.platform.service import ReasoningService

_TERT_QUERY = {
    "domain": "immortalization",
    "task": "explain_mechanism",
    "experiment": {"construct": "TERT_only"},
    "allow_literature": True,
    "target_measurements": ["TERT"],
}


def _store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(ImmortalizationSeedSource(), store)
    return store


class _WorkingProvider:
    """Serves one open-access article plus its JATS full text."""

    name = "fake"

    def __init__(self, jats_xml: str) -> None:
        self._xml = jats_xml

    def search(self, query) -> LiteratureSearchResult:
        record = ArticleRecord(
            identifiers=ArticleIdentifier(pmcid="PMC1", pmid="1", provider_id="PMC1"),
            title="TERT",
            abstract="TERT",
            is_open_access=True,
            has_full_text=True,
            provider="fake",
            retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        return LiteratureSearchResult(
            provenance=ProviderProvenance(
                provider="fake",
                query_sent="q",
                retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
                hit_count=1,
            ),
            articles=[record],
        )

    def fetch_record(self, identifier):  # pragma: no cover - unused
        raise NotImplementedError

    def fetch_open_full_text(self, identifier):
        return self._xml


def _fake_agent(jats_xml: str) -> LiteratureDiscoveryAgent:
    return LiteratureDiscoveryAgent(
        AgentContext(services={"literature_provider": _WorkingProvider(jats_xml)})
    )


# --- 1. literature is wired into real API / CLI composition -------------------


def test_api_composes_a_literature_agent_by_default() -> None:
    # Without this the endpoint could never retrieve, whatever the request asked for.
    with TestClient(app) as client:
        client.get("/health")
        agent = app.state.literature_agent
    assert isinstance(agent, LiteratureDiscoveryAgent)
    assert agent.provider is not None  # the real Europe PMC provider by default


def test_api_literature_success_with_an_injected_provider(jats_xml) -> None:
    with TestClient(app) as client:
        app.state.literature_agent = _fake_agent(jats_xml)  # dependency injection
        response = client.post("/reasoning/query", json=_TERT_QUERY)

    assert response.status_code == 200
    literature = ReasoningResponse.model_validate(response.json()).literature
    assert literature.status is LiteratureStatus.SUCCESS
    assert literature.evidence
    assert all(c.tier is EvidenceTier.HYPOTHESIS for c in literature.evidence)
    assert all(c.citations for c in literature.evidence)


def test_api_offline_request_stays_offline(jats_xml) -> None:
    class _Explode:
        provider = None

        async def run(self, inputs):  # pragma: no cover - must never run
            raise AssertionError("literature must not be consulted when disabled")

    with TestClient(app) as client:
        app.state.literature_agent = _Explode()
        response = client.post("/reasoning/query", json={**_TERT_QUERY, "allow_literature": False})

    assert response.status_code == 200
    body = ReasoningResponse.model_validate(response.json())
    assert body.literature.status is LiteratureStatus.NOT_REQUESTED
    assert body.literature.evidence == []


def test_cli_literature_success_with_an_injected_provider(
    jats_xml, tmp_path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(cli_module, "_literature_agent", lambda: _fake_agent(jats_xml))
    request_file = tmp_path / "q.json"
    request_file.write_text(json.dumps(_TERT_QUERY), encoding="utf-8")

    assert cli_main(["query", "--input", str(request_file), "--format", "json"]) == 0
    body = ReasoningResponse.model_validate(json.loads(capsys.readouterr().out))
    assert body.literature.status is LiteratureStatus.SUCCESS
    assert body.literature.evidence


def test_cli_offline_request_never_builds_a_provider(tmp_path, capsys, monkeypatch) -> None:
    def _explode():  # pragma: no cover - must never be called
        raise AssertionError("a provider must not be composed for an offline query")

    monkeypatch.setattr(cli_module, "_literature_agent", _explode)
    request_file = tmp_path / "q.json"
    request_file.write_text(
        json.dumps({**_TERT_QUERY, "allow_literature": False}), encoding="utf-8"
    )
    assert cli_main(["query", "--input", str(request_file), "--format", "json"]) == 0
    body = ReasoningResponse.model_validate(json.loads(capsys.readouterr().out))
    assert body.literature.status is LiteratureStatus.NOT_REQUESTED


# --- 2. real timeouts are distinguishable end to end --------------------------


class _TimingOutTransport:
    """Reproduces what urllib raises when a read times out."""

    def get(self, url, *, headers=None, timeout=10.0):
        raise TimeoutError("timed out")


class _ConnectTimeoutTransport:
    """A *connect* timeout arrives wrapped in URLError(reason=TimeoutError)."""

    def get(self, url, *, headers=None, timeout=10.0):
        raise urllib.error.URLError(TimeoutError("timed out"))


class _BrokenTransport:
    def get(self, url, *, headers=None, timeout=10.0):
        raise ProviderError("connection reset")


def test_urllib_transport_raises_a_typed_timeout(monkeypatch) -> None:
    # The original defect: UrllibTransport collapsed TimeoutError into ProviderError,
    # so the production Europe PMC path could never yield a TIMEOUT status.
    def _timeout(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", _timeout)
    with pytest.raises(ProviderTimeoutError):
        UrllibTransport().get("https://example.invalid/x")


def test_urllib_transport_detects_a_wrapped_connect_timeout(monkeypatch) -> None:
    def _wrapped(*args, **kwargs):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr("urllib.request.urlopen", _wrapped)
    with pytest.raises(ProviderTimeoutError):
        UrllibTransport().get("https://example.invalid/x")


def test_urllib_transport_keeps_non_timeouts_generic(monkeypatch) -> None:
    def _refused(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _refused)
    with pytest.raises(ProviderError) as exc:
        UrllibTransport().get("https://example.invalid/x")
    assert not isinstance(exc.value, ProviderTimeoutError)


@pytest.mark.parametrize("transport", [_TimingOutTransport(), _ConnectTimeoutTransport()])
def test_provider_propagates_the_timeout_type(transport) -> None:
    provider = EuropePmcProvider(transport=transport, retries=0, sleeper=lambda _s: None)
    from virtualcell.literature.contracts import LiteratureQuery

    with pytest.raises(ProviderTimeoutError):
        provider.search(LiteratureQuery(query_text="TERT"))


def test_bundle_records_provider_timeout_distinctly() -> None:
    agent = LiteratureDiscoveryAgent(
        AgentContext(
            services={
                "literature_provider": EuropePmcProvider(
                    transport=_TimingOutTransport(), retries=0, sleeper=lambda _s: None
                )
            }
        )
    )
    from virtualcell.core.contracts import AgentInput

    out = asyncio.run(agent.run(AgentInput(query="TERT")))
    assert out.result["run_status"] == DiscoveryRunStatus.PROVIDER_TIMEOUT.value
    assert out.result["run_status"] != DiscoveryRunStatus.PROVIDER_ERROR.value


def test_service_reports_timeout_for_a_real_transport_timeout() -> None:
    """The end-to-end path the review flagged as impossible to reach."""
    agent = LiteratureDiscoveryAgent(
        AgentContext(
            services={
                "literature_provider": EuropePmcProvider(
                    transport=_TimingOutTransport(), retries=0, sleeper=lambda _s: None
                )
            }
        )
    )
    service = ReasoningService(_store(), default_registry(), literature_agent=agent)
    response = asyncio.run(service.query(ReasoningQuery.model_validate(_TERT_QUERY)))

    assert response.literature.status is LiteratureStatus.TIMEOUT
    assert response.literature.status is not LiteratureStatus.PROVIDER_ERROR
    assert response.literature.evidence == []
    # The scientific content is still returned deterministically.
    assert response.summary and response.supporting_evidence


def test_service_still_reports_provider_error_for_non_timeouts() -> None:
    agent = LiteratureDiscoveryAgent(
        AgentContext(
            services={
                "literature_provider": EuropePmcProvider(
                    transport=_BrokenTransport(), retries=0, sleeper=lambda _s: None
                )
            }
        )
    )
    service = ReasoningService(_store(), default_registry(), literature_agent=agent)
    response = asyncio.run(service.query(ReasoningQuery.model_validate(_TERT_QUERY)))
    assert response.literature.status is LiteratureStatus.PROVIDER_ERROR


def test_run_status_failure_helper_covers_both() -> None:
    assert DiscoveryRunStatus.PROVIDER_TIMEOUT.is_failure
    assert DiscoveryRunStatus.PROVIDER_ERROR.is_failure
    assert not DiscoveryRunStatus.ZERO_RESULTS.is_failure
    assert not DiscoveryRunStatus.SUCCESS.is_failure


# --- 2b. document-retrieval failures are not zero-results ---------------------
#
# Review round 3: the *search* can succeed while the documents behind it fail to
# download. The agent absorbed those into per-document warnings and left run_status
# SUCCESS, so a run whose every document timed out was reported as ZERO_RESULTS —
# "we read everything and nothing qualified" instead of "we could not read it".


class _FetchFailingProvider:
    """Search succeeds with one open-access article; fetching its full text fails."""

    name = "fake"

    def __init__(self, error: ProviderError) -> None:
        self._error = error

    def search(self, query) -> LiteratureSearchResult:
        record = ArticleRecord(
            identifiers=ArticleIdentifier(pmcid="PMC1", pmid="1", provider_id="PMC1"),
            title="TERT",
            abstract=None,
            is_open_access=True,
            has_full_text=True,
            provider="fake",
            retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        return LiteratureSearchResult(
            provenance=ProviderProvenance(
                provider="fake",
                query_sent="q",
                retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
                hit_count=1,
            ),
            articles=[record],
        )

    def fetch_record(self, identifier):  # pragma: no cover - unused
        raise NotImplementedError

    def fetch_open_full_text(self, identifier):
        raise self._error


def _agent_with(provider) -> LiteratureDiscoveryAgent:
    return LiteratureDiscoveryAgent(AgentContext(services={"literature_provider": provider}))


@pytest.mark.parametrize(
    "error,expected_bundle,expected_platform",
    [
        (
            ProviderTimeoutError("full text timed out"),
            DiscoveryRunStatus.PROVIDER_TIMEOUT,
            LiteratureStatus.TIMEOUT,
        ),
        (
            ProviderError("full text unavailable"),
            DiscoveryRunStatus.PROVIDER_ERROR,
            LiteratureStatus.PROVIDER_ERROR,
        ),
    ],
)
def test_document_fetch_failure_is_not_reported_as_zero_results(
    error, expected_bundle, expected_platform
) -> None:
    agent = _agent_with(_FetchFailingProvider(error))
    service = ReasoningService(_store(), default_registry(), literature_agent=agent)
    response = asyncio.run(service.query(ReasoningQuery.model_validate(_TERT_QUERY)))

    assert response.literature.status is expected_platform
    assert response.literature.status is not LiteratureStatus.ZERO_RESULTS
    assert response.literature.evidence == []  # a failure never becomes evidence
    # And the typed failure is recorded on the bundle rather than only in prose.
    from virtualcell.core.contracts import AgentInput

    out = asyncio.run(
        agent.run(
            AgentInput(
                query="TERT",
                context={
                    "extract": True,
                    "verify": True,
                    "convert": True,
                    "target_measurements": ["TERT"],
                },
            )
        )
    )
    failures = out.result["document_failures"]
    assert failures and failures[0]["status"] == expected_bundle.value


def test_document_fetch_timeout_and_error_are_distinguishable() -> None:
    def _status(error):
        agent = _agent_with(_FetchFailingProvider(error))
        service = ReasoningService(_store(), default_registry(), literature_agent=agent)
        return asyncio.run(
            service.query(ReasoningQuery.model_validate(_TERT_QUERY))
        ).literature.status

    assert _status(ProviderTimeoutError("slow")) is LiteratureStatus.TIMEOUT
    assert _status(ProviderError("broken")) is LiteratureStatus.PROVIDER_ERROR


def test_genuine_zero_results_is_still_zero_results(jats_xml) -> None:
    """A search that returns nothing is a real negative — not a failure."""

    class _EmptyProvider:
        name = "fake"

        def search(self, query):
            return LiteratureSearchResult(
                provenance=ProviderProvenance(
                    provider="fake",
                    query_sent="q",
                    retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
                    hit_count=0,
                ),
                articles=[],
            )

        def fetch_record(self, identifier):  # pragma: no cover - unused
            raise NotImplementedError

        def fetch_open_full_text(self, identifier):  # pragma: no cover - unused
            return None

    service = ReasoningService(
        _store(), default_registry(), literature_agent=_agent_with(_EmptyProvider())
    )
    response = asyncio.run(service.query(ReasoningQuery.model_validate(_TERT_QUERY)))
    assert response.literature.status is LiteratureStatus.ZERO_RESULTS


def test_partial_failure_keeps_the_usable_evidence(jats_xml) -> None:
    """One document succeeds, another times out: keep the evidence, record the failure."""

    class _MixedProvider:
        name = "fake"

        def search(self, query):
            good = ArticleRecord(
                identifiers=ArticleIdentifier(pmcid="PMC1", provider_id="PMC1"),
                title="TERT good",
                abstract="TERT",
                is_open_access=True,
                has_full_text=True,
                provider="fake",
                retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
            )
            bad = ArticleRecord(
                identifiers=ArticleIdentifier(pmcid="PMC2", provider_id="PMC2"),
                title="TERT bad",
                abstract=None,
                is_open_access=True,
                has_full_text=True,
                provider="fake",
                retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
            )
            return LiteratureSearchResult(
                provenance=ProviderProvenance(
                    provider="fake",
                    query_sent="q",
                    retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
                    hit_count=2,
                ),
                articles=[good, bad],
            )

        def fetch_record(self, identifier):  # pragma: no cover - unused
            raise NotImplementedError

        def fetch_open_full_text(self, identifier):
            if identifier.pmcid == "PMC2":
                raise ProviderTimeoutError("second document timed out")
            return jats_xml

    service = ReasoningService(
        _store(), default_registry(), literature_agent=_agent_with(_MixedProvider())
    )
    response = asyncio.run(service.query(ReasoningQuery.model_validate(_TERT_QUERY)))

    # The usable result is preserved...
    assert response.literature.status is LiteratureStatus.SUCCESS
    assert response.literature.evidence
    # ...and the partial failure is recorded rather than discarded or promoted.
    assert "partial retrieval" in (response.literature.detail or "")


# --- 2c. CLI failure detection covers every failure status --------------------


class _SearchFailingProvider:
    name = "fake"

    def __init__(self, error: ProviderError) -> None:
        self._error = error

    def search(self, query):
        raise self._error

    def fetch_record(self, identifier):  # pragma: no cover - unused
        raise NotImplementedError

    def fetch_open_full_text(self, identifier):  # pragma: no cover - unused
        return None


@pytest.mark.parametrize(
    "error,expected_status",
    [
        (ProviderTimeoutError("search timed out"), "provider_timeout"),
        (ProviderError("search failed"), "provider_error"),
    ],
)
def test_cli_literature_discover_exits_non_zero_on_any_failure(
    error, expected_status, capsys, monkeypatch
) -> None:
    # The regression: only 'provider_error' was treated as failure, so the newly added
    # 'provider_timeout' exited 0 and an automation pipeline would read it as success.
    import virtualcell.agents.literature_discovery.agent as agent_module

    monkeypatch.setattr(
        agent_module, "EuropePmcProvider", lambda *a, **k: _SearchFailingProvider(error)
    )
    exit_code = cli_main(["literature", "discover", "--query", "TERT"])
    assert exit_code == 1, f"{expected_status} must exit non-zero"
    assert expected_status in capsys.readouterr().out  # named in text mode


@pytest.mark.parametrize(
    "error,expected_status",
    [
        (ProviderTimeoutError("search timed out"), "provider_timeout"),
        (ProviderError("search failed"), "provider_error"),
    ],
)
def test_cli_literature_discover_failure_is_machine_readable(
    error, expected_status, tmp_path, capsys, monkeypatch
) -> None:
    import virtualcell.agents.literature_discovery.agent as agent_module

    monkeypatch.setattr(
        agent_module, "EuropePmcProvider", lambda *a, **k: _SearchFailingProvider(error)
    )
    # JSON mode keeps the status readable while still exiting non-zero.
    assert cli_main(["literature", "discover", "--query", "TERT", "--format", "json"]) == 1
    assert json.loads(capsys.readouterr().out)["run_status"] == expected_status

    # ...as does --output file mode.
    out_file = tmp_path / "bundle.json"
    assert cli_main(["literature", "discover", "--query", "TERT", "--output", str(out_file)]) == 1
    capsys.readouterr()
    assert json.loads(out_file.read_text(encoding="utf-8"))["run_status"] == expected_status


def test_cli_literature_discover_zero_results_still_exits_zero(capsys, monkeypatch) -> None:
    class _EmptyProvider:
        name = "fake"

        def search(self, query):
            return LiteratureSearchResult(
                provenance=ProviderProvenance(
                    provider="fake",
                    query_sent="q",
                    retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
                    hit_count=0,
                ),
                articles=[],
            )

        def fetch_record(self, identifier):  # pragma: no cover - unused
            raise NotImplementedError

        def fetch_open_full_text(self, identifier):  # pragma: no cover - unused
            return None

    import virtualcell.agents.literature_discovery.agent as agent_module

    monkeypatch.setattr(agent_module, "EuropePmcProvider", lambda *a, **k: _EmptyProvider())
    assert cli_main(["literature", "discover", "--query", "TERT"]) == 0
    capsys.readouterr()


# --- 3. snapshot observations survive -----------------------------------------

_SNAPSHOT = {
    "domain": "immortalization",
    "task": "assess_state",
    "experiment": {
        "intent": "immortalization_assessment",
        "PDL_trend": "plateau",
        "DT_trend": "worsening",
        "gammaH2AX": "high",
        "SA_b_gal": "high",
        "p21": "high",
        "adipogenic_retention": "lost",
    },
}


def test_snapshot_observations_survive_the_adapter() -> None:
    response = ImmortalizationDomainPack().execute(
        ReasoningQuery.model_validate(_SNAPSHOT), _store()
    )
    observed = " ".join(response.observations)
    for axis, value in [
        ("PDL_trend", "plateau"),
        ("DT_trend", "worsening"),
        ("gammaH2AX", "high"),
        ("SA_b_gal", "high"),
        ("p21", "high"),
        ("adipogenic_retention", "lost"),
    ]:
        assert f"{axis}={value}" in observed, f"{axis} disappeared from observations"
    # Unmeasured axes are omitted rather than guessed.
    assert "p16=" not in observed


def test_snapshot_observations_survive_the_api() -> None:
    with TestClient(app) as client:
        response = client.post("/reasoning/query", json=_SNAPSHOT)
    body = ReasoningResponse.model_validate(response.json())
    observed = " ".join(body.observations)
    assert "PDL_trend=plateau" in observed and "gammaH2AX=high" in observed


def test_normalized_input_is_preserved_for_audit() -> None:
    response = ImmortalizationDomainPack().execute(
        ReasoningQuery.model_validate(_SNAPSHOT), _store()
    )
    recorded = response.domain_details["assessment_input"]
    # The validated input the assessment actually consumed, not the raw request.
    assert recorded["PDL_trend"] == "plateau"
    assert recorded["adipogenic_retention"] == "lost"
    assert recorded["intent"] == "immortalization_assessment"


def test_derived_series_values_are_marked_and_take_precedence() -> None:
    payload = {
        "domain": "immortalization",
        "task": "assess_state",
        "experiment": {
            "intent": "immortalization_assessment",
            "PDL_trend": "increasing",
            "observations": [
                {"passage": 25, "culture_day": 100, "cumulative_PDL": 30.0, "DT_hours": 42},
                {"passage": 30, "culture_day": 130, "cumulative_PDL": 33.0, "DT_hours": 58},
                {"passage": 35, "culture_day": 165, "cumulative_PDL": 34.0, "DT_hours": 80},
            ],
        },
    }
    response = ImmortalizationDomainPack().execute(ReasoningQuery.model_validate(payload), _store())
    observed = " ".join(response.observations)
    assert "derived from series" in observed
    assert "trajectory=" in observed


# --- 4. contradictory task/intent combinations --------------------------------


@pytest.mark.parametrize(
    "task,intent",
    [
        ("explain_mechanism", "hypothesis_handling"),
        ("handle_hypothesis", "mechanism_explanation"),
        ("assess_state", "mechanism_explanation"),
        ("assess_state", "hypothesis_handling"),
    ],
)
def test_conflicting_task_and_intent_is_rejected(task: str, intent: str) -> None:
    query = ReasoningQuery(
        domain="immortalization",
        task=task,
        experiment={"intent": intent, "construct": "TERT_only"},
    )
    with pytest.raises(QueryValidationError):
        ImmortalizationDomainPack().execute(query, _store())


def test_matching_task_and_intent_is_accepted() -> None:
    query = ReasoningQuery(
        domain="immortalization",
        task="explain_mechanism",
        experiment={"intent": "mechanism_explanation", "construct": "TERT_only"},
    )
    assert ImmortalizationDomainPack().execute(query, _store()).summary


def test_api_reports_a_task_intent_conflict_as_422() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/reasoning/query",
            json={
                "domain": "immortalization",
                "task": "explain_mechanism",
                "experiment": {"intent": "hypothesis_handling"},
            },
        )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "invalid_query"


# --- 5. LiteratureOutcome invariant is structural ------------------------------


@pytest.mark.parametrize(
    "status",
    [
        LiteratureStatus.NOT_REQUESTED,
        LiteratureStatus.UNAVAILABLE,
        LiteratureStatus.ZERO_RESULTS,
        LiteratureStatus.PROVIDER_ERROR,
        LiteratureStatus.TIMEOUT,
    ],
)
def test_evidence_on_a_non_success_status_is_rejected(status: LiteratureStatus) -> None:
    claim = Claim(statement="x", tier=EvidenceTier.HYPOTHESIS)
    with pytest.raises(ValidationError, match="only valid with status 'success'"):
        LiteratureOutcome(status=status, evidence=[claim])


def test_evidence_on_success_is_allowed() -> None:
    claim = Claim(statement="x", tier=EvidenceTier.HYPOTHESIS)
    assert LiteratureOutcome(status=LiteratureStatus.SUCCESS, evidence=[claim]).evidence


def test_failure_statuses_may_carry_detail_without_evidence() -> None:
    outcome = LiteratureOutcome(status=LiteratureStatus.TIMEOUT, detail="too slow")
    assert outcome.evidence == [] and outcome.detail == "too slow"


# --- 6. unknown top-level request fields --------------------------------------


@pytest.mark.parametrize(
    "field", ["allow_litrature", "explanation_lvl", "targets", "experiments", "Domain"]
)
def test_unknown_top_level_field_is_rejected(field: str) -> None:
    # A misspelled control field would otherwise silently keep its default and change
    # what the platform does, with no signal to the caller.
    with pytest.raises(ValidationError):
        ReasoningQuery.model_validate(
            {"domain": "immortalization", "task": "assess_state", field: "x"}
        )


def test_experiment_stays_an_open_mapping() -> None:
    query = ReasoningQuery.model_validate(
        {
            "domain": "immortalization",
            "task": "assess_state",
            "experiment": {"anything_the_domain_defines": 1, "nested": {"ok": True}},
        }
    )
    assert query.experiment["anything_the_domain_defines"] == 1


def test_api_rejects_an_unknown_field_with_422() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/reasoning/query",
            json={
                "domain": "immortalization",
                "task": "assess_state",
                "allow_litrature": True,
            },
        )
    assert response.status_code == 422
