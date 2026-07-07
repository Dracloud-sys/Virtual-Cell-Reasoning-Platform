"""LLM backends for the reasoning layer.

A backend turns a question plus a block of grounded, evidence-graded facts into a
natural-language answer. Two backends are provided:

* :class:`AnthropicBackend` — calls Anthropic Claude. Requires the ``anthropic``
  package (``pip install '.[llm]'``) and an ``ANTHROPIC_API_KEY`` in the
  environment. The API key is never read from code or committed.
* :class:`TemplateBackend` — a deterministic offline fallback that formats the
  retrieved evidence directly, with no external call. It keeps the platform (and
  its tests) usable without an API key.

:func:`get_backend` selects Anthropic when it is both installed and configured,
otherwise the template backend.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

_SYSTEM_PROMPT = (
    "You are a careful cell-biology reasoning assistant for a Virtual Cell "
    "Reasoning Platform. Answer the user's question using ONLY the knowledge-graph "
    "evidence provided below. Do not introduce biological facts that are not in the "
    "evidence. For each statement you make, cite the supporting entity id in the form "
    "[kb:<id>] and respect its evidence tier. If the evidence is insufficient to "
    "answer, say so plainly rather than guessing."
)


@runtime_checkable
class LLMBackend(Protocol):
    """Turns a question + grounded evidence text into an answer string."""

    name: str

    def answer(self, question: str, evidence: str) -> str: ...


class TemplateBackend:
    """Deterministic, offline backend: returns the grounded evidence as an answer.

    This makes the reasoning endpoint usable (and testable) with no API key. It does
    not synthesize prose beyond framing the retrieved facts honestly.
    """

    name = "offline-template"

    def answer(self, question: str, evidence: str) -> str:
        if not evidence.strip():
            return (
                "No knowledge-base evidence was found for this question. "
                "(Offline mode: set ANTHROPIC_API_KEY and install the 'llm' extra "
                "for synthesized answers.)"
            )
        return (
            "Based on the knowledge base (offline mode — evidence shown as retrieved, "
            "not synthesized):\n\n" + evidence
        )


class AnthropicBackend:
    """Answers via Anthropic Claude, grounded strictly in the provided evidence."""

    name = "anthropic"

    def __init__(self, model: str, max_tokens: int = 1024) -> None:
        self.model = model
        self.max_tokens = max_tokens

    def answer(self, question: str, evidence: str) -> str:
        import anthropic  # lazy: only needed when this backend is actually used

        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
        user = f"Question:\n{question}\n\nKnowledge-graph evidence:\n{evidence}"
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


def _anthropic_available() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def get_backend(model: str | None = None) -> LLMBackend:
    """Return the best available backend.

    Uses Anthropic Claude when the package is installed and ``ANTHROPIC_API_KEY`` is
    set; otherwise falls back to the deterministic offline template backend.
    """
    if os.environ.get("ANTHROPIC_API_KEY") and _anthropic_available():
        from virtualcell.core.config import get_settings

        return AnthropicBackend(model=model or get_settings().llm_model)
    return TemplateBackend()
