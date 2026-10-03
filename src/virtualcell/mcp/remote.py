"""The same MCP server over Streamable HTTP, for a host that connects by URL.

    Claude custom connector  --HTTPS-->  /mcp  ->  build_server()  ->  the six tools

A connector added by URL reaches this server from the host's cloud, not from the user's
machine, so the stdio door cannot serve it. This module adds the transport and the access
control a public address needs, and nothing else: the server is ``build_server`` - the same
function, the same six tools, the same research logic - and no tool is copied or wrapped.

**Access is one person's.** The host discovers the authorization server from the protected
resource metadata this module publishes, signs its user in there, and sends the access
token it gets back. Every request to ``/mcp`` is then checked here: the signature against
the issuer's published keys, the issuer, the audience (this server's exact URL), the
expiry, the scope, and finally that the token names the one ``(issuer, subject)`` pair this
deployment was configured for. A valid token for anyone else is refused. The login itself
never happens here; this is a resource server and holds no credentials.

**Missing configuration stops the process.** An HTTP server that started without its access
settings would serve the tools to the internet, so :func:`serve` refuses to bind until every
setting is present and well formed. Neither the Host header nor a session id is ever treated
as identity; the transport runs stateless, so there is no session id to lean on.

**One process, one worker.** The record of what this server issued
(``research_payloads.IssuedEvidence``) and the fetched-body cache live in this process.
A second worker or instance would each hold a different record, and a restart empties it.
That is recoverable by design - an id this process did not issue reads back as
``not_issued`` / ``host_supplied``, and ids are content-derived, so searching again re-issues
the same id - and it is why this runs as exactly one worker.

The protocol SDK is imported here and in ``server.py`` only; the stdio path never imports
this module.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import jwt
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

logger = logging.getLogger(__name__)

#: The one path the tools are served on. The resource URL must end in it exactly, because
#: the host compares the metadata's `resource` with the URL the user typed, character for
#: character.
MCP_PATH = "/mcp"

ENV_RESOURCE_URL = "VCRP_MCP_RESOURCE_URL"
ENV_ISSUER = "VCRP_MCP_OAUTH_ISSUER"
ENV_ALLOWED_SUBJECT = "VCRP_MCP_ALLOWED_SUBJECT"
ENV_REQUIRED_SCOPES = "VCRP_MCP_REQUIRED_SCOPES"
ENV_JWKS_URL = "VCRP_MCP_JWKS_URL"
ENV_HOST = "VCRP_MCP_HOST"
ENV_PORT = "PORT"

#: Asymmetric only. Accepting a shared-secret algorithm would let anyone holding the
#: public key mint a token, and `none` would let anyone at all.
ALGORITHMS = ("RS256",)

#: Origins a browser-originated request may carry. The Origin check exists against DNS
#: rebinding from a web page; a request with no Origin (a server-to-server call) passes it,
#: and a bearer token is still required either way.
HOST_ORIGINS = ("https://claude.ai", "https://claude.com")

_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


class RemoteConfigError(ValueError):
    """The HTTP transport was asked for without the settings that make it safe to expose."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__(
            "refusing to serve over HTTP: " + "; ".join(problems) + ". Nothing was started."
        )


@dataclass(frozen=True)
class RemoteSettings:
    resource_url: str
    issuer: str
    allowed_subject: str
    required_scopes: tuple[str, ...]
    jwks_url: str
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def public_host(self) -> str:
        """The Host header a legitimate request carries: the resource URL's authority."""
        return urlsplit(self.resource_url).netloc

    @property
    def public_origin(self) -> str:
        parts = urlsplit(self.resource_url)
        return f"{parts.scheme}://{parts.netloc}"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> RemoteSettings:
        """Read every setting, and report every problem at once rather than the first."""
        problems: list[str] = []

        def required(name: str) -> str:
            value = (env.get(name) or "").strip()
            if not value:
                problems.append(f"{name} is not set")
            return value

        resource_url = required(ENV_RESOURCE_URL)
        issuer = required(ENV_ISSUER)
        subject = required(ENV_ALLOWED_SUBJECT)
        scopes_raw = required(ENV_REQUIRED_SCOPES)

        if resource_url:
            problems.extend(_url_problems(ENV_RESOURCE_URL, resource_url))
            if urlsplit(resource_url).path != MCP_PATH:
                problems.append(
                    f"{ENV_RESOURCE_URL} must end in exactly {MCP_PATH!r} (the path the tools are "
                    f"served on), got path {urlsplit(resource_url).path!r}"
                )
        if issuer:
            problems.extend(_url_problems(ENV_ISSUER, issuer))
        if subject and any(ch.isspace() for ch in subject):
            problems.append(f"{ENV_ALLOWED_SUBJECT} must be one subject, with no whitespace")
        scopes = tuple(s for s in scopes_raw.replace(",", " ").split() if s)
        if scopes_raw and not scopes:
            problems.append(f"{ENV_REQUIRED_SCOPES} names no scope")

        jwks_url = (env.get(ENV_JWKS_URL) or "").strip()
        if not jwks_url and issuer:
            # The issuer's published key set. Auth0 serves it here, and its metadata says so.
            jwks_url = issuer.rstrip("/") + "/.well-known/jwks.json"
        elif jwks_url:
            problems.extend(_url_problems(ENV_JWKS_URL, jwks_url))

        host = (env.get(ENV_HOST) or "127.0.0.1").strip()
        port_raw = (env.get(ENV_PORT) or "8000").strip()
        try:
            port = int(port_raw)
            if not 0 < port < 65536:
                raise ValueError
        except ValueError:
            problems.append(f"{ENV_PORT} must be a TCP port, got {port_raw!r}")
            port = 0

        if problems:
            raise RemoteConfigError(problems)
        return cls(
            resource_url=resource_url,
            issuer=issuer,
            allowed_subject=subject,
            required_scopes=scopes,
            jwks_url=jwks_url,
            host=host,
            port=port,
        )


