"""The platform's measurement-consumption vocabulary.

Contract-level only: the states, what each promises, and the invariants that keep a ledger
from contradicting itself. Which measurement lands in which state is domain policy and is
tested against the packs in `tests/integration/test_measurement_consumption_surfaces.py`.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from pydantic import ValidationError

from virtualcell.core.consumption import (
    ConsumptionLedger,
    ConsumptionReport,
    ConsumptionStatus,
    MeasurementConsumption,
)

_MODULE = pathlib.Path("src/virtualcell/core/consumption.py")


# The smallest *valid* entry for each state. Doubles as the fixture for the invariant tests
# below: every invalid case is one of these with a single field spoiled, so a failure names
# exactly which invariant broke rather than which fixture was malformed.
VALID: dict[ConsumptionStatus, dict] = {
    ConsumptionStatus.USED_FOR_STATUS: {
        "submitted_as": "p16",
        "canonical_name": "p16",
        "used_for": ["candidate_status"],
    },
    ConsumptionStatus.USED_FOR_GUIDANCE: {
        "submitted_as": "genomic_stability",
        "canonical_name": "genomic_stability",
        "used_for": ["flag:genomic_instability_detected"],
    },
    ConsumptionStatus.NOT_APPLICABLE: {
        "submitted_as": "species",
        "canonical_name": "species",
        "reason": "carried as context and read by no builder",
    },
    ConsumptionStatus.UNSUPPORTED: {
        "submitted_as": "gamaH2AX",
        "reason": "no axis of this name exists",
    },
    ConsumptionStatus.QUALITY_EXCLUDED: {
        "submitted_as": "cumulative_PDL",
        "canonical_name": "cumulative_PDL",
        "reason": "QC recorded this reading as 'suspect'",
    },
}


def _entry(status: ConsumptionStatus, **overrides) -> MeasurementConsumption:
    return MeasurementConsumption(status=status, **{**VALID[status], **overrides})


# --- the states are distinct, and stay distinct -------------------------------


def test_every_state_is_reachable_and_distinct() -> None:
    """Five states because five things can happen. If two ever collapse, a caller loses the
    distinction the ledger exists to give them — chiefly 'we could not trust this value'
    versus 'we had nothing to use it for'."""
    values = [s.value for s in ConsumptionStatus]
    assert values == [
        "used_for_status",
        "used_for_guidance",
        "not_applicable",
        "unsupported",
        "quality_excluded",
    ]
    assert len(set(values)) == len(values)


@pytest.mark.parametrize("status", list(ConsumptionStatus))
def test_only_the_status_state_claims_to_have_moved_the_verdict(status) -> None:
    """`affected_status` is derived from `status`, never stored beside it, so the two cannot
    drift apart — the same one-authority rule PR16 applied to genomic stability."""
    entry = _entry(status)
    assert entry.affected_status is (status is ConsumptionStatus.USED_FOR_STATUS)


def test_guidance_does_not_count_as_having_touched_the_verdict() -> None:
    """The distinction PR16 was written to create: an axis can raise a flag, add evidence
    and change the next experiment while leaving the status untouched."""
    guidance = MeasurementConsumption(
        submitted_as="genomic_stability",
        canonical_name="genomic_stability",
        status=ConsumptionStatus.USED_FOR_GUIDANCE,
        used_for=["flag:genomic_instability_detected", "next_experiment"],
    )
    assert guidance.used_for  # it did real work...
    assert guidance.affected_status is False  # ...and none of it was the verdict


def test_an_entry_cannot_be_edited_after_the_fact() -> None:
    """Frozen as well as validated: without it, a caller could construct a legal entry and
    then mutate `status` into a combination the validator would have rejected."""
    entry = _entry(ConsumptionStatus.USED_FOR_STATUS)
    with pytest.raises(ValidationError):
        entry.status = ConsumptionStatus.UNSUPPORTED


# --- the invariants hold at the model boundary, not just in the builder -------
#
# The point of these: a platform contract that only holds when the convenience builder is
# used is a convention. A deserialised HTTP payload, a future pack, or a test fixture must
# be equally unable to express a self-contradicting entry.


@pytest.mark.parametrize("status", list(ConsumptionStatus))
def test_the_minimal_valid_entry_for_every_state_is_accepted(status) -> None:
    assert _entry(status).status is status


@pytest.mark.parametrize("status", list(ConsumptionStatus))
def test_canonical_name_is_absent_exactly_when_the_name_was_not_recognised(status) -> None:
    """The biconditional that separates the two ways a value goes unused: `unsupported`
    means we have never heard of it, everything else means we knew it and did not use it.
    If a recognised state could omit the name, that distinction would blur."""
    unsupported = status is ConsumptionStatus.UNSUPPORTED
    assert (_entry(status).canonical_name is None) is unsupported

    with pytest.raises(ValidationError):
        _entry(status, canonical_name=None if not unsupported else "gammaH2AX")


@pytest.mark.parametrize(
    "status", [ConsumptionStatus.USED_FOR_STATUS, ConsumptionStatus.USED_FOR_GUIDANCE]
)
def test_a_consumed_entry_must_name_what_read_it(status) -> None:
    """Claiming a value was used while naming nothing that used it is the assertion this
    ledger exists to make impossible."""
    with pytest.raises(ValidationError):
        _entry(status, used_for=[])


@pytest.mark.parametrize(
    "status", [ConsumptionStatus.USED_FOR_STATUS, ConsumptionStatus.USED_FOR_GUIDANCE]
)
def test_a_consumed_entry_must_not_carry_a_reason(status) -> None:
    """`reason` answers "why was this not used". Beside a consumed value it would read as a
    caveat on a verdict that does not have one."""
    with pytest.raises(ValidationError):
        _entry(status, reason="but only a little")


@pytest.mark.parametrize(
    "status",
    [
        ConsumptionStatus.NOT_APPLICABLE,
        ConsumptionStatus.UNSUPPORTED,
        ConsumptionStatus.QUALITY_EXCLUDED,
    ],
)
def test_an_unconsumed_entry_must_explain_itself_and_claim_no_purpose(status) -> None:
    with pytest.raises(ValidationError):
        _entry(status, used_for=["candidate_status"])
    with pytest.raises(ValidationError):
        _entry(status, reason=None)
    with pytest.raises(ValidationError):
        _entry(status, reason="   ")  # blank is not an explanation


def test_a_deserialised_payload_is_validated_too() -> None:
    """The route that bypasses the builder entirely."""
    payload = {
        "submitted_as": "gamaH2AX",
        "canonical_name": "gammaH2AX",  # unsupported names resolve to nothing
        "status": "unsupported",
        "reason": "typo",
    }
    with pytest.raises(ValidationError):
        MeasurementConsumption.model_validate(payload)


def test_guidance_cannot_be_made_to_claim_the_verdict() -> None:
    """No validator needed: `affected_status` is computed, so the contradiction is not
    representable. Pinned because a later refactor to a stored field would silently allow it."""
    assert "affected_status" not in MeasurementConsumption.model_fields
    payload = {**VALID[ConsumptionStatus.USED_FOR_GUIDANCE], "status": "used_for_guidance"}
    assert (
        MeasurementConsumption.model_validate({**payload, "affected_status": True}).affected_status
        is False
    )


# --- the ledger records; it does not decide -----------------------------------


def test_the_ledger_preserves_submission_order() -> None:
    """Order is the caller's own, so an entry is findable against the request that produced
    it. Sorting would be tidier and would break that correspondence."""
    ledger = ConsumptionLedger()
    ledger.used_for_status("zebra", used_for=["s"]).unsupported("alpha").not_applicable(
        "middle", reason="because"
    )
    assert [e.submitted_as for e in ledger.report().entries] == ["zebra", "alpha", "middle"]


def test_an_unsupported_entry_always_carries_a_reason() -> None:
    """A bare 'unsupported' with no explanation helps nobody; the default reason exists so
    a pack cannot accidentally ship one."""
    entry = ConsumptionLedger().unsupported("typo").report().entries[0]
    assert entry.reason
    assert entry.canonical_name is None  # it resolved to nothing, and says so


def test_a_default_provenance_applies_unless_an_entry_overrides_it() -> None:
    ledger = ConsumptionLedger(provenance="query.experiment")
    ledger.used_for_status("PDL_trend", used_for=["candidate_status"])
    ledger.quality_excluded("DT_hours", reason="suspect", provenance="run:x:observations[2]")
    default, override = ledger.report().entries
    assert default.provenance == "query.experiment"
    assert override.provenance == "run:x:observations[2]"


def test_canonical_name_defaults_to_the_submitted_name_for_consumed_entries() -> None:
    entry = ConsumptionLedger().used_for_status("p16", used_for=["candidate_status"])
    assert entry.report().entries[0].canonical_name == "p16"


# --- the report's summaries agree with its entries ----------------------------


def test_the_summaries_are_derived_from_the_entries() -> None:
    ledger = ConsumptionLedger()
    ledger.used_for_status("p16", used_for=["candidate_status"])
    ledger.used_for_guidance("genomic_stability", used_for=["flag:x"])
    ledger.unsupported("gamaH2AX")
    ledger.not_applicable("species", reason="context only")
    report = ledger.report()

    assert report.unsupported == ["gamaH2AX"]
    assert report.status_inputs == ["p16"]
    assert len(report.by_status(ConsumptionStatus.NOT_APPLICABLE)) == 1


def test_an_empty_report_is_valid_and_says_nothing() -> None:
    """A domain with no declared policy must report nothing rather than something wrong —
    which is also what keeps this field additive for every existing caller."""
    report = ConsumptionReport()
    assert report.entries == []
    assert report.unsupported == []
    assert report.status_inputs == []


def test_the_summaries_survive_a_json_round_trip() -> None:
    """They are computed fields, so they must serialise — an HTTP caller cannot call a
    Python property."""
    ledger = ConsumptionLedger().used_for_status("p16", used_for=["candidate_status"])
    payload = ledger.report().model_dump(mode="json")
    assert payload["status_inputs"] == ["p16"]
    assert payload["entries"][0]["affected_status"] is True


# --- the boundary this module must not cross ----------------------------------


def test_the_vocabulary_knows_no_domain() -> None:
    """The same rule the reasoning kernel lives under: a platform contract that imported a
    vertical would let one domain's science leak into every domain's response shape."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(name.startswith("virtualcell") for name in imported), imported


def test_no_biological_term_appears_in_the_vocabulary_itself() -> None:
    """Checked over the state names rather than the prose: the docstrings cite immortalization
    and adipogenesis as examples, which is explanation, not coupling."""
    names = " ".join(s.value for s in ConsumptionStatus).lower()
    for term in ("senescence", "adipo", "immortal", "karyotype", "lipid", "marker"):
        assert term not in names
