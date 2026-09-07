"""Which repository a run is allowed to act on, decided by a committed file.

The previous round moved the base and the pushed commit from "a string the caller supplied" to
"a fact read off the remote". That is only worth something if something other than the caller
decides **which remote**. It did not: `target.remote`, `target.base_branch`, `lock.remote` and
`state.remote` all came out of the request file the agent writes, so pointing phase one at
another reachable remote, or at a different base branch, bound that as the production target and
every later check dutifully verified the wrong thing.

So the authority is `docs/operations/run_target.json`, alongside the approver list and for the
same reason. A request may **repeat** these values — the runbook's example does — but it may not
differ from them, and a difference is a schema error rather than an override.

Two things are checked against reality rather than assumed:

* **the checkout is the configured repository.** `git remote get-url origin`, normalised through
  the several shapes GitHub hands out (`git@`, `https://`, a token-bearing URL, with or without
  `.git`), must be the repository the config names. A container that cloned something else is
  not a container this run may push from.
* **one repository, not three.** The lock ref, the state ref and the branch all live on the same
  configured remote, so a run cannot take its lock on one repository while pushing to another.

`--development` bypasses all of this, and only that flag does: the tests need a bare repository
in a temporary directory, and nothing that reaches a scheduled container may pass it.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Committed, reviewable, and outside the request file the agent writes.
CONFIG_PATH = "docs/operations/run_target.json"

#: Every URL shape GitHub offers, including the token-bearing one an App checkout uses.
_GITHUB_URL = re.compile(
    r"^(?:git@|ssh://git@|git://|https?://(?:[^@/]*@)?)?github\.com[:/]"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)

_REQUIRED = ("repository", "remote", "base_branch", "branch_prefix", "lock_namespace", "state_ref")


class TargetConfigError(RuntimeError):
    """The production target is missing, unreadable, or does not describe one repository."""


@dataclass(frozen=True)
class ProductionTarget:
    """The one repository, remote and pair of refs a scheduled run may touch."""

    repository: str
    remote: str
    base_branch: str
    branch_prefix: str
    lock_namespace: str
    state_ref: str

    def branch_for(self, work_id: str) -> str:
        return f"{self.branch_prefix}{work_id}"

    def owns_branch(self, branch: str) -> bool:
        return branch.startswith(self.branch_for(""))


def load_target(path: Path) -> ProductionTarget:
    """The committed configuration, or a refusal. Never a default assembled from thin air."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise TargetConfigError(f"no production target at {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise TargetConfigError(f"{path} is unreadable: {error}") from error
    if not isinstance(raw, dict):
        raise TargetConfigError(f"the production target at {path} is not an object")
    missing = [name for name in _REQUIRED if not str(raw.get(name) or "").strip()]
    if missing:
        raise TargetConfigError(f"{path} names no {', '.join(missing)}")
    repository = str(raw["repository"]).strip()
    if repository.count("/") != 1:
        raise TargetConfigError(f"{repository!r} is not an owner/name repository")
    return ProductionTarget(
        repository=repository,
        remote=str(raw["remote"]).strip(),
        base_branch=str(raw["base_branch"]).strip(),
        branch_prefix=str(raw["branch_prefix"]).strip(),
        lock_namespace=str(raw["lock_namespace"]).strip(),
        state_ref=str(raw["state_ref"]).strip(),
    )


def normalise_repository(url: str) -> str:
    """`owner/name`, lowercased, from any of GitHub's URL shapes. Anything else is refused."""
    match = _GITHUB_URL.match(url.strip())
    if match is None:
        raise TargetConfigError(f"{url!r} is not a GitHub repository URL")
    return f"{match['owner']}/{match['repo']}".lower()


def remote_repository(remote: str, *, workdir: Path) -> str:
    """What `remote` actually points at in this checkout, as `owner/name`."""
    proc = subprocess.run(
        ["git", "remote", "get-url", remote], cwd=workdir, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise TargetConfigError(
            f"this checkout has no remote {remote!r}: {(proc.stderr or proc.stdout).strip()}"
        )
    return normalise_repository(proc.stdout.strip())


def checkout_problem(target: ProductionTarget, *, workdir: Path) -> str | None:
    """Why this checkout is not the configured repository, or None when it is."""
    try:
        found = remote_repository(target.remote, workdir=workdir)
    except TargetConfigError as error:
        return str(error)
    if found != target.repository.lower():
        return (
            f"{target.remote} in this checkout is {found}, but the configured production "
            f"repository is {target.repository}"
        )
    return None
