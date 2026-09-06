"""Question 10: a change the issue did not authorise stops the run rather than widening it.

The scope check is deliberately dumb. It compares paths, and it has no opinion about whether
a change is a good idea - that judgement belongs to whoever wrote the issue. What it prevents
is the failure where a run meets one blocked file, decides the blocker is small, and returns
with a diff nobody approved.
"""

from __future__ import annotations

from automation.outcomes import Status
from automation.scope import PathPolicy, parse_path_policy

POLICY = PathPolicy(
    allowed=("scripts/automation/", "tests/automation/", "CHANGELOG.md"),
    forbidden=("src/virtualcell/",),
)


def test_changes_inside_the_allowed_paths_pass() -> None:
    outcome = POLICY.verdict(("scripts/automation/gate.py", "CHANGELOG.md"))

    assert outcome.status is Status.READY_TO_IMPLEMENT
    assert outcome.proceeds


def test_a_path_outside_the_allowed_list_is_blocked() -> None:
    outcome = POLICY.verdict(("scripts/automation/gate.py", "pyproject.toml"))

    assert outcome.status is Status.BLOCKED_SCOPE
    assert "pyproject.toml" in outcome.detail


def test_a_forbidden_path_is_blocked_even_when_an_allow_rule_would_match() -> None:
    """Forbidden wins. Otherwise a broad allow entry silently reopens a closed door."""
    policy = PathPolicy(allowed=("src/",), forbidden=("src/virtualcell/",))

    outcome = policy.verdict(("src/virtualcell/cli.py",))

    assert outcome.status is Status.BLOCKED_SCOPE
    assert "src/virtualcell/cli.py" in outcome.detail


def test_a_file_rule_matches_that_file_only() -> None:
    outcome = POLICY.verdict(("CHANGELOG.md.bak",))

    assert outcome.status is Status.BLOCKED_SCOPE


def test_every_offending_path_is_named_not_just_the_first() -> None:
    outcome = POLICY.verdict(("pyproject.toml", "README.md"))

    assert "pyproject.toml" in outcome.detail
    assert "README.md" in outcome.detail


def test_an_empty_change_set_is_not_a_scope_violation() -> None:
    assert POLICY.verdict(()).proceeds


def test_policy_is_read_from_the_issue_body() -> None:
    body = """## Allowed paths

```
scripts/automation/
CHANGELOG.md
```

## Forbidden paths

```
src/virtualcell/
```
"""
    policy = parse_path_policy(body)

    assert policy.allowed == ("scripts/automation/", "CHANGELOG.md")
    assert policy.forbidden == ("src/virtualcell/",)


def test_a_policy_with_no_allowed_paths_permits_nothing() -> None:
    """An unparsable or empty allow list must not degrade into 'allow everything'."""
    empty = PathPolicy(allowed=(), forbidden=())

    assert empty.verdict(("CHANGELOG.md",)).status is Status.BLOCKED_SCOPE
