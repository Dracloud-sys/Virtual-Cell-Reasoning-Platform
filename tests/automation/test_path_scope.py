"""Question 10: a change the issue did not authorise stops the run rather than widening it.

The scope check is deliberately dumb. It compares paths, and it has no opinion about whether
a change is a good idea - that judgement belongs to whoever wrote the issue. What it prevents
is the failure where a run meets one blocked file, decides the blocker is small, and returns
with a diff nobody approved.
"""

from __future__ import annotations

from automation.outcomes import Status
from automation.scope import (
    KERNEL_PATH,
    PathChange,
    PathPolicy,
    parse_path_policy,
    unsafe_reason,
)

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


# --- hardening added after the first review round -------------------------------------------


def test_the_kernel_is_forbidden_even_when_the_issue_forgot_to_list_it() -> None:
    """A wide allow rule plus a forgetful forbidden list is not kernel authorisation."""
    policy = PathPolicy(allowed=("src/",), forbidden=(), kernel_authorized=False)

    outcome = policy.verdict(("src/virtualcell/reasoning/kernel/decide.py",))

    assert outcome.status is Status.BLOCKED_SCOPE
    assert KERNEL_PATH in "".join(policy.effective_forbidden)


def test_an_authorised_kernel_change_is_allowed_through() -> None:
    policy = PathPolicy(allowed=("src/",), forbidden=(), kernel_authorized=True)

    assert policy.verdict(("src/virtualcell/reasoning/kernel/decide.py",)).proceeds


def test_a_traversal_path_is_refused_before_it_is_matched() -> None:
    outcome = POLICY.verdict(("../../etc/passwd",))

    assert outcome.status is Status.BLOCKED_SCOPE
    assert "escapes the repository" in outcome.detail


def test_an_absolute_path_is_refused() -> None:
    assert POLICY.verdict(("/etc/passwd",)).status is Status.BLOCKED_SCOPE
    assert unsafe_reason("/etc/passwd") == "absolute"


def test_a_windows_style_path_is_refused() -> None:
    assert unsafe_reason("scripts\\automation\\gate.py") is not None


def test_a_dot_segment_that_would_normalise_away_is_refused() -> None:
    assert unsafe_reason("scripts/./automation/gate.py") is not None


def test_a_plain_relative_path_is_safe() -> None:
    assert unsafe_reason("scripts/automation/gate.py") is None


def test_a_rename_is_judged_on_both_ends() -> None:
    """Moving a file out of the kernel is a kernel change, invisible if you only see where
    it landed."""
    policy = PathPolicy(allowed=("scripts/",), forbidden=(), kernel_authorized=False)

    outcome = policy.verdict(
        (PathChange("scripts/moved.py", previous_path="src/virtualcell/reasoning/kernel/x.py"),)
    )

    assert outcome.status is Status.BLOCKED_SCOPE
    assert "kernel" in outcome.detail


def test_a_rename_wholly_inside_the_allowed_paths_passes() -> None:
    outcome = POLICY.verdict(
        (PathChange("scripts/automation/b.py", previous_path="scripts/automation/a.py"),)
    )

    assert outcome.proceeds


def test_the_policy_parsed_from_an_issue_carries_the_kernel_decision() -> None:
    body = """## Allowed paths

```
src/
```

## Forbidden paths

```
none - this milestone is repository-wide.
```
"""
    guarded = parse_path_policy(body, kernel_authorized=False)
    opened = parse_path_policy(body, kernel_authorized=True)

    assert not guarded.permits("src/virtualcell/reasoning/kernel/decide.py")
    assert opened.permits("src/virtualcell/reasoning/kernel/decide.py")
