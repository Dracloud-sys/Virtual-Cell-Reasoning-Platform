"""The remote door: the same six tools over Streamable HTTP, for one person, behind OAuth.

A custom connector reaches this server from the host's cloud, so whatever the transport
serves, it serves to the internet. Three claims carry the weight here, and each has a quiet
way of becoming false.

**Nothing is served without a verified token for the one configured person.** Missing
settings stop the process before it binds. A token that is expired, forged, issued by
someone else, issued for another resource, short of scope, or issued to another subject is
a 401/403 - never a degraded answer. The Host header is checked, and is never identity.

**A host can find its way to login on its own.** The 401 names the protected resource
metadata, and that document names this server's exact URL and the authorization server.
If either drifts, the connector fails with "couldn't reach the server" and nothing here
would have said why.

**The tools are the stdio tools.** Same ``build_server``, same six tools; a restart loses
the issued-evidence record and says so rather than vouching for what it cannot, and a
second search re-issues the same id.

What this file does NOT prove: that a real authorization server issues tokens this
verifier accepts, or that a real host completes the login. Those need real accounts and a
public address, and are recorded as not yet run in ``docs/remote_mcp.md``.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import time
from datetime import UTC, datetime
from typing import Any

import pytest

remote = pytest.importorskip(
    "virtualcell.mcp.remote", reason="the HTTP transport needs the optional 'mcp' extra"
)
mcp_server = pytest.importorskip("virtualcell.mcp.server")

import anyio  # noqa: E402
import httpx2  # noqa: E402
import jwt  # noqa: E402
import uvicorn  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from virtualcell.core.contracts import AgentInput, AgentOutput  # noqa: E402
from virtualcell.literature.contracts import (  # noqa: E402
    ArticleIdentifier,
    ArticleRecord,
    DiscoveryRunStatus,
    LiteratureEvidenceBundle,
    LiteratureQuery,
    ProviderProvenance,
)

RESOURCE = "https://vcrp.test/mcp"
ISSUER = "https://tenant.example/"
SUBJECT = "auth0|the-one-owner"
SCOPE = "vcrp:use"
METADATA_URL = "https://vcrp.test/.well-known/oauth-protected-resource/mcp"
TOOL_NAMES = sorted(
    [
        "list_domains",
        "describe_domain",
        "reason",
        "research_evidence",
        "read_evidence_source",
        "check_research_draft",
        "compare_research_observations",
    ]
)

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _Keys:
    """Stands in for the issuer's published key set: one key, under kid ``k1``."""

    def __init__(self, fail: Exception | None = None) -> None:
        self._fail = fail

    def get_signing_key_from_jwt(self, token: str) -> Any:
        if self._fail is not None:
            raise self._fail
        kid = jwt.get_unverified_header(token).get("kid")
        if kid != "k1":
            raise jwt.PyJWKClientError(f"no key {kid!r}")

        class _Signing:
            key = _KEY.public_key()

        return _Signing()


def _env(**overrides: str) -> dict[str, str]:
    env = {
        remote.ENV_RESOURCE_URL: RESOURCE,
        remote.ENV_ISSUER: ISSUER,
        remote.ENV_ALLOWED_SUBJECT: SUBJECT,
        remote.ENV_REQUIRED_SCOPES: SCOPE,
    }
    env.update(overrides)
    return env


def _settings(**overrides: str):
    return remote.RemoteSettings.from_env(_env(**overrides))