def _url_problems(name: str, value: str) -> list[str]:
    parts = urlsplit(value)
    problems: list[str] = []
    if parts.scheme == "http" and parts.hostname in _LOOPBACK:
        pass  # a local test server; never reachable from elsewhere
    elif parts.scheme != "https":
        problems.append(f"{name} must be https (http only for a loopback address), got {value!r}")
    if not parts.hostname:
        problems.append(f"{name} has no host: {value!r}")
    if parts.username or parts.password:
        problems.append(f"{name} must not carry credentials")
    if parts.query or parts.fragment:
        problems.append(f"{name} must not carry a query or fragment")
    return problems


class SigningKeySource(Protocol):
    """What :class:`jwt.PyJWKClient` provides; a test supplies its own keys through it."""

    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class OneUserTokenVerifier:
    """Accept a JWT access token only for this resource, from this issuer, for one person.

    Returns ``None`` - which the SDK turns into ``401`` with a ``WWW-Authenticate`` pointing
    at the protected resource metadata - for anything it cannot positively verify, including
    a key set it could not fetch. The reason is logged; the token never is.
    """

    def __init__(self, settings: RemoteSettings, keys: SigningKeySource | None = None) -> None:
        self._settings = settings
        self._keys = keys or jwt.PyJWKClient(
            settings.jwks_url, cache_keys=True, lifespan=3600, timeout=10
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        settings = self._settings
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in ALGORITHMS:
                logger.warning("refused a token signed with %r", header.get("alg"))
                return None
            signing_key = await asyncio.to_thread(self._keys.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(ALGORITHMS),
                audience=settings.resource_url,
                issuer=settings.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except Exception as exc:  # noqa: BLE001 - every failure to verify is a refusal
            logger.warning("refused a token: %s", type(exc).__name__)
            return None

        if claims.get("sub") != settings.allowed_subject:
            logger.warning("refused a valid token for a subject this server does not serve")
            return None

        scope = claims.get("scope")
        scopes = scope.split() if isinstance(scope, str) else []
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("client_id") or ""),
            scopes=scopes,
            expires_at=int(claims["exp"]),
            # Audience was checked above, so the resource is this server's own URL.
            resource=settings.resource_url,
            subject=claims["sub"],
            claims={"iss": claims["iss"]},
        )


def auth_settings(settings: RemoteSettings) -> AuthSettings:
    """What the SDK publishes as protected resource metadata and enforces per request."""
    return AuthSettings(
        issuer_url=settings.issuer,
        resource_server_url=settings.resource_url,
        required_scopes=list(settings.required_scopes),
        validate_token_resource=True,
    )


def transport_security(settings: RemoteSettings) -> TransportSecuritySettings:
    """Refuse a request addressed to another host. This is not identity, the token is."""
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[settings.public_host],
        allowed_origins=[settings.public_origin, *HOST_ORIGINS],
    )


def build_http_app(
    settings: RemoteSettings,
    *,
    keys: SigningKeySource | None = None,
    **server_kwargs: Any,
) -> Any:
    """The ASGI app: ``build_server`` with auth attached, served statelessly on ``/mcp``.

    Stateless because nothing the tools need lives in a protocol session, and because a
    free host that stops and restarts the process would otherwise hand the client a session
    id the new process has never seen.
    """
    from virtualcell.mcp.server import build_server

    server = build_server(
        auth=auth_settings(settings),
        token_verifier=OneUserTokenVerifier(settings, keys),
        **server_kwargs,
    )
    return server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        transport_security=transport_security(settings),
        host=settings.host,
    )


def serve(
    *,
    literature_agent: object | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """Validate, build, and run one worker. Exits before binding if anything is missing."""
    try:
        settings = RemoteSettings.from_env(os.environ if env is None else env)
    except RemoteConfigError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    import uvicorn

    app = build_http_app(settings, literature_agent=literature_agent)
    # One worker, stated rather than defaulted: the issued-evidence record is per process.
    uvicorn.run(app, host=settings.host, port=settings.port, workers=1, server_header=False)
