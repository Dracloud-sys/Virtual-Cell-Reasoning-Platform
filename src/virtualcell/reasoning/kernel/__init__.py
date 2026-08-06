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

Nothing here imports from :mod:`virtualcell.agents`, and a test enforces that. It is what
makes "domain-independent" a checkable property rather than an intention.
"""

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
    excludes_weak_relations,
    ground_links,
    rendered_step,
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
    "INTERPRETATION_CONFIDENCE",
    "MEASUREMENT_CONFIDENCE",
    "WEAK_RELATIONS",
    "WEAK_STEPS",
    "AssertionSafetyError",
    "GroundingError",
    "LinkAdmission",
    "all_of",
    "assertion_texts",
    "excludes_weak_relations",
    "forbidden_phrases_in",
    "ground_links",
    "interpretation_claim",
    "measurement_claim",
    "rendered_step",
    "targets_in",
    "validate_assertions",
]
