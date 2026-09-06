"""A real remote and a real clone, because the last two rounds were about the difference.

The gate's remaining claims are all claims about a remote: this base SHA is what `main` pointed
at, this branch carries the commit verification passed on, this lock ref is still ours. A test
that stubs the remote can only check that the code asks its stub the question it was written to
ask. So the fixtures build a bare repository and clone it, and every one of those questions is
answered by git.

It is cheap — `git init`, one commit, a clone — and the fourth review round exists because a
failure path that was never driven end to end turned out not to work.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


def git(*args: str, cwd: Path) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return done.stdout.strip()


@dataclass(frozen=True)
class Workspace:
    """A bare remote, a clone of it, and the base commit both agree on."""

    root: Path
    remote: Path
    base_sha: str

    def git(self, *args: str) -> str:
        return git(*args, cwd=self.root)

    def rev(self, ref: str = "HEAD") -> str:
        return self.git("rev-parse", ref)

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message: str = "work") -> str:
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.rev()

    def branch(self, name: str) -> None:
        self.git("checkout", "-q", "-B", name)

    def push(self, name: str, *, ref: str = "HEAD") -> None:
        self.git("push", "-q", str(self.remote), f"{ref}:refs/heads/{name}")

    def remote_head(self, name: str) -> str:
        listed = self.git("ls-remote", str(self.remote), f"refs/heads/{name}")
        return listed.split()[0] if listed else ""


def build(root: Path) -> Workspace:
    """One commit on `main`, pushed to a bare remote alongside it."""
    work = root / "clone"
    remote = root / "origin.git"
    work.mkdir(parents=True)
    git("init", "--quiet", "--bare", "-b", "main", str(remote), cwd=root)
    git("init", "--quiet", "-b", "main", cwd=work)
    git("config", "user.email", "t@t.invalid", cwd=work)
    git("config", "user.name", "t", cwd=work)
    for relative, text in (
        ("scripts/automation/gate.py", "x = 1\n"),
        ("src/virtualcell/cli.py", "z = 1\n"),
        ("src/virtualcell/reasoning/kernel/decide.py", "y = 1\n"),
    ):
        path = work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git("add", "-A", cwd=work)
    git("commit", "-qm", "base", cwd=work)
    git("push", "-q", str(remote), "HEAD:refs/heads/main", cwd=work)
    return Workspace(root=work, remote=remote, base_sha=git("rev-parse", "HEAD", cwd=work))
