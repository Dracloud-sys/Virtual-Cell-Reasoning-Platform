"""MCP adapter for the platform's reasoning surface.

Three tools - ``list_domains``, ``describe_domain``, ``reason`` - over the same
``ReasoningService`` the API and CLI use. No new request type, no MCP-specific
reasoning path, no re-derivation of anything scientific.

:mod:`virtualcell.mcp.payloads` and :mod:`virtualcell.mcp.guidance` are pure and
import no SDK; :mod:`virtualcell.mcp.server` needs the optional ``mcp`` extra and
is therefore *not* imported here. Import it directly::

    from virtualcell.mcp.server import build_server
"""

from __future__ import annotations

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

__all__ = [
    "DescribeDomainResult",
    "ListDomainsResult",
    "ReasonResult",
    "ToolRefusal",
    "describe_domain",
    "guidance",
    "list_domains",
    "reason",
]
