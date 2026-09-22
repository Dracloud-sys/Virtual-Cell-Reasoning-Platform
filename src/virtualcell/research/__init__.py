"""Open-ended research reasoning: a question and some evidence, not a domain and a task.

The strict path (`platform.service.ReasoningService.query`) resolves a `DomainPack` before
anything else, which is right for a verified verdict and wrong for a question nobody has
written a pack for. This is the other door. It takes any research question, uses no
registry, and returns hypotheses and an experimental design with every claim labelled by
what it actually rests on.

The two paths do not share a code path and neither weakens the other.
"""

from virtualcell.research.backend import (
    PROMPT_VERSION,
    BackendCallFailed,
    BackendUnavailable,
    ModelReply,
    ResearchBackend,
    ResearchBackendError,
    get_research_backend,
)
from virtualcell.research.contracts import (
    DecisionBranch,
    EvidenceItem,
    EvidenceKind,
    Hypothesis,
    HypothesisSupport,
    IntegrityFinding,
    ProposedExperiment,
    ResearchBudget,
    ResearchProvenance,
    ResearchReport,
    ResearchRequest,
)
from virtualcell.research.service import ResearchService, build_prompt, check_integrity

__all__ = [
    "PROMPT_VERSION",
    "BackendCallFailed",
    "BackendUnavailable",
    "DecisionBranch",
    "EvidenceItem",
    "EvidenceKind",
    "Hypothesis",
    "HypothesisSupport",
    "IntegrityFinding",
    "ModelReply",
    "ProposedExperiment",
    "ResearchBackend",
    "ResearchBackendError",
    "ResearchBudget",
    "ResearchProvenance",
    "ResearchReport",
    "ResearchRequest",
    "ResearchService",
    "build_prompt",
    "check_integrity",
    "get_research_backend",
]
