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

    python -m automation preflight --request run-request.json

Exit code 0 means work may begin, and nothing else does.
"""

from __future__ import annotations

from .approvals import ApproverConfigError, load_approvers, parse_approvals
from .environment import EnvironmentFacts, find_interpreter, probe_environment
from .github_payloads import APPROVAL_LABEL, SchemaError, read_pull_requests, read_queue
from .gitrefs import GitRefLockStore, GitRefStateStore, LockUnavailable, StateCorrupt
from .locking import FileLockStore, InMemoryLockStore, LockStore, acquire
from .outcomes import EXIT_CODES, Outcome, Status
from .postflight import PostflightInputs, changed_paths, run_postflight
from .preflight import GateInputs, LinkedPullRequest, run_preflight
from .queue import QueueIssue, QueueRead
from .revisions import RevisionInstruction, actionable, rejections
from .scope import KERNEL_PATH, PathChange, PathPolicy, parse_path_policy, unsafe_reason
from .spec_contract import REQUIRED_SECTIONS, SpecReport, extract_work_id, validate_spec
from .tokens import BoundRevision, Confirmation, LockToken, fingerprint_of, sha256_of

__all__ = [
    "APPROVAL_LABEL",
    "EXIT_CODES",
    "KERNEL_PATH",
    "REQUIRED_SECTIONS",
    "ApproverConfigError",
    "BoundRevision",
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
    "Outcome",
    "PathChange",
    "PathPolicy",
    "PostflightInputs",
    "QueueIssue",
    "QueueRead",
    "RevisionInstruction",
    "SchemaError",
    "SpecReport",
    "StateCorrupt",
    "Status",
    "acquire",
    "actionable",
    "changed_paths",
    "extract_work_id",
    "fingerprint_of",
    "find_interpreter",
    "load_approvers",
    "parse_approvals",
    "parse_path_policy",
    "probe_environment",
    "sha256_of",
    "read_pull_requests",
    "read_queue",
    "rejections",
    "run_postflight",
    "run_preflight",
    "unsafe_reason",
    "validate_spec",
]
