# Contributing to Virtual Cell Platform

Thank you for your interest. This project aims to build a biologically realistic,
modular, explainable digital cell. Contributions of code, data connectors,
documentation, and scientific review are all welcome.

## Ground rules

1. **Respect the module boundaries.** Every module must be independently replaceable.
   New functionality should be added as an agent or a backend behind an existing
   protocol, not by coupling modules together.
2. **Separate evidence tiers.** Any biological claim produced by code must be tagged
   with an `EvidenceTier` (`established` / `hypothesis` / `speculative`). Never mix
   tiers. See [`docs/evidence-policy.md`](docs/evidence-policy.md).
3. **Type everything.** Public functions require type hints and, where they carry
   data, Pydantic models.
4. **Tests required.** New code needs unit tests. Keep the default test suite free of
   external service dependencies (use the in-memory backend).

## Development setup

```bash
uv sync --extra dev      # or: pip install -e ".[dev]"
pytest
ruff check .
ruff format .
```

## Pull requests

- Branch from `main`, keep PRs focused and small.
- Ensure `pytest` and `ruff check .` pass locally (CI enforces both).
- Describe the biological or architectural rationale in the PR description.
- Reference the relevant roadmap stage from [`docs/roadmap.md`](docs/roadmap.md).

## Commit style

Use concise, imperative commit messages (e.g., `add Reactome source connector`).
