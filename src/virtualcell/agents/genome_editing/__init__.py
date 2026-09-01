"""Genome-edit validation — the third reasoning vertical.

Exists to test what two verticals cannot: whether the `DomainPack` boundary and the reasoning
kernel are general, or merely fit the domain the kernel was extracted from and the one written
immediately after it. Chosen for the shape of its decision rather than its subject matter —
see `docs/third_domain_selection.md`.

Written against the kernel unchanged, and deliberately not by copying either existing vertical;
a test forbids it importing them, so any similarity is evidence rather than an artifact.
"""

from virtualcell.agents.genome_editing.assessment import (
    EditingAssessment,
    EditingSafetyError,
    UnsupportedEditingIntentError,
    assess,
    build_mechanism_report,
    mechanism_links,
)
from virtualcell.agents.genome_editing.models import (
    REQUIRED_AXES,
    SEQUENCE_LEVEL_ASSAYS,
    AllelePattern,
    AssayValue,
    ControlValue,
    DetectionValue,
    EditingAssessmentInput,
    EditingFlag,
    EditingIntent,
    EditStatus,
    EditType,
    ExpressionValue,
    OffTargetValue,
)

__all__ = [
    "REQUIRED_AXES",
    "SEQUENCE_LEVEL_ASSAYS",
    "AllelePattern",
    "AssayValue",
    "ControlValue",
    "DetectionValue",
    "EditStatus",
    "EditType",
    "EditingAssessment",
    "EditingAssessmentInput",
    "EditingFlag",
    "EditingIntent",
    "EditingSafetyError",
    "ExpressionValue",
    "OffTargetValue",
    "UnsupportedEditingIntentError",
    "assess",
    "build_mechanism_report",
    "mechanism_links",
]
