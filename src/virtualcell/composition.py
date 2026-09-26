"""Optional dependencies an interface may be started with, built in one place.

`virtualcell.mcp` is forbidden by an AST test from importing `virtualcell.agents` at all:
the adapter re-derives no scientific value, owns no vocabulary and names no vertical, and
the rule is enforced rather than described. Its entry point still has to be able to start
the server *with* a literature searcher, because a server that cannot be given one answers
every search request with `not_implemented` however the operator configures it.

Both of those are right, so the wiring goes here rather than in either of them. The MCP
package asks this module for a searcher and never names one; this module names one and
knows nothing about MCP. Widening the test to let the adapter import an agent would have
been one line and would have removed the only thing keeping that boundary true.

`cli.py` and `api/main.py` each still construct their own — they are composition roots
too, and unifying them is a tidy-up for a change that is about them, not this one.
"""

from __future__ import annotations


def default_literature_agent() -> object:
    """The Europe PMC-backed discovery agent the CLI and the API already use.

    Constructing it performs **no I/O**: nothing is contacted until a request actually asks
    for a search. So wiring it in at startup enables the capability without spending
    anything, and a caller still has to pass `search_literature=true` before a single byte
    leaves the machine.
    """
    from virtualcell.agents.literature_discovery.agent import LiteratureDiscoveryAgent

    return LiteratureDiscoveryAgent()
