"""Natural-language reasoning over the knowledge graph.

The reasoning layer answers natural-language questions by retrieving grounded
evidence from the knowledge base and having an LLM synthesize an answer that
cites that evidence. It never lets the model invent biology: every claim must be
backed by a retrieved knowledge-graph fact. When no LLM is configured, a
deterministic offline backend formats the retrieved evidence directly.
"""

from __future__ import annotations

from virtualcell.reasoning.decision import AssessmentFlag, CandidateStatus, DecisionReport
from virtualcell.reasoning.explain import Explanation, MechanisticLink, explain
from virtualcell.reasoning.qa import Answer, QuestionAnswerer

__all__ = [
    "Answer",
    "AssessmentFlag",
    "CandidateStatus",
    "DecisionReport",
    "Explanation",
    "MechanisticLink",
    "QuestionAnswerer",
    "explain",
]
