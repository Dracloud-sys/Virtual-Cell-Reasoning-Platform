"""The generic reasoning kernel (PR14a).

The domain-independent machinery a vertical reasons *with*, lifted out of the vertical
that first needed it. The dividing line is a single question: **would a different biology
answer this differently?**

* How to walk a graph outward, deduplicate what it finds, and order it so the strongest
  reasoning reads first — no. That is :mod:`~virtualcell.reasoning.kernel.grounding`.
* *Which* links a mechanism claim may rest on — yes. That stays in the pack, supplied as
  an admission policy.
* Where in a report a forbidden phrasing counts as an assertion — no. That is
  :mod:`~virtualcell.reasoning.kernel.safety`, and it is the same everywhere because it is
  a fact about report structure, not about cells.
* *Which* phrasings are forbidden — yes. Also the pack's.
* That an observation is established evidence and a conclusion drawn from it is a
  hypothesis — no. :mod:`~virtualcell.reasoning.kernel.claims` fixes that convention so it
  cannot drift per vertical, which is how a report starts overclaiming while every
  individual file still looks reasonable.
* Working out which required axes went unmeasured, and collecting a suggestion list without
  repeats — no. :mod:`~virtualcell.reasoning.kernel.assembly`, and deliberately nothing more
  than that: two verticals read side by side shared almost no other procedure.
* *Which* axes are required, and which assay answers which gap — yes. The pack's.

Nothing here imports from :mod:`virtualcell.agents`, and a test enforces that. It is what
makes "domain-independent" a checkable property rather than an intention.
"""

from virtualcell.reasoning.kernel.assembly import (
    UNMEASURED,
    missing_axes,
    ordered_unique,
)
from virtualcell.reasoning.kernel.claims import (
    INTERPRETATION_CONFIDENCE,
    MEASUREMENT_CONFIDENCE,
    interpretation_claim,
    measurement_claim,
)
from virtualcell.reasoning.kernel.grounding import (
    DEFAULT_MAX_HOPS,
    WEAK_RELATIONS,
    WEAK_STEPS,
    GroundingError,
    LinkAdmission,
    all_of,
    ground_links,
    relations_in,
    rendered_step,
    step_relations,
    targets_in,
)
from virtualcell.reasoning.kernel.safety import (
    AssertionSafetyError,
    assertion_texts,
    forbidden_phrases_in,
    validate_assertions,
)

__all__ = [
    "DEFAULT_MAX_HOPS",
    "UNMEASURED",
    "INTERPRETATION_CONFIDENCE",
    "MEASUREMENT_CONFIDENCE",
    "WEAK_RELATIONS",
    "WEAK_STEPS",
    "AssertionSafetyError",
    "GroundingError",
    "LinkAdmission",
    "all_of",
    "assertion_texts",
    "forbidden_phrases_in",
    "ground_links",
    "interpretation_claim",
    "measurement_claim",
    "missing_axes",
    "ordered_unique",
    "relations_in",
    "rendered_step",
    "step_relations",
    "targets_in",
    "validate_assertions",
]
