"""The platform's one numeric value grammar (PR8c, relocated in PR13b).

Reading "2.4", "<0.05" or "2.4 ± 0.3" out of a source string is the same problem whether
the source is a table cell in a paper or a cell in an uploaded CSV, and the *conservative*
answer must be the same in both places. A second grammar would be a second set of edge
cases, and the edge cases are the whole point: a bound must never become a point estimate,
an uncertainty must never become a value, and ambiguous text must never gain a number.

This lives in ``core`` because both :mod:`virtualcell.literature` and
:mod:`virtualcell.ingestion` are consumers, and neither should depend on the other for it.

What the grammar refuses is as important as what it accepts:

* ``1,234`` — thousands separator or decimal comma? Refused whole, raw text preserved.
* ``increased``, ``NS``, ``ND`` — qualitative; a number is never fabricated.
* ``<0.05`` — parsed, but the comparator is kept *separately* so the value is never later
  read as a point estimate.
* ``2.4 ± 0.3`` — the error is kept separately and never mistaken for the value.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel


class ParseStatus(StrEnum):
    """Whether a numeric value could be taken from the raw source text."""

    PARSED = "parsed"
    UNPARSED = "unparsed"


_COMPARATOR = re.compile(r"^\s*(<=|>=|≤|≥|<|>|~|≈)\s*")
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_UNCERTAINTY = re.compile(r"(?:±|\+/-|\+-)\s*([-+]?\d+(?:\.\d+)?)")
# "1,234" is ambiguous (thousands separator vs decimal comma). Rather than guess, a
# digit-comma-digit value stays UNPARSED with its raw text preserved.
_AMBIGUOUS_SEPARATOR = re.compile(r"\d,\d")
_UNIT_AFTER = re.compile(
    r"^\s*[-\s]?(fold|%|percent|h|hr|hrs|hour|hours|day|days|min|minutes|"
    r"nm|µm|um|mm|cm|ml|µl|ul|mg|µg|ug|ng|kda|bp|kb)\b",
    re.IGNORECASE,
)
_NON_NUMERIC_TOKENS = {"ns", "nd", "n/a", "na", "-", "—", ""}

_COMPARATOR_CANON = {"≤": "<=", "≥": ">=", "≈": "~"}


class ParsedValue(BaseModel):
    """The outcome of reading one raw value string. Nothing is invented."""

    raw_value: str
    parsed_value: float | None = None
    comparator: str | None = None
    uncertainty: float | None = None
    unit: str | None = None
    parse_status: ParseStatus = ParseStatus.UNPARSED


def parse_value_text(text: str) -> ParsedValue:
    """Split a raw cell/span into value / comparator / uncertainty / unit.

    Conservative by design: ``2.4`` parses; ``2.4-fold`` parses with a unit;
    ``2.4 ± 0.3`` keeps the error separately; ``<0.05`` keeps the comparator (it is a
    bound, not a point estimate); ``increased`` / ``NS`` stay UNPARSED with no number;
    ``1,234`` stays UNPARSED because the separator is ambiguous.
    """
    raw = text.strip()
    if raw.lower() in _NON_NUMERIC_TOKENS:
        return ParsedValue(raw_value=raw)
    if _AMBIGUOUS_SEPARATOR.search(raw):
        # Thousands separator or decimal comma? Refuse to guess; keep the raw text.
        return ParsedValue(raw_value=raw)

    rest = raw
    comparator = None
    match = _COMPARATOR.match(rest)
    if match:
        comparator = _COMPARATOR_CANON.get(match.group(1), match.group(1))
        rest = rest[match.end() :]

    number = _NUMBER.search(rest)
    if not number:
        # No number anywhere: qualitative text ("increased"). Never fabricate one.
        return ParsedValue(raw_value=raw, comparator=comparator)

    value = float(number.group(0))
    tail = rest[number.end() :]

    uncertainty = None
    unc = _UNCERTAINTY.search(tail)
    if unc:
        uncertainty = float(unc.group(1))
        tail = tail[unc.end() :]

    unit = None
    unit_match = _UNIT_AFTER.match(tail)
    if unit_match:
        unit = unit_match.group(1).lower()

    return ParsedValue(
        raw_value=raw,
        parsed_value=value,
        comparator=comparator,
        uncertainty=uncertainty,
        unit=unit,
        parse_status=ParseStatus.PARSED,
    )
