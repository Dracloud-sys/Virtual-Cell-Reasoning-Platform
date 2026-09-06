"""Operational safeguards for an unattended run (VCRP-OPS-001).

This package is not part of the shipped library. Nothing under ``src/virtualcell`` imports it,
installing the wheel does not install it, and it computes nothing scientific: it decides
whether a run is allowed to begin, and says why when it is not.

The decision is pure. The modules under :mod:`automation.preflight` take facts and return an
:class:`~automation.outcomes.Outcome`; reading GitHub, touching the filesystem and running the
suite stay with :mod:`automation.runner`, the entry point. That split is what makes the
operational questions in ``tests/automation`` answerable from fixtures instead of from a live
queue - a queue used as a test fixture is a queue that can dispatch real work by accident.

Entry point:

    python scripts/automation/cli.py preflight --request run-request.json --token lock.json

Exit code 0 means the step succeeded and the next may begin, and nothing else does.
"""

from __future__ import annotations

from .approvals import ApproverConfigError, load_approvers, parse_approvals
from .completion import CompletionInputs, OpenPullRequest, check_completion
from .environment import EnvironmentFacts, find_interpreter, probe_environment
from .github_payloads import (
    APPROVAL_LABEL,
    SchemaError,
    read_open_pull_requests,
    read_pull_requests,
    read_queue,
)
from .gitrefs import (
    GitRefLockStore,
    GitRefStateStore,
    LockUnavailable,
    StateCorrupt,
    remote_head,
)
from .locking import FileLockStore, InMemoryLockStore, LockStore, acquire
from .outcomes import EXIT_CODES, Outcome, Status
from .postflight import PostflightInputs, changed_paths, run_postflight
from .preflight import GateInputs, LinkedPullRequest, run_preflight
from .production import (
    CONFIG_PATH,
    ProductionTarget,
    TargetConfigError,
    checkout_problem,
    load_target,
    normalise_repository,
)
from .queue import QueueIssue, QueueRead
from .revisions import RevisionInstruction, actionable, rejections
from .scope import KERNEL_PATH, PathChange, PathPolicy, parse_path_policy, unsafe_reason
from .spec_contract import REQUIRED_SECTIONS, SpecReport, extract_work_id, validate_spec
from .tokens import (
    BoundRevision,
    BoundTarget,
    Confirmation,
    LockToken,
    fingerprint_of,
    sha256_of,
)

__all__ = [
    "APPROVAL_LABEL",
    "CONFIG_PATH",
    "EXIT_CODES",
    "KERNEL_PATH",
    "REQUIRED_SECTIONS",
    "ApproverConfigError",
    "BoundRevision",
    "BoundTarget",
    "CompletionInputs",
    "Confirmation",
    "EnvironmentFacts",
    "FileLockStore",
    "GateInputs",
    "GitRefLockStore",
    "GitRefStateStore",
    "InMemoryLockStore",
    "LinkedPullRequest",
    "LockToken",
    "LockStore",
    "LockUnavailable",
    "OpenPullRequest",
    "Outcome",
    "PathChange",
    "PathPolicy",
    "PostflightInputs",
    "ProductionTarget",
    "QueueIssue",
    "QueueRead",
    "RevisionInstruction",
    "SchemaError",
    "SpecReport",
    "StateCorrupt",
    "TargetConfigError",
    "Status",
    "acquire",
    "actionable",
    "changed_paths",
    "check_completion",
    "checkout_problem",
    "extract_work_id",
    "fingerprint_of",
    "find_interpreter",
    "load_approvers",
    "load_target",
    "parse_approvals",
    "normalise_repository",
    "parse_path_policy",
    "probe_environment",
    "sha256_of",
    "read_open_pull_requests",
    "read_pull_requests",
    "read_queue",
    "remote_head",
    "rejections",
    "run_postflight",
    "run_preflight",
    "unsafe_reason",
    "validate_spec",
]
