"""Adipogenesis — the minimal second reasoning vertical.

Exists to be a *second data point*, not a complete domain. Decision assembly currently has
one implementation, and an abstraction extracted from a single caller is shaped entirely by
that caller; a second independent assembly has to exist before PR14b can tell what is
genuinely shared from what merely looked shared.

Written against the PR14a kernel and deliberately not by copying the immortalization
builder, so any similarity between the two is evidence rather than an artifact.
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
