"""Command-line interface for the Virtual Cell Reasoning Platform.

Usage:
    virtualcell version
    virtualcell agents
    virtualcell search "<query>"
    virtualcell neighbors <entity_id>
    virtualcell ask "<query>"
    virtualcell qa "<natural-language question>"
    virtualcell explain <entity_id>
    virtualcell assess immortalization --input assessment.json [--format json|text]
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
from pathlib import Path

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
        f"Mechanistic reach of {result.seed_id} ({result.seed_name}), <= {result.max_hops} hop(s):"
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


def _print_assessment_text(report) -> None:
    flags = ", ".join(f.value for f in report.flags) or "-"
    print(f"status: {report.candidate_status}   flags: {flags}")
    if report.trajectory is not None:
        t = report.trajectory
        print(
            f"trajectory: {t['state']} "
            f"(PDL {t['derived_PDL_trend']}, DT {t['derived_DT_trend']}, "
            f"DT_fold {t['DT_fold_change']})"
        )
        print(
            f"usable timepoints: PDL={t['usable_PDL_timepoints']} DT={t['usable_DT_timepoints']}"
            f"   applied: {report.derived_input or '-'}"
        )
    print(f"conclusion: {report.conclusion}")

    def _block(label: str, items: list[str]) -> None:
        if items:
            print(f"{label}:")
            for item in items:
                print(f"  - {item}")

    _block("input conflicts", report.input_conflicts)
    _block("blocked overrides", report.blocked_overrides)
    _block("uncertainty", report.uncertainty)
    _block("supporting", [c.statement for c in report.supporting_evidence])
    _block("contradicting", [c.statement for c in report.contradicting_evidence])
    _block("missing axes", report.missing_axes)
    _block("conflict", report.conflict_explanation)
    _block("limitations", report.limitations)
    _block("overinterpretation risk", report.overinterpretation_risk)
    _block("recommended validation", report.recommended_validation)
    _block("next experiment", report.next_experiment)


def _cmd_assess(args: argparse.Namespace) -> int:
    import json

    from pydantic import ValidationError

    from virtualcell.agents.immortalization.adapters import input_from_scenario
    from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
    from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource

    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"could not read input: {exc}")
        return 1
    if not isinstance(payload, dict) or "intent" not in payload:
        print("input must be a JSON object with an 'intent' field")
        return 1

    # A store with the immortalization seed so mechanism/hypothesis reports ground;
    # ``--load`` merges the seed onto an existing saved graph.
    if args.load:
        from virtualcell.knowledge.persistence import load_store

        store = load_store(args.load)
    else:
        store = InMemoryKnowledgeStore()
    load_into(ImmortalizationSeedSource(), store)

    intent = payload["intent"]
    scenario = {key: value for key, value in payload.items() if key != "intent"}
    try:
        data = input_from_scenario(intent, scenario)
        report = ImmortalizationAssessmentAgent(store=store).assess(data)
    except (ValueError, ValidationError) as exc:
        print(f"assessment failed: {exc}")
        return 1

    if args.format == "json":
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        _print_assessment_text(report)
    return 0


def _cmd_literature_discover(args: argparse.Namespace) -> int:
    import json

    from virtualcell.agents.literature_discovery.agent import (
        LiteratureDiscoveryAgent,
        LiteratureQueryError,
    )
    from virtualcell.core.contracts import AgentInput
    from virtualcell.literature.providers.base import ProviderError

    context = {
        "species": args.species or [],
        "cell_types": args.cell_type or [],
        "genes": args.gene or [],
        "phenotypes": args.phenotype or [],
        "assays": args.assay or [],
        "year_from": args.year_from,
        "year_to": args.year_to,
        "open_access_only": args.open_access_only,
        "max_results": args.max_results,
    }
    agent = LiteratureDiscoveryAgent()
    try:
        output = asyncio.run(agent.run(AgentInput(query=args.query, context=context)))
    except LiteratureQueryError as exc:
        print(f"invalid query: {exc}")
        return 1
    except ProviderError as exc:  # pragma: no cover - defensive; agent already catches
        print(f"provider error: {exc}")
        return 1

    result = output.result or {}
    if args.output:
        Path(args.output).write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"wrote discovery bundle to {args.output}")
        return 0
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    prov = result.get("provider_provenance", {})
    print(
        f"provider: {prov.get('provider')}   hits: {prov.get('hit_count')}   note: {output.notes}"
    )
    for rel in result.get("relevance", []):
        ident = rel.get("article", {})
        key = (
            ident.get("pmcid") or ident.get("pmid") or ident.get("doi") or ident.get("provider_id")
        )
        missing = rel.get("missing_critical_filters") or "-"
        print(f"  [{rel.get('total_score'):.2f}] {key}   missing: {missing}")
    return 0


def _cmd_seed(args: argparse.Namespace) -> int:
    from virtualcell.knowledge.sources.base import load_into

    if args.load:
        from virtualcell.knowledge.persistence import load_store

        store = load_store(args.load)
    else:
        store = InMemoryKnowledgeStore()

    if args.name == "immortalization":
        from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource

        n_entities, n_interactions = load_into(ImmortalizationSeedSource(), store)
    else:  # pragma: no cover - argparse restricts choices
        print(f"unknown seed: {args.name}")
        return 1

    print(f"seeded {n_entities} entities, {n_interactions} interactions from '{args.name}'")
    if args.save:
        from virtualcell.knowledge.persistence import save_store

        save_store(store, args.save)
        print(f"saved graph to {args.save}")
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

    p_assess = sub.add_parser("assess", help="run a domain assessment agent on a JSON input file")
    p_assess.add_argument("domain", choices=["immortalization"])
    p_assess.add_argument("--input", required=True, help="path to a JSON assessment input")
    p_assess.add_argument("--format", choices=["json", "text"], default="text")
    p_assess.add_argument("--load", help="merge the seed onto an existing saved graph JSON")
    p_assess.set_defaults(func=_cmd_assess)

    p_lit = sub.add_parser("literature", help="external literature discovery")
    lit_sub = p_lit.add_subparsers(dest="literature_command", required=True)
    p_disc = lit_sub.add_parser(
        "discover", help="discover external papers (metadata + relevance; no claims)"
    )
    p_disc.add_argument("--query", required=True, help="research question / query text")
    p_disc.add_argument("--species", action="append", help="species filter (repeatable)")
    p_disc.add_argument("--cell-type", action="append", help="cell-type filter (repeatable)")
    p_disc.add_argument("--gene", action="append", help="gene filter (repeatable)")
    p_disc.add_argument("--phenotype", action="append", help="phenotype filter (repeatable)")
    p_disc.add_argument("--assay", action="append", help="assay filter (repeatable)")
    p_disc.add_argument("--year-from", type=int)
    p_disc.add_argument("--year-to", type=int)
    p_disc.add_argument("--open-access-only", action="store_true")
    p_disc.add_argument("--max-results", type=int, default=25)
    p_disc.add_argument("--format", choices=["json", "text"], default="text")
    p_disc.add_argument("--output", help="write the discovery bundle as UTF-8 JSON to this path")
    p_disc.set_defaults(func=_cmd_literature_discover)

    p_seed = sub.add_parser("seed", help="build a bundled curated seed graph")
    p_seed.add_argument("name", choices=["immortalization"])
    p_seed.add_argument("--load", help="merge into an existing saved graph JSON")
    p_seed.add_argument("--save", help="write the resulting graph to a JSON file")
    p_seed.set_defaults(func=_cmd_seed)

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
