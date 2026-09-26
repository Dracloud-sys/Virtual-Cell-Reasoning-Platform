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

**Its limits are its own, and written down here.** The per-request timeout and the retry
ceiling are passed explicitly rather than left to the SDK's defaults, so what this code runs
under is readable here instead of in a dependency's release notes. They are limits on a
request and a count of retries — **not a deadline for the call**, and this module does not
enforce one. How long a call took is therefore measured and reported, not computed from the
settings. What the provider says back — which model it served, why it stopped, what it spent
— comes out in a `ModelReply` and is recorded, because a run that logs only what it *asked*
for cannot afterwards be told apart from a different run.

The Anthropic wiring, the settings lookup and the availability check are reused from
`reasoning/llm.py` rather than copied.
"""

from __future__ import annotations

import os
import time
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from virtualcell.reasoning.llm import _anthropic_available

#: Bumped when the prompt changes in a way that could change an answer. Recorded in every
#: report's provenance, so two runs can be told apart without guessing.
PROMPT_VERSION = "research-v1"

#: Per-attempt HTTP timeout, in seconds — the limit on **one request**, not on the call.
#: Set here rather than left to the SDK, whose default is ten minutes: a research design is
#: one bounded generation, and a caller waiting ten minutes on a provider that has stopped
#: answering has been told nothing for most of it.
DEFAULT_TIMEOUT_SECONDS = 120.0

#: Retries per logical call, on top of the first attempt. The SDK retries connection
#: errors, 408/409/429 and 5xx, and it retries timeouts too.
#:
#: **These two numbers do not multiply into a deadline.** An earlier version of this comment
#: said the worst case was ``DEFAULT_TIMEOUT_SECONDS * (DEFAULT_MAX_RETRIES + 1)`` — "six
#: minutes" — and that is wrong twice over. The timeout bounds a single HTTP request, and
#: the SDK sleeps between retries with backoff that the timeout does not cover, so the
#: product is not an upper bound; and nothing here cancels an operation that exceeds it, so
#: no total deadline is enforced at all. Claiming a 360-second ceiling would be describing a
#: control that does not exist.
#:
#: What can honestly be said is what these settings *are*: a per-request limit and a retry
#: ceiling, both recorded as such. What actually happened is measured — see
#: ``ModelReply.elapsed_seconds`` — rather than predicted from these two constants.
DEFAULT_MAX_RETRIES = 2

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


class ModelReply(BaseModel):
    """One logical design call: the text, and what the provider said about producing it.

    ``design`` returns this rather than a bare string so a report can record what actually
    answered it. A run that logs only the model it *asked* for, and no token counts, cannot
    later be told apart from a different run — which is the whole purpose of provenance.

    Every field but ``text`` is optional and defaults to ``None``, because a backend that
    does not report a thing must leave it blank rather than supply a default that reads
    like a measurement.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    #: What the provider reported it served, which need not be what was requested.
    model_served: str | None = None
    stop_reason: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    #: The attempt ceiling this call ran under (retries + 1), and the per-request timeout.
    #: Limits, not counts: the SDK retries internally and never says how many attempts it
    #: made, so reporting a number here as "attempts used" would be inventing one. Nor do
    #: they multiply into a deadline — see `DEFAULT_MAX_RETRIES`.
    max_request_attempts: int | None = Field(default=None, ge=1)
    timeout_seconds: float | None = Field(default=None, gt=0)
    #: Wall-clock seconds the call actually took, monotonic, measured around the provider
    #: call including whatever retrying and backoff happened inside it. This is the only
    #: honest number about duration here: the limits above say what was *allowed*, and a
    #: product of them would be a prediction. A run reports what it spent.
    elapsed_seconds: float | None = Field(default=None, ge=0)


@runtime_checkable
class ResearchBackend(Protocol):
    """Turns a fully-assembled research prompt into one :class:`ModelReply`."""

    name: str
    model: str | None

    def design(self, prompt: str, *, max_output_tokens: int) -> ModelReply: ...


class AnthropicResearchBackend:
    """Anthropic Claude, prompted for research design rather than grounded recall."""

    name = "anthropic-research"

    def __init__(
        self,
        model: str,
        system_prompt: str = RESEARCH_SYSTEM_PROMPT,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.model = model
        self._system = system_prompt
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    @property
    def max_request_attempts(self) -> int:
        """Attempts allowed per logical call. One first try plus the retries."""
        return self.max_retries + 1

    def design(self, prompt: str, *, max_output_tokens: int) -> ModelReply:
        import anthropic  # lazy: only needed when this backend is actually used

        # Measured, not predicted. The timeout and retry ceiling below say what one request
        # is allowed; they do not bound the call, so how long it took is a thing to observe.
        started = time.monotonic()
        try:
            # Both limits are passed explicitly. The SDK's own defaults are a ten-minute
            # timeout and two retries, and leaving them implicit means the per-request limit
            # this code runs under lives in a dependency's release notes, not here.
            client = anthropic.Anthropic(  # reads ANTHROPIC_API_KEY from the environment
                timeout=self.timeout_seconds,
                max_retries=self.max_retries,
            )
            response = client.messages.create(
                model=self.model,
                max_tokens=max_output_tokens,
                system=self._system,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # provider errors are many and none of them are success
            elapsed = time.monotonic() - started
            raise BackendCallFailed(
                f"the model provider call failed after {elapsed:.1f}s: {exc}"
            ) from exc
        return self._read_reply(response, elapsed_seconds=time.monotonic() - started)

    def _read_reply(self, response: object, *, elapsed_seconds: float | None = None) -> ModelReply:
        """Read the reply, refusing the two non-answers that look like parse errors.

        A reply cut off at ``max_tokens`` is JSON that stops mid-object, so it fails to
        parse downstream and the caller is told "the model did not return parseable JSON" —
        which sends them to debug the prompt when the actual fix is a larger output budget.
        A refusal carries no text at all, so it would surface as "the model returned no
        text" and send them to debug the transport. The provider says which happened in
        ``stop_reason``; this asks instead of guessing.
        """
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "max_tokens":
            raise BackendCallFailed(
                "the reply was cut off because the output budget was too small; raise "
                "`budget.max_output_tokens` and run again. The partial text is not a design."
            )
        if stop_reason == "refusal":
            raise BackendCallFailed(
                "the model declined to answer this request. That is a refusal, not an "
                "empty result and not a transport problem; the request is what to look at."
            )
        text = "".join(
            block.text for block in getattr(response, "content", []) if block.type == "text"
        )
        if not text.strip():
            raise BackendCallFailed(f"the model returned no text (stop_reason: {stop_reason!r})")
        usage = getattr(response, "usage", None)
        return ModelReply(
            text=text,
            model_served=getattr(response, "model", None),
            stop_reason=stop_reason,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            max_request_attempts=self.max_request_attempts,
            timeout_seconds=self.timeout_seconds,
            elapsed_seconds=elapsed_seconds,
        )


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
