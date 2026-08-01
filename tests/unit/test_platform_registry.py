"""Domain registry tests (PR11): resolution, explicit rejection, no silent fallback."""

from __future__ import annotations

import pytest

from virtualcell.platform.bootstrap import default_registry
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.domains import (
    DomainRegistry,
    UnknownDomainError,
    UnsupportedTaskError,
)
from virtualcell.platform.packs.immortalization import ImmortalizationDomainPack


class _StubPack:
    """A second domain, proving the registry is not immortalization-shaped."""

    domain = "adipogenesis"
    supported_tasks = ("assess_state",)

    def execute(self, query, store) -> ReasoningResponse:  # pragma: no cover - not run
        raise NotImplementedError


def test_default_registry_resolves_immortalization() -> None:
    registry = default_registry()
    pack = registry.resolve("immortalization", "assess_state")
    assert isinstance(pack, ImmortalizationDomainPack)
    assert registry.domains() == ["immortalization"]
    assert registry.tasks("immortalization") == [
        "assess_state",
        "explain_mechanism",
        "handle_hypothesis",
    ]


def test_unknown_domain_is_rejected_explicitly() -> None:
    registry = default_registry()
    with pytest.raises(UnknownDomainError) as exc:
        registry.resolve("adipogenesis", "assess_state")
    assert "adipogenesis" in str(exc.value)


def test_unsupported_task_is_rejected_explicitly() -> None:
    registry = default_registry()
    with pytest.raises(UnsupportedTaskError) as exc:
        registry.resolve("immortalization", "predict_yield")
    assert "predict_yield" in str(exc.value)


def test_unknown_domain_never_falls_back_to_immortalization() -> None:
    # The failure mode that would silently answer a different science question.
    registry = default_registry()
    for domain in ("adipogenesis", "myogenesis", "", "IMMORTALIZATION"):
        with pytest.raises(UnknownDomainError):
            registry.get(domain or "unset")


def test_registration_is_deterministic_and_additive() -> None:
    registry = DomainRegistry()
    registry.register(ImmortalizationDomainPack())
    registry.register(_StubPack())
    assert registry.domains() == ["adipogenesis", "immortalization"]  # sorted, stable
    # A newly registered domain is addressable immediately, with its own task set.
    assert registry.resolve("adipogenesis", "assess_state").domain == "adipogenesis"
    with pytest.raises(UnsupportedTaskError):
        registry.resolve("adipogenesis", "explain_mechanism")


def test_duplicate_domain_registration_is_an_error() -> None:
    registry = DomainRegistry()
    registry.register(ImmortalizationDomainPack())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(ImmortalizationDomainPack())


def test_pack_must_declare_domain_and_tasks() -> None:
    class _NoDomain:
        domain = ""
        supported_tasks = ("t",)

        def execute(self, query, store):  # pragma: no cover
            raise NotImplementedError

    class _NoTasks:
        domain = "d"
        supported_tasks = ()

        def execute(self, query, store):  # pragma: no cover
            raise NotImplementedError

    registry = DomainRegistry()
    with pytest.raises(ValueError):
        registry.register(_NoDomain())
    with pytest.raises(ValueError):
        registry.register(_NoTasks())


def test_default_registry_instances_are_independent() -> None:
    # Each call composes a fresh registry, so tests and callers cannot leak state.
    first, second = default_registry(), default_registry()
    first.register(_StubPack())
    assert "adipogenesis" in first
    assert "adipogenesis" not in second


def test_registry_holds_no_domain_specific_rules() -> None:
    """Guard the architectural boundary: no domain science in the dispatch layer.

    Checks *executable* code — identifiers and runtime string literals — rather than the
    whole file, since prose may legitimately cite immortalization as the example domain.
    """
    import ast
    import inspect

    import virtualcell.platform.domains as domains

    tree = ast.parse(inspect.getsource(domains))
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
    }
    code_text: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docstrings:
                code_text.append(node.value)
        elif isinstance(node, ast.Name | ast.Attribute):
            code_text.append(getattr(node, "id", "") or getattr(node, "attr", ""))

    blob = " ".join(code_text).lower()
    for leaked in ("immortalization", "tert", "cdk4", "p16", "senescence"):
        assert leaked not in blob, f"registry code references domain concept {leaked!r}"


def test_query_contract_carries_domain_for_dispatch() -> None:
    query = ReasoningQuery(domain="adipogenesis", task="assess_state")
    assert query.domain == "adipogenesis"  # not coerced toward the reference vertical