def _token(*, key=_KEY, kid: str = "k1", algorithm: str = "RS256", **claims: Any) -> str:
    """A token as the issuer would mint it; pass ``claim=None`` to leave a claim out."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": ISSUER,
        # Auth0 adds its userinfo audience beside the API's when `openid` is requested.
        "aud": [RESOURCE, ISSUER + "userinfo"],
        "sub": SUBJECT,
        "iat": now,
        "exp": now + 600,
        "scope": f"openid offline_access {SCOPE}",
        "azp": "claude-connector-client",
    }
    payload.update(claims)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, key, algorithm=algorithm, headers={"kid": kid})


def _app(settings=None, *, keys=None, **server_kwargs):
    return remote.build_http_app(settings or _settings(), keys=keys or _Keys(), **server_kwargs)


_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def _rpc(client: TestClient, method: str, params: dict | None = None, *, token: str | None):
    """POST one JSON-RPC request; return (status, message or None, response)."""
    headers = dict(_HEADERS)
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    response = client.post("/mcp", json=body, headers=headers)
    message = None
    if response.status_code == 200:
        data = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
        message = json.loads(data[-1]) if data else response.json()
    return response.status_code, message, response


def _call(client: TestClient, tool: str, arguments: dict, token: str) -> dict[str, Any]:
    status, message, _ = _rpc(
        client, "tools/call", {"name": tool, "arguments": arguments}, token=token
    )
    assert status == 200, status
    result = message["result"]
    assert not result.get("isError"), result
    return result["structuredContent"]


# --- a literature agent with no network, the same shape the stdio tests use ------------------


def _bundle(articles: list[ArticleRecord]) -> LiteratureEvidenceBundle:
    return LiteratureEvidenceBundle(
        query=LiteratureQuery(query_text="q"),
        provider_provenance=ProviderProvenance(
            provider="stub", query_sent="q", retrieved_at=datetime.now(UTC)
        ),
        run_status=DiscoveryRunStatus.SUCCESS,
        articles=articles,
    )


class _SequentialLiterature:
    def __init__(self, *article_sets: list[ArticleRecord]) -> None:
        self._sets = list(article_sets)
        self.calls = 0

    async def run(self, inputs: AgentInput) -> AgentOutput:
        articles = self._sets[min(self.calls, len(self._sets) - 1)]
        self.calls += 1
        return AgentOutput(
            agent="stub",
            claims=[],
            confidence=0.0,
            notes="",
            result=_bundle(articles).model_dump(mode="json"),
        )


_DEGRADATION = ArticleRecord(
    identifiers=ArticleIdentifier(doi="10.1000/scaffold-degradation"),
    title="Scaffold degradation kinetics in dermal repair",
    abstract="Mass loss reached 60% by day 14 while hydroxyproline accumulation lagged.",
)
_DEPOSITION = ArticleRecord(
    identifiers=ArticleIdentifier(doi="10.1000/collagen-deposition"),
    title="New collagen in construct and medium",
    abstract="Newly synthesised collagen was recovered from both the construct and the medium.",
)


def _draft(evidence: list[dict]) -> dict[str, Any]:
    return {
        "question": "Should new collagen be measured in both the construct and the medium?",
        "hypotheses": [],
        "experiments": [],
        "evidence_used": [item["id"] for item in evidence],
        "evidence": evidence,
    }


# =========================================================================================
# 1. Missing or malformed settings stop the process before anything listens
# =========================================================================================


def test_http_mode_refuses_to_start_without_its_access_settings() -> None:
    with pytest.raises(remote.RemoteConfigError) as caught:
        remote.RemoteSettings.from_env({})
    message = str(caught.value)
    for name in (
        remote.ENV_RESOURCE_URL,
        remote.ENV_ISSUER,
        remote.ENV_ALLOWED_SUBJECT,
        remote.ENV_REQUIRED_SCOPES,
    ):
        assert name in message, "every missing setting is reported, not just the first"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (remote.ENV_RESOURCE_URL, "http://vcrp.test/mcp"),  # plain http off loopback
        (remote.ENV_RESOURCE_URL, "https://vcrp.test/"),  # not the path the tools are on
        (remote.ENV_RESOURCE_URL, "https://vcrp.test/mcp/"),  # a slash the host would not type
        (remote.ENV_RESOURCE_URL, "https://vcrp.test/mcp?x=1"),
        (remote.ENV_ISSUER, "http://tenant.example/"),
        (remote.ENV_ALLOWED_SUBJECT, "auth0|a auth0|b"),  # one person, not a list
        (remote.ENV_REQUIRED_SCOPES, " , "),
        (remote.ENV_PORT, "not-a-port"),
    ],
)
def test_a_malformed_setting_is_refused_not_guessed(name: str, value: str) -> None:
    with pytest.raises(remote.RemoteConfigError) as caught:
        remote.RemoteSettings.from_env(_env(**{name: value}))
    assert name in str(caught.value)


def test_the_http_entry_point_exits_before_binding_when_unconfigured(monkeypatch) -> None:
    for name in (
        remote.ENV_RESOURCE_URL,
        remote.ENV_ISSUER,
        remote.ENV_ALLOWED_SUBJECT,
        remote.ENV_REQUIRED_SCOPES,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        mcp_server.sys, "argv", ["virtualcell.mcp", "--transport", "streamable-http"]
    )

    def _never(*args, **kwargs):
        raise AssertionError("the server bound a port without its access settings")

    monkeypatch.setattr(uvicorn, "run", _never)
    with pytest.raises(SystemExit) as caught:
        mcp_server.main()
    assert caught.value.code == 2


def test_a_configured_http_entry_point_runs_exactly_one_worker(monkeypatch) -> None:
    for name, value in _env(**{remote.ENV_HOST: "0.0.0.0", remote.ENV_PORT: "10000"}).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(mcp_server.sys, "argv", ["virtualcell.mcp", "--transport=streamable-http"])
    seen: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: seen.update(kwargs))

    mcp_server.main()

    assert seen["workers"] == 1
    assert seen["host"] == "0.0.0.0"
    assert seen["port"] == 10000


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["virtualcell.mcp"], "stdio"),
        (["virtualcell.mcp", "--literature"], "stdio"),
        (["virtualcell.mcp", "--transport", "streamable-http"], "streamable-http"),
        (["virtualcell.mcp", "--transport=stdio"], "stdio"),
    ],
)
def test_the_transport_defaults_to_stdio(argv: list[str], expected: str) -> None:
    assert mcp_server.transport_from_argv(argv) == expected


@pytest.mark.parametrize(
    "argv",
    [["virtualcell.mcp", "--transport", "http"], ["virtualcell.mcp", "--transport"]],
)
def test_an_unknown_transport_stops_rather_than_falling_back(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        mcp_server.transport_from_argv(argv)


def test_the_stdio_entry_point_is_unchanged(monkeypatch) -> None:
    """The committed `.mcp.json` passes no transport; it must still start stdio, and must
    not touch the HTTP module at all."""
    monkeypatch.setattr(mcp_server.sys, "argv", ["virtualcell.mcp", "--literature"])
    seen: list[str] = []
    monkeypatch.setattr(
        mcp_server.MCPServer, "run", lambda self, transport="stdio", **kw: seen.append(transport)
    )

    def _never(**kwargs):
        raise AssertionError("stdio started the HTTP transport")

    monkeypatch.setattr(remote, "serve", _never)
    mcp_server.main()
    assert seen == ["stdio"]


# =========================================================================================
# 2. A host can discover where to log in
# =========================================================================================


def test_the_protected_resource_metadata_names_this_url_and_the_issuer_exactly() -> None:
    """The host compares `resource` with the URL the user typed, character for character,
    and uses the first authorization server listed."""
    with TestClient(_app(), base_url="https://vcrp.test") as client:
        response = client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    document = response.json()
    assert document["resource"] == RESOURCE
    assert document["authorization_servers"] == [ISSUER]
    assert document["scopes_supported"] == [SCOPE]


def test_an_unauthenticated_request_is_a_401_that_points_at_the_metadata() -> None:
    with TestClient(_app(), base_url="https://vcrp.test") as client:
        status, _, response = _rpc(client, "tools/list", token=None)
    assert status == 401
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert f'resource_metadata="{METADATA_URL}"' in challenge


# =========================================================================================
# 3. Only a verified token for the one configured person gets through
# =========================================================================================


def _hs256() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": ISSUER, "aud": RESOURCE, "sub": SUBJECT, "exp": now + 600, "scope": SCOPE},
        "a-shared-secret-anyone-could-guess-32b",
        algorithm="HS256",
        headers={"kid": "k1"},
    )


@pytest.mark.parametrize(
    ("case", "make"),
    [
        ("expired", lambda: _token(exp=int(time.time()) - 60)),
        ("forged: signed by another key under the right kid", lambda: _token(key=_OTHER_KEY)),
        ("unknown key id", lambda: _token(kid="k2")),
        ("wrong issuer", lambda: _token(iss="https://other-tenant.example/")),
        ("issuer spelled without its trailing slash", lambda: _token(iss=ISSUER.rstrip("/"))),
        ("audience of another API", lambda: _token(aud="https://other.example/api")),
        ("audience only the issuer's userinfo", lambda: _token(aud=ISSUER + "userinfo")),
        ("another person with a valid token", lambda: _token(sub="auth0|someone-else")),
        ("no subject", lambda: _token(sub=None)),
        ("no expiry", lambda: _token(exp=None)),
        ("shared-secret algorithm", _hs256),
        ("not a JWT", lambda: "opaque-access-token"),
    ],
)
def test_a_token_that_does_not_verify_is_refused(case: str, make) -> None:
    with TestClient(_app(), base_url="https://vcrp.test") as client:
        status, message, response = _rpc(client, "tools/list", token=make())
    assert status == 401, case
    assert message is None
    assert f'resource_metadata="{METADATA_URL}"' in response.headers["www-authenticate"]


def test_a_token_short_of_the_required_scope_is_a_403() -> None:
    with TestClient(_app(), base_url="https://vcrp.test") as client:
        status, _, response = _rpc(client, "tools/list", token=_token(scope="openid profile"))
    assert status == 403
    assert 'error="insufficient_scope"' in response.headers["www-authenticate"]


def test_an_unreachable_key_set_refuses_rather_than_trusting() -> None:
    keys = _Keys(fail=jwt.PyJWKClientConnectionError("key set unreachable"))
    with TestClient(_app(keys=keys), base_url="https://vcrp.test") as client:
        status, _, _ = _rpc(client, "tools/list", token=_token())
    assert status == 401


def test_the_host_header_is_checked_but_never_grants_access() -> None:
    with TestClient(_app(), base_url="https://vcrp.test") as client:
        right_host_no_token, _, _ = _rpc(client, "tools/list", token=None)
        headers = {**_HEADERS, "authorization": f"Bearer {_token()}", "host": "elsewhere.test"}
        wrong_host = client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers
        )
    assert right_host_no_token == 401
    assert wrong_host.status_code == 421


def test_initialize_list_tools_and_call_tool_over_http() -> None:
    token = _token()
    with TestClient(_app(), base_url="https://vcrp.test") as client:
        init_status, init, _ = _rpc(
            client,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
            token=token,
        )
        list_status, listed, _ = _rpc(client, "tools/list", token=token)
        evidence = _call(client, "research_evidence", {"question": "collagen in medium"}, token)

    assert init_status == list_status == 200
    assert init["result"]["serverInfo"]["name"] == mcp_server.SERVER_NAME
    assert sorted(t["name"] for t in listed["result"]["tools"]) == TOOL_NAMES
    assert evidence["question"] == "collagen in medium"


# =========================================================================================
# 4. The research door behaves over HTTP exactly as it does over stdio
# =========================================================================================


def test_two_searches_are_read_and_checked_as_server_retrieved_over_http() -> None:
    token = _token()
    app = _app(literature_agent=_SequentialLiterature([_DEGRADATION], [_DEPOSITION]))
    with TestClient(app, base_url="https://vcrp.test") as client:
        first = _call(
            client,
            "research_evidence",
            {"question": "degradation", "search_literature": True},
            token,
        )["evidence"]
        second = _call(
            client,
            "research_evidence",
            {"question": "deposition", "search_literature": True},
            token,
        )["evidence"]
        read = _call(client, "read_evidence_source", {"evidence_id": second[0]["id"]}, token)
        check = _call(client, "check_research_draft", _draft(first + second), token)

    assert first[0]["id"] != second[0]["id"]
    assert read["status"] == "ok"
    assert "construct and the medium" in read["evidence"][0]["locator"]["source_text"]
    assert {row["origin"] for row in check["evidence_origins"]} == {"server_retrieved"}
    assert check["scientific_validity_checked"] is False


def test_a_restart_loses_the_record_and_says_so_then_a_new_search_restores_it() -> None:
    """A free host stops and restarts the process. The new process must not vouch for an id
    it did not issue - and searching again re-issues the same content-derived id."""
    token = _token()
    with TestClient(
        _app(literature_agent=_SequentialLiterature([_DEPOSITION])), base_url="https://vcrp.test"
    ) as before:
        issued = _call(
            before,
            "research_evidence",
            {"question": "deposition", "search_literature": True},
            token,
        )["evidence"]

    restarted = _app(literature_agent=_SequentialLiterature([_DEPOSITION]))
    with TestClient(restarted, base_url="https://vcrp.test") as after:
        lost = _call(after, "read_evidence_source", {"evidence_id": issued[0]["id"]}, token)
        unvouched = _call(after, "check_research_draft", _draft(issued), token)
        again = _call(
            after, "research_evidence", {"question": "deposition", "search_literature": True}, token
        )["evidence"]
        reread = _call(after, "read_evidence_source", {"evidence_id": issued[0]["id"]}, token)
        vouched = _call(after, "check_research_draft", _draft(issued), token)

    assert lost["status"] == "not_issued"
    assert "research_evidence" in lost["detail"], "the refusal names the way back"
    assert unvouched["evidence_origins"][0]["origin"] == "host_supplied"
    assert again[0]["id"] == issued[0]["id"], "a re-search re-issues the same id"
    assert reread["status"] == "ok"
    assert vouched["evidence_origins"][0]["origin"] == "server_retrieved"


# =========================================================================================
# 5. A real local HTTP server and a real SDK client, and a real stdio process
# =========================================================================================


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_a_real_client_over_a_real_local_http_server() -> None:
    """uvicorn on loopback and the SDK's own streamable-HTTP client. This is the whole
    transport short of TLS and a real authorization server - neither of which a test on
    this machine can honestly stand in for."""
    port = _free_port()
    resource = f"http://127.0.0.1:{port}/mcp"
    settings = remote.RemoteSettings.from_env(_env(**{remote.ENV_RESOURCE_URL: resource}))
    app = remote.build_http_app(
        settings,
        keys=_Keys(),
        literature_agent=_SequentialLiterature([_DEGRADATION], [_DEPOSITION]),
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, workers=1, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        assert time.monotonic() < deadline, "the local server did not start"
        time.sleep(0.05)

    token = _token(aud=resource)
    out: dict[str, Any] = {}

    async def exchange() -> None:
        async with httpx2.AsyncClient() as bare:
            refused = await bare.post(resource, json={"jsonrpc": "2.0", "id": 1, "method": "x"})
            out["unauthenticated"] = refused.status_code
            out["metadata"] = (
                await bare.get(f"http://127.0.0.1:{port}/.well-known/oauth-protected-resource/mcp")
            ).json()
        async with (
            httpx2.AsyncClient(headers={"authorization": f"Bearer {token}"}) as authed,
            streamable_http_client(resource, http_client=authed) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            out["tools"] = sorted(t.name for t in (await session.list_tools()).tools)
            first = await session.call_tool(
                "research_evidence", {"question": "degradation", "search_literature": True}
            )
            second = await session.call_tool(
                "research_evidence", {"question": "deposition", "search_literature": True}
            )
            items = first.structured_content["evidence"] + second.structured_content["evidence"]
            read_back = await session.call_tool(
                "read_evidence_source", {"evidence_id": items[1]["id"]}
            )
            check = await session.call_tool("check_research_draft", _draft(items))
            out["read"] = read_back.structured_content["status"]
            out["origins"] = [r["origin"] for r in check.structured_content["evidence_origins"]]

    try:
        anyio.run(exchange)
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert out["unauthenticated"] == 401
    assert out["metadata"]["resource"] == resource
    assert out["tools"] == TOOL_NAMES
    assert out["read"] == "ok"
    assert out["origins"] == ["server_retrieved", "server_retrieved"]


def test_the_stdio_process_still_serves_the_same_tools() -> None:
    """The committed command, spawned as a host spawns it."""
    out: dict[str, Any] = {}

    async def exchange() -> None:
        params = StdioServerParameters(command=sys.executable, args=["-m", "virtualcell.mcp"])
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            init = await session.initialize()
            out["name"] = init.server_info.name
            out["tools"] = sorted(t.name for t in (await session.list_tools()).tools)

    asyncio.run(asyncio.wait_for(exchange(), timeout=60))
    assert out["name"] == mcp_server.SERVER_NAME
    assert out["tools"] == TOOL_NAMES
