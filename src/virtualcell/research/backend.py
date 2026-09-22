"""The model call behind the research path, and its failure states.

Two things here differ from `reasoning/llm.py`, both on purpose.

**It does not fall back.** `get_backend()` returns a `TemplateBackend` when no API key is
set, which is right for a grounded Q&A endpoint that can honestly hand back the evidence it
retrieved. It is wrong here: there is nothing to hand back, so a fallback would report a
successful investigation that never happened. `get_research_backend()` raises instead, and
the caller sees `BackendUnavailable` rather than an empty design.

**Its prompt is its own.** `reasoning/llm.py`'s system prompt forbids any fact not in the
evidence, which is correct for that path and must stay untouched. Exploration needs to
propose mechanisms nobody supplied — that is the whole point — so this prompt permits it on
one condition: anything proposed from the model's own knowledge comes back labelled
`model_prior`, a search target rather than a finding. The permission and the label are the
same sentence.

The Anthropic wiring, the settings lookup and the availability check are reused from
`reasoning/llm.py` rather than copied.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from virtualcell.reasoning.llm import _anthropic_available

#: Bumped when the prompt changes in a way that could change an answer. Recorded in every
#: report's provenance, so two runs can be told apart without guessing.
PROMPT_VERSION = "research-v1"

RESEARCH_SYSTEM_PROMPT = """\
You are a research design assistant for a Virtual Cell Reasoning Platform. You are given a \
research question, the context it sits in, and whatever evidence the researcher already has. \
Your job is to turn it into a design an experimentalist could act on.

You MAY propose mechanisms and hypotheses that the supplied evidence does not contain — that \
is what you are for. What you may NOT do is let a proposal look like a finding. Every claim \
you make rests on exactly one of these, and you must say which:

- evidence the researcher supplied or that was read from a source: cite its id;
- an inference from those: cite the ids it follows from;
- your own prior knowledge with nothing supplied behind it: mark the hypothesis \
`unverified_candidate` and leave its supporting ids empty. It is a thing to go and check, \
not a thing that is known.

Cite only evidence ids that appear in the EVIDENCE block. Never invent an id. If you need \
something nobody gave you, say so in open_items instead of inventing support for it.

Do not state a numeric confidence, success probability or information gain. Nobody measured \
them. Explain priority in words, from what a result would decide and what it would cost.

Propose competing hypotheses, including the dull explanations — an artefact of the assay, a \
confound in the control, a difference between the system the evidence came from and the one \
in the question. For each experiment, say what it would tell apart, and what a positive, a \
negative and an ambiguous result would each change.

Distinguish what was observed from what you expect to observe.

Return ONLY a JSON object, no prose around it, with exactly these keys:

{
  "restated_question": str,
  "assumptions": [str],
  "hypotheses": [
    {"id": str, "statement": str, "support": "evidence_linked" | "unverified_candidate",
     "supporting_evidence_ids": [str], "contradicting_evidence_ids": [str],
     "applicability": str | null}
  ],
  "experiments": [
    {"id": str, "design": str, "discriminates": [str], "controls": [str],
     "measurements": [str], "timepoints": [str],
     "branches": [{"outcome": str, "implication": str}],
     "priority_rationale": str | null}
  ],
  "open_items": [str],
  "evidence_used": [str]
}
"""


class ResearchBackendError(RuntimeError):
    """Base for every way the research path can fail to produce a design."""


class BackendUnavailable(ResearchBackendError):
    """No model provider is configured or installed. Not an empty result — no result."""


class BackendCallFailed(ResearchBackendError):
    """The provider was reachable and the call did not produce usable output."""


class BudgetExhausted(ResearchBackendError):
    """The run hit its own ceiling before finishing. Whatever exists is partial."""


@runtime_checkable
class ResearchBackend(Protocol):
    """Turns a fully-assembled research prompt into a raw JSON string."""

    name: str
    model: str | None

    def design(self, prompt: str, *, max_output_tokens: int) -> str: ...


class AnthropicResearchBackend:
    """Anthropic Claude, prompted for research design rather than grounded recall."""

    name = "anthropic-research"

    def __init__(self, model: str, system_prompt: str = RESEARCH_SYSTEM_PROMPT) -> None:
        self.model = model
        self._system = system_prompt

    def design(self, prompt: str, *, max_output_tokens: int) -> str:
        import anthropic  # lazy: only needed when this backend is actually used

        try:
            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
            response = client.messages.create(
                model=self.model,
                max_tokens=max_output_tokens,
                system=self._system,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # provider errors are many and none of them are success
            raise BackendCallFailed(f"the model provider call failed: {exc}") from exc
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text.strip():
            raise BackendCallFailed("the model returned no text")
        return text


def get_research_backend(model: str | None = None) -> ResearchBackend:
    """Return a research backend, or raise if none can be had.

    Deliberately without a fallback. There is no honest offline answer to "design me an
    experiment": handing back a template would be reporting a success that did not happen,
    which is the one failure mode this path cannot afford.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise BackendUnavailable(
            "no ANTHROPIC_API_KEY is set, so no research design can be generated. This is "
            "not an empty result: nothing ran."
        )
    if not _anthropic_available():
        raise BackendUnavailable(
            "the 'anthropic' package is not installed (pip install '.[llm]'), so no "
            "research design can be generated."
        )
    from virtualcell.core.config import get_settings

    return AnthropicResearchBackend(model=model or get_settings().llm_model)
