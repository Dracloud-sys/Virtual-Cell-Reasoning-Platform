# Roadmap

The platform grows through 12 stages. Each stage extends or replaces existing
modules rather than rewriting the system. The guiding rule: prioritize decisions
that move the project closer to a full digital organism.

| Stage | Name | Status |
|------:|------|--------|
| 1 | Cellular Knowledge Base | **In progress (v0.1: working in-memory core)** |
| 2 | AI-assisted Literature Mining | Interface stub (Literature Agent) |
| 3 | Gene Regulatory Network Modeling | Planned |
| 4 | Cell Signaling Network | Interface stub (Signaling Agent) |
| 5 | Epigenetic Regulation | Planned |
| 6 | Metabolic Network | Interface stub (Metabolism Agent) |
| 7 | Protein Interaction Network | Interface stub (Protein Interaction Agent) |
| 8 | Cellular State Prediction | Planned |
| 9 | Digital Cell | Planned |
| 10 | Digital Tissue | Planned |
| 11 | Digital Organ | Planned |
| 12 | Digital Organism | Planned |

## Biological hierarchy respected across stages

```
Genome → Epigenome → Transcriptome → Proteome → Metabolome
       → Cell State → Cell Behavior → Tissue Dynamics
```

## v0.1 scope

- Working Stage 1 knowledge base (in-memory), with graph/vector backends as
  interfaces.
- Full architecture scaffold: agents, orchestration, simulation, API, CLI.
- Reference stub agent (Literature) demonstrating the query → evidence-tagged
  `Claim` flow.

## Near-term (post v0.1)

- Real Neo4j/Qdrant backend implementations wired end-to-end.
- First data-source ingestion (Gene Ontology, Reactome).
- Gene Regulatory Network model (Stage 3) as the first PyTorch-backed agent.
