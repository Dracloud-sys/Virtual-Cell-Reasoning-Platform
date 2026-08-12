"""Shared decision-report assembly (PR14b).

Deliberately two functions. Reading the immortalization and adipogenesis builders side by
side (`docs/pr14b_assembly_comparison.md`) turned up almost no shared *procedure* — nearly
every concern is either content generation that is pure biology, or a field both verticals
happen to fill. Manufacturing a larger assembly layer here would mean inventing structure
the evidence does not show.

What survived the comparison is what both verticals actually do the same way:

* work out which required axes went unmeasured, in declared order;
* collect an ordered suggestion list without repeats.

Both take policy as data and perform assembly only. Neither knows what an axis *is*, which
axes matter, or which assay answers which gap — those differ per biology and stay in the
pack. The test is the one from PR14a: would a different biology answer this differently?
"unmeasured means unmeasured" survives it; "a senescence axis is required" does not.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Sequence

UNMEASURED: frozenset[object] = frozenset({None, "unknown"})
"""What both verticals already treat as *no reading*.

Stated once because the alternative is each vertical deciding separately whether ``None``
and ``"unknown"`` mean the same thing — and a domain that counted ``"unknown"`` as measured
would report an axis as covered when nobody looked at it.
"""


def missing_axes(
    required: Sequence[str],
    values: dict[str, object],
    *,
    unmeasured: Iterable[object] = UNMEASURED,
) -> list[str]:
    """The required axes with no reading, in the order they were declared.

    Declared order rather than set order, because this list is read by a person and a report
    that shuffles its own gaps between runs is a report nobody can diff.

    Which axes are required, and what a reading means, are the caller's — this only performs
    the subtraction.
    """
    absent = set(unmeasured)
    return [axis for axis in required if values.get(axis) in absent]


def ordered_unique[T: Hashable](items: Iterable[T]) -> list[T]:
    """The items in first-seen order, without repeats.

    Suggestion lists — what to validate, what to run next — are assembled from several
    independent conditions, so the same assay can be reached twice. Listing it twice reads as
    emphasis nobody intended, and sorting or set-ing it would lose the priority the order
    carries.
    """
    seen: set[T] = set()
    unique: list[T] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique
