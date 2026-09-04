"""The MCP adapter: a fourth surface, not a new capability.

    API / CLI / MCP  ->  ReasoningService.query()  ->  DomainRegistry  ->  DomainPack

This module registers three tools and does nothing else. It re-derives no
scientific value, owns no vocabulary, branches on no domain, and names no
vertical - everything domain-specific arrives through ``DomainRegistry`` and
``DomainDescription``. Adding a fourth domain must change zero lines in this
package; a test asserts it.

The MCP SDK is an optional dependency (``pip install "virtualcell[mcp]"``). It is
imported here and nowhere else, so the rest of the package - and
:mod:`virtualcell.mcp.payloads` with it - stays importable without it.

Every tool returns exactly one concrete type. A union of "answer or refusal"
would be wrapped by the SDK under a single ``result`` property, and that wrapper
would flatten the field ordering :class:`~virtualcell.mcp.payloads.ReasonResult`
depends on - the ordering is the mitigation for a summarising model dropping the
caveats, so it wins. Anticipated failures travel on the SDK's tool-error channel
instead, carrying a parseable :class:`~virtualcell.mcp.payloads.ToolRefusal`.
"""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.store import KnowledgeStore
from virtualcell.mcp import guidance
from virtualcell.mcp.payloads import (
    DescribeDomainResult,
    ListDomainsResult,
    ReasonResult,
    ToolRefusal,
    describe_domain,
    list_domains,
    reason,
)
from virtualcell.platform.bootstrap import default_registry, seed_registered_domains
from virtualcell.platform.contracts import ReasoningQuery
from virtualcell.platform.domains import (
    DomainRegistry,
    QueryValidationError,
    UnknownDomainError,
    UnsupportedTaskError,
)
from virtualcell.platform.service import ReasoningService

SERVER_NAME = "virtualcell"

SERVER_INSTRUCTIONS = """\
An evidence-graded mechanistic reasoning layer for cell biology. It explains why,
through which pathways, and how confidently - and it refuses to conclude past its
evidence.

Call list_domains, then describe_domain for the domain you want, then reason.
Do not assemble an experiment payload without describing the domain first: axis
names are not guessable, and an unrecognised key is reported back rather than
corrected.

Whatever this server returns, relay its limitations and overinterpretation risks
with its status. Never report a status on its own.\
"""

_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

_LIST_FIRST = "Call list_domains for the registered names."


def _refuse(error: str, detail: str, remedy: str) -> ToolError:
    """Build the SDK error a caller can parse back into a :class:`ToolRefusal`."""
    return ToolError(ToolRefusal(error=error, detail=detail, remedy=remedy).message())


def build_server(
    *,
    registry: DomainRegistry | None = None,
    store: KnowledgeStore | None = None,
    literature_agent: object | None = None,
) -> MCPServer:
    """Build the MCP server over a registry and a seeded knowledge store.

    Both are injectable so a test can register a domain this repository does not
    ship and prove the tools reach it without a change here.
    """
    registry = registry if registry is not None else default_registry()
    if store is None:
        store = InMemoryKnowledgeStore()
        seed_registered_domains(store)

    server: MCPServer = MCPServer(name=SERVER_NAME, instructions=SERVER_INSTRUCTIONS)

    @server.tool(
        name="list_domains",
        description=guidance.LIST_DOMAINS,
        annotations=_READ_ONLY,
    )
    def _list_domains() -> ListDomainsResult:
        return list_domains(registry)

    @server.tool(
        name="describe_domain",
        description=guidance.DESCRIBE_DOMAIN,
        annotations=_READ_ONLY,
    )
    def _describe_domain(domain: str) -> DescribeDomainResult:
        try:
            pack = registry.get(domain)
        except UnknownDomainError as exc:
            raise _refuse("unknown_domain", str(exc), _LIST_FIRST) from exc
        return describe_domain(pack.describe())

    @server.tool(
        name="reason",
        description=guidance.REASON,
        annotations=_READ_ONLY,
    )
    async def _reason(
        domain: str,
        task: str,
        experiment: dict[str, Any] | None = None,
        question: str | None = None,
        allow_literature: bool = False,
    ) -> ReasonResult:
        try:
            query = ReasoningQuery(
                domain=domain,
                task=task,
                experiment=experiment or {},
                question=question,
                allow_literature=allow_literature,
            )
        except ValueError as exc:
            raise _refuse(
                "malformed_query",
                str(exc),
                "Fix the request fields and call reason again.",
            ) from exc

        service = ReasoningService(store, registry, literature_agent=literature_agent)
        try:
            response = await service.query(query)
        except UnknownDomainError as exc:
            raise _refuse("unknown_domain", str(exc), _LIST_FIRST) from exc
        except UnsupportedTaskError as exc:
            raise _refuse(
                "unsupported_task",
                str(exc),
                f"Call describe_domain({domain!r}) for the tasks it supports.",
            ) from exc
        except QueryValidationError as exc:
            raise _refuse(
                "invalid_experiment",
                str(exc),
                (
                    f"Call describe_domain({domain!r}) for the accepted keys and "
                    "vocabularies, then re-send. Do not invent a value for an axis "
                    "you did not measure - send its unmeasured_value instead."
                ),
            ) from exc
        return reason(response)

    return server


def main() -> None:
    """Entry point: serve over stdio."""
    build_server().run(transport="stdio")
