"""Command-line interface for the Virtual Cell Platform.

Usage:
    virtualcell version
    virtualcell agents
    virtualcell search "<query>"
    virtualcell neighbors <entity_id>

The CLI seeds an in-memory knowledge base with the bundled sample dataset.
"""

from __future__ import annotations

import argparse
import asyncio

from virtualcell import __version__
from virtualcell.core.agent import AgentContext
from virtualcell.core.contracts import AgentInput
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.sample import SampleDataSource


def _seeded_store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(SampleDataSource(), store)
    return store


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"virtualcell {__version__}")
    return 0


def _cmd_agents(_: argparse.Namespace) -> int:
    import virtualcell.agents  # noqa: F401  (registers agents)
    from virtualcell.core.registry import registry

    for name in registry.names():
        print(name)
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    store = _seeded_store()
    hits = store.search(args.query, k=args.k)
    if not hits:
        print("(no matches)")
        return 0
    for entity in hits:
        print(f"{entity.id}\t{entity.type.value}\t{entity.name}")
    return 0


def _cmd_neighbors(args: argparse.Namespace) -> int:
    store = _seeded_store()
    if store.get(args.entity_id) is None:
        print(f"entity not found: {args.entity_id}")
        return 1
    for entity in store.neighbors(args.entity_id):
        print(f"{entity.id}\t{entity.type.value}\t{entity.name}")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    from virtualcell.agents.literature.agent import LiteratureAgent

    store = _seeded_store()
    agent = LiteratureAgent(AgentContext(services={"knowledge_store": store}), store=store)
    output = asyncio.run(agent.run(AgentInput(query=args.query)))
    for claim in output.claims:
        print(f"[{claim.tier.value}] ({claim.confidence:.2f}) {claim.statement}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="virtualcell", description="Virtual Cell Platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="print version").set_defaults(func=_cmd_version)
    sub.add_parser("agents", help="list registered agents").set_defaults(func=_cmd_agents)

    p_search = sub.add_parser("search", help="search the knowledge base")
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=10)
    p_search.set_defaults(func=_cmd_search)

    p_neighbors = sub.add_parser("neighbors", help="list neighbors of an entity")
    p_neighbors.add_argument("entity_id")
    p_neighbors.set_defaults(func=_cmd_neighbors)

    p_ask = sub.add_parser("ask", help="ask the Literature Agent")
    p_ask.add_argument("query")
    p_ask.set_defaults(func=_cmd_ask)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
