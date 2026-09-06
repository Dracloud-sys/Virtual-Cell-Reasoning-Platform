"""Operational safeguards for an unattended run (VCRP-OPS-001).

This package is not part of the shipped library. Nothing under ``src/virtualcell`` imports it,
installing the wheel does not install it, and it computes nothing scientific: it decides
whether a run is allowed to begin, and says why when it is not.

The decision is pure. Every module here takes facts and returns an
:class:`~automation.outcomes.Outcome`; reading GitHub, touching the filesystem and running the
suite stay with the caller. That is what makes the ten operational questions in
``tests/automation`` answerable from fixtures instead of from a live queue - a queue used as a
test fixture is a queue that can dispatch real work by accident.
"""

from __future__ import annotations

from .environment import EnvironmentFacts, find_interpreter, probe_environment
from .locking import FileLockStore, InMemoryLockStore, LockStore, acquire
from .outcomes import Outcome, Status
from .preflight import GateInputs, LinkedPullRequest, run_preflight
from .queue import QueueIssue, QueueRead
from .revisions import RevisionInstruction, actionable
from .scope import PathPolicy, parse_path_policy
from .spec_contract import REQUIRED_SECTIONS, SpecReport, validate_spec

__all__ = [
    "REQUIRED_SECTIONS",
    "EnvironmentFacts",
    "FileLockStore",
    "GateInputs",
    "InMemoryLockStore",
    "LinkedPullRequest",
    "LockStore",
    "Outcome",
    "PathPolicy",
    "QueueIssue",
    "QueueRead",
    "RevisionInstruction",
    "SpecReport",
    "Status",
    "acquire",
    "actionable",
    "find_interpreter",
    "parse_path_policy",
    "probe_environment",
    "run_preflight",
    "validate_spec",
]
