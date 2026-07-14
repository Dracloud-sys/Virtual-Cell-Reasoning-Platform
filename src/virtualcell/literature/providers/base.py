"""Provider protocol and an injectable HTTP transport.

Networking is behind a small :class:`HttpTransport` protocol so the connectors are
testable with a fake transport and never touch the network in tests. The default
transport uses the standard library (``urllib``) — no new runtime dependency — with
an explicit timeout and a descriptive User-Agent.

A transport/network failure raises :class:`ProviderError`; an HTTP error status is
returned as an :class:`HttpResponse` so a connector can distinguish a provider
failure from a legitimately empty result set.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from virtualcell.literature.contracts import (
    ArticleIdentifier,
    ArticleRecord,
    LiteratureQuery,
    LiteratureSearchResult,
)

_DEFAULT_USER_AGENT = (
    "virtualcell-literature/0.1 (+https://github.com/Dracloud-sys/Virtual-Cell-Reasoning-Platform)"
)
_DEFAULT_TIMEOUT = 10.0


class ProviderError(RuntimeError):
    """A transport/provider failure — distinct from a search that returned no hits."""


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    text: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


@runtime_checkable
class HttpTransport(Protocol):
    def get(
        self, url: str, *, headers: dict[str, str] | None = None, timeout: float = _DEFAULT_TIMEOUT
    ) -> HttpResponse: ...


class UrllibTransport:
    """Default transport over ``urllib`` (stdlib). Real network; not used in tests."""

    def __init__(self, user_agent: str = _DEFAULT_USER_AGENT) -> None:
        self.user_agent = user_agent

    def get(
        self, url: str, *, headers: dict[str, str] | None = None, timeout: float = _DEFAULT_TIMEOUT
    ) -> HttpResponse:
        request = urllib.request.Request(
            url, headers={"User-Agent": self.user_agent, **(headers or {})}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    status_code=response.status,
                    text=response.read().decode("utf-8", "replace"),
                )
        except urllib.error.HTTPError as exc:
            # An HTTP error carries a status; hand it back so the caller decides.
            body = exc.read().decode("utf-8", "replace") if exc.fp else ""
            return HttpResponse(status_code=exc.code, text=body)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"transport error fetching {url}: {exc}") from exc


@runtime_checkable
class LiteratureProvider(Protocol):
    """A source of article metadata and (where open access) full text."""

    name: str

    def search(self, query: LiteratureQuery) -> LiteratureSearchResult: ...

    def fetch_record(self, identifier: ArticleIdentifier) -> ArticleRecord: ...

    def fetch_open_full_text(self, identifier: ArticleIdentifier) -> str | None: ...
