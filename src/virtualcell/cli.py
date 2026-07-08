"""Command-line interface for the Virtual Cell Reasoning Platform.

Usage:
    virtualcell version
    virtualcell agents
    virtualcell search "<query>"
    virtualcell neighbors <entity_id>
    virtualcell ask "<query>"
    virtualcell qa "<natural-language question>"
    virtualcell explain <entity_id>
    virtualcell ingest reactome --path <UniProt2Reactome.txt> --save graph.json
    virtualcell ingest uniprot  --path <uniprotkb_export.tsv> --load graph.json --save graph.json
    virtualcell qa "..." --load graph.json

Query commands seed the bundled sample dataset unless ``--load <graph.json>`` is
given; ``ingest --save`` persists a graph and ``ingest --load ... --save`` merges
sources into one file.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys

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


def _store(args: argparse.Namespace) -> InMemoryKnowledgeStore:
    """Load a saved graph if ``--load`` was given, otherwise seed the sample data."""
    path = getattr(args, "load", None)
    if path:
        from virtualcell.knowledge.persistence import load_store

        return load_store(path)
    return _seeded_store()


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
    store = _store(args)
    hits = store.search(args.query, k=args.k)
    if not hits:
        print("(no matches)")
        return 0
    for entity in hits:
        print(f"{entity.id}\t{entity.type.value}\t{entity.name}")
    return 0


def _cmd_neighbors(args: argparse.Namespace) -> int:
    store = _store(args)
    if store.get(args.entity_id) is None:
        print(f"entity not found: {args.entity_id}")
        return 1
    for entity in store.neighbors(args.entity_id):
        print(f"{entity.id}\t{entity.type.value}\t{entity.name}")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    from virtualcell.agents.literature.agent import LiteratureAgent

    store = _store(args)
    agent = LiteratureAgent(AgentContext(services={"knowledge_store": store}), store=store)
    output = asyncio.run(agent.run(AgentInput(query=args.query)))
    for claim in output.claims:
        print(f"[{claim.tier.value}] ({claim.confidence:.2f}) {claim.statement}")
    return 0


def _cmd_explain(args: argparse.Namespace) -> int:
    from virtualcell.reasoning.explain import explain

    store = _store(args)
    try:
        result = explain(store, args.entity_id, max_hops=args.hops, top_k=args.k)
    except ValueError as exc:
        print(exc)
        return 1

    print(
        f"Mechanistic reach of {result.seed_id} ({result.seed_name}), "
        f"<= {result.max_hops} hop(s):"
    )
    for link in result.links:
        print(
            f"[{link.tier.value:11}] ({link.confidence:.2f}) {link.hops}-hop  "
            f"{link.target_id}  {link.target_name}"
        )
        print(f"              via: {' | '.join(link.path)}")
    return 0


def _cmd_qa(args: argparse.Namespace) -> int:
    from virtualcell.reasoning.qa import QuestionAnswerer

    store = _store(args)
    result = QuestionAnswerer(store).answer(args.question, k=args.k)
    print(result.answer)
    print(f"\n[backend: {result.backend}]")
    if result.grounded_entity_ids:
        print(f"[grounded in: {', '.join(result.grounded_entity_ids)}]")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    from virtualcell.knowledge.sources.base import load_into

    if args.source == "reactome":
        from virtualcell.knowledge.sources.reactome import ReactomeSource

        source = ReactomeSource(path=args.path, species=args.species)
    elif args.source == "uniprot":
        from virtualcell.knowledge.sources.uniprot import UniProtSource

        source = UniProtSource(path=args.path, species=args.species)
    elif args.source == "intact":
        from virtualcell.knowledge.sources.intact import IntActSource

        source = IntActSource(path=args.path, min_score=args.min_score)
    else:  # pragma: no cover - argparse restricts choices
        print(f"unknown source: {args.source}")
        return 1

    if args.load:
        from virtualcell.knowledge.persistence import load_store

        store = load_store(args.load)
    else:
        store = InMemoryKnowledgeStore()
    try:
        n_entities, n_interactions = load_into(source, store)
    except (OSError, ValueError) as exc:
        print(f"ingest failed: {exc}")
        return 1

    print(
        f"ingested {n_entities} entities, {n_interactions} interactions "
        f"from '{args.source}' ({args.path})"
    )
    if args.save:
        from virtualcell.knowledge.persistence import save_store

        save_store(store, args.save)
        print(f"saved graph to {args.save}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="virtualcell", description="Virtual Cell Reasoning Platform CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="print version").set_defaults(func=_cmd_version)
    sub.add_parser("agents", help="list registered agents").set_defaults(func=_cmd_agents)

    load_help = "load a saved graph JSON instead of the bundled sample"

    p_search = sub.add_parser("search", help="search the knowledge base")
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=10)
    p_search.add_argument("--load", help=load_help)
    p_search.set_defaults(func=_cmd_search)

    p_neighbors = sub.add_parser("neighbors", help="list neighbors of an entity")
    p_neighbors.add_argument("entity_id")
    p_neighbors.add_argument("--load", help=load_help)
    p_neighbors.set_defaults(func=_cmd_neighbors)

    p_ask = sub.add_parser("ask", help="ask the Literature Agent")
    p_ask.add_argument("query")
    p_ask.add_argument("--load", help=load_help)
    p_ask.set_defaults(func=_cmd_ask)

    p_qa = sub.add_parser("qa", help="answer a natural-language question (grounded LLM)")
    p_qa.add_argument("question")
    p_qa.add_argument("-k", type=int, default=5, help="retrieval breadth per term")
    p_qa.add_argument("--load", help=load_help)
    p_qa.set_defaults(func=_cmd_qa)

    p_explain = sub.add_parser("explain", help="evidence-graded mechanistic reach of an entity")
    p_explain.add_argument("entity_id")
    p_explain.add_argument("--hops", type=int, default=2, help="max inference hops (default 2)")
    p_explain.add_argument("-k", type=int, default=25, help="max results to show")
    p_explain.add_argument("--load", help=load_help)
    p_explain.set_defaults(func=_cmd_explain)

    p_ingest = sub.add_parser("ingest", help="ingest a real data source into a knowledge base")
    p_ingest.add_argument("source", choices=["reactome", "uniprot", "intact"])
    p_ingest.add_argument(
        "--path", required=True, help="path to the source file (e.g. UniProt2Reactome.txt)"
    )
    p_ingest.add_argument(
        "--species", default="Homo sapiens", help="species filter (default: Homo sapiens)"
    )
    p_ingest.add_argument(
        "--min-score", type=float, default=0.0, help="min interaction score (intact only)"
    )
    p_ingest.add_argument("--load", help="merge into an existing saved graph JSON")
    p_ingest.add_argument("--save", help="write the resulting graph to a JSON file")
    p_ingest.set_defaults(func=_cmd_ingest)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Biological data (e.g. UniProt protein names) contains non-ASCII characters;
    # force UTF-8 output so printing never crashes on a legacy console codec.
    for stream in (sys.stdout, sys.stderr):
        # pragma: no cover - stream may not be reconfigurable (e.g. when redirected)
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:  # e.g. a missing or invalid --load file
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
