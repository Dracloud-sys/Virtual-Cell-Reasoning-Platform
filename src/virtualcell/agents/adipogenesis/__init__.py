"""Adipogenesis — the second reasoning vertical.

Started as a *second data point* for PR14b: decision assembly had one implementation, and an
abstraction extracted from a single caller is shaped entirely by that caller. It was written
against the PR14a kernel and deliberately not by copying the immortalization builder, so any
similarity between the two is evidence rather than an artifact.

It is now a full vertical — six axes, five statuses, seven flags and its own scorecard — and
the original claim survived the expansion: the kernel it reasons through still knows no
biology. See `docs/adipogenesis_vertical.md`.
"""

from virtualcell.agents.adipogenesis.assessment import (
    AdipogenesisAssessment,
    AdipogenesisSafetyError,
    UnsupportedAdipogenesisIntentError,
    assess,
    build_mechanism_report,
)
from virtualcell.agents.adipogenesis.models import (
    AdipogenesisAssessmentInput,
    AdipogenesisFlag,
    AdipogenesisIntent,
    DifferentiationStatus,
)

__all__ = [
    "AdipogenesisAssessment",
    "AdipogenesisAssessmentInput",
    "AdipogenesisFlag",
    "AdipogenesisIntent",
    "AdipogenesisSafetyError",
    "DifferentiationStatus",
    "UnsupportedAdipogenesisIntentError",
    "assess",
    "build_mechanism_report",
]
