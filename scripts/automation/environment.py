"""Is this checkout's suite actually runnable here, asked rather than assumed.

`CLAUDE.md` records the interpreter as ``C:\\Users\\...\\Python312``. That was true of the
machine it was written on and is false of every cloud container, where the default `python` is
older than the project's floor and the dependencies are not installed. A probe that looks for a
known path answers a question about somebody's laptop. This one asks the interpreter its
version and tries the imports, which is the question that decides whether a verification run
means anything.

Nothing here installs. A run that cannot verify reports ``BLOCKED_ENVIRONMENT`` and stops,
because the failure mode this prevents is a green report produced by a gate that quietly
skipped the checks it could not run.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

#: Mirrors ``requires-python`` in pyproject.toml. If that moves, this has to move with it.
MINIMUM_PYTHON: tuple[int, int] = (3, 12)

#: Version-specific names only. A bare ``python3`` would be a guess about its version, and a
#: guess is what this module exists to avoid.
INTERPRETER_CANDIDATES: tuple[str, ...] = ("python3.12", "python3.13", "python3.14")


@dataclass(frozen=True)
class EnvironmentFacts:
    """What was measured, in a form a blocked report can quote."""

    python_version: tuple[int, int]
    missing_dependencies: tuple[str, ...] = ()

    @property
    def fit(self) -> bool:
        return self.python_version >= MINIMUM_PYTHON and not self.missing_dependencies

    @property
    def summary(self) -> str:
        version = ".".join(str(part) for part in self.python_version)
        minimum = ".".join(str(part) for part in MINIMUM_PYTHON)
        parts = [f"python {version}"]
        if self.python_version < MINIMUM_PYTHON:
            parts[0] += f" (needs >= {minimum})"
        if self.missing_dependencies:
            parts.append("missing: " + ", ".join(self.missing_dependencies))
        elif self.fit:
            parts.append("all dependencies present")
        return "; ".join(parts)


def probe_environment(
    *,
    version: Sequence[int],
    dependencies: Iterable[str],
    importable: Callable[[str], bool],
) -> EnvironmentFacts:
    """Measure the running interpreter and the imports this checkout needs."""
    missing = tuple(name for name in dependencies if not importable(name))
    return EnvironmentFacts(python_version=(version[0], version[1]), missing_dependencies=missing)


def find_interpreter(
    *,
    which: Callable[[str], str | None] = shutil.which,
    candidates: Iterable[str] = INTERPRETER_CANDIDATES,
) -> str | None:
    """The first interpreter on PATH that names a version at or above the floor.

    Returns ``None`` rather than falling back to whatever `python` happens to be: an
    interpreter that might be old is not better than no interpreter, it is just harder to
    notice.
    """
    for candidate in candidates:
        found = which(candidate)
        if found:
            return found
    return None
