"""Question 5, at the level of the probe: fitness is measured, never assumed from a path.

`CLAUDE.md` records an interpreter at `C:\\Users\\...\\Python312`, which is true of the machine
it was written on and false of every cloud container. A probe that checks for a known path
answers a question about that machine; a probe that asks the interpreter its version and tries
the imports answers the question that matters here - can this checkout's suite actually run.
"""

from __future__ import annotations

from automation.environment import (
    MINIMUM_PYTHON,
    EnvironmentFacts,
    find_interpreter,
    probe_environment,
)


def test_the_current_interpreter_is_described_not_assumed() -> None:
    facts = probe_environment(version=(3, 12, 3), dependencies=(), importable=lambda _: True)

    assert facts.python_version == (3, 12)
    assert facts.fit


def test_an_older_interpreter_is_unfit() -> None:
    facts = probe_environment(version=(3, 11, 15), dependencies=(), importable=lambda _: True)

    assert not facts.fit
    assert "3.11" in facts.summary


def test_a_newer_interpreter_is_fit() -> None:
    facts = probe_environment(version=(3, 13, 0), dependencies=(), importable=lambda _: True)

    assert facts.fit


def test_missing_imports_are_named() -> None:
    facts = probe_environment(
        version=(3, 12, 3),
        dependencies=("pydantic", "pytest", "ruff"),
        importable=lambda name: name != "ruff",
    )

    assert not facts.fit
    assert facts.missing_dependencies == ("ruff",)
    assert "ruff" in facts.summary


def test_the_declared_minimum_matches_the_project() -> None:
    """`pyproject.toml` says requires-python >= 3.12; this constant must not drift from it."""
    assert MINIMUM_PYTHON == (3, 12)


def test_interpreter_is_discovered_from_the_path_not_hard_coded() -> None:
    seen: list[str] = []

    def which(name: str) -> str | None:
        seen.append(name)
        return "/somewhere/bin/python3.12" if name == "python3.12" else None

    found = find_interpreter(which=which)

    assert found == "/somewhere/bin/python3.12"
    assert "python3.12" in seen
    assert not any(candidate.startswith("C:") for candidate in seen)


def test_no_suitable_interpreter_returns_none_rather_than_a_guess() -> None:
    assert find_interpreter(which=lambda _: None) is None


def test_facts_carry_enough_to_report_blocked_environment() -> None:
    facts = EnvironmentFacts(python_version=(3, 11), missing_dependencies=("pydantic",))

    assert "3.11" in facts.summary
    assert "pydantic" in facts.summary
