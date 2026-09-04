"""The text a model reads before it calls anything.

A tool description is the only part of this server that is guaranteed to reach a
calling model *before* it acts. Everything the platform refuses to conclude is
therefore stated here as well as in the payload — once structurally, in the
field order of :mod:`virtualcell.mcp.payloads`, and once in prose, here.

Kept in its own module so the rules are one reviewable object rather than
string literals scattered through decorators, and so a test can assert that a
required sentence is actually shipped.
"""

from __future__ import annotations

LIST_DOMAINS = """\
List every reasoning domain this platform can answer for, with its one-line
purpose and its task names.

Cheap and side-effect free. Call it first; never guess a domain name.\
"""

DESCRIBE_DOMAIN = """\
Describe one domain: its tasks, what each task requires, and every measurement
axis it accepts - the exact key to send, the accepted vocabulary, the value
type and bounds, whether the axis can move the verdict or only refine it, and
how to spell "no reading was taken".

Call this before assembling an experiment payload. Axis names are not
guessable, and a key this domain does not recognise is reported back as
`unsupported` rather than silently corrected - the answer is then computed
without that measurement.\
"""

REASON = """\
Run a reasoning query against one domain and return the platform's answer.

This tool does not invent a verdict. It returns the platform's status together
with its limitations, its unmeasured axes and its overinterpretation risks, and
all of those are part of the answer. Report the status only alongside them.

Rules for using the result:

- `status` may be null. That means the domain pack reached no verdict. Do not
  supply one, and do not read `summary` as a verdict.
- Do not upgrade a refusal into a conclusion. If the platform says the evidence
  is insufficient, that is the answer, not an obstacle to it.
- Do not describe an axis the platform reported as unmeasured as if it had been
  measured.
- If `unsupported_measurements` is non-empty, say so. The answer was computed
  WITHOUT those measurements. Call `describe_domain`, fix the key, and re-send
  rather than reporting this answer.
- Follow-up measurements come from `missing_inputs[].send_as` and from nowhere
  else. `missing_information` is prose for a person and may spell an axis
  differently from the key it is sent as.
- `recommended_validation` and `recommended_next_experiments` are lab work for
  a person to do. Relay them. Never turn one into an experiment key, and never
  synthesise a value for one - inventing a result is the exact failure this
  platform exists to prevent.
- `limitations` and `overinterpretation_risks` are not padding. Relay them with
  the status; a summary that drops them is wrong even when the status is right.\
"""


def flatten(text: str) -> str:
    """Collapse wrapping so a phrase check does not depend on where a line broke."""
    return " ".join(text.split())


#: Rules that must survive any future rewording of the descriptions above. A test
#: asserts each one is still present in the shipped tool description, so a
#: well-meant edit cannot quietly drop a safety rule.
REQUIRED_PHRASES: tuple[tuple[str, str], ...] = (
    ("reason", "does not invent a verdict"),
    ("reason", "status` may be null"),
    ("reason", "computed WITHOUT those measurements"),
    ("reason", "missing_inputs[].send_as"),
    ("reason", "never synthesise a value"),
    ("reason", "overinterpretation_risks"),
    ("reason", "Do not upgrade a refusal into a conclusion"),
    ("describe_domain", "reported back as `unsupported`"),
    ("list_domains", "never guess a domain name"),
)
