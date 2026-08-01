"""Contract tests for the domain-neutral query/response boundary (PR11)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from virtualcell.core.evidence import Claim, EvidenceTier
from virtualcell.platform.contracts import (
    DecisionSupport,
    ExplanationLevel,
    LiteratureOutcome,
    LiteratureStatus,
    QueryProvenance,
    ReasoningQuery,
    ReasoningResponse,
)
from virtualcell.reasoning.explain import MechanisticLink


def _query(**over) -> ReasoningQuery:
    payload = {
        "domain": "immortalization",
        "task": "assess_state",
        "question": "Does this evidence support an immortalization candidate?",
        "experiment": {"intent": "immortalization_assessment", "PDL_trend": "increasing"},
        "explanation_level": "practitioner",
        "allow_literature": False,
        "target_measurements": ["TERT"],
    }
    payload.update(over)
    return ReasoningQuery.model_validate(payload)


# --- request ----------------------------------------------------------------


def test_valid_request_round_trips() -> None:
    query = _query()
    assert ReasoningQuery.model_validate(query.model_dump(mode="json")) == query
    # The normalised experiment payload survives verbatim — no semantic loss.
    assert query.experiment["intent"] == "immortalization_assessment"
    assert query.experiment["PDL_trend"] == "increasing"


def test_domain_is_not_defaulted_to_immortalization() -> None:
    # The generic contract must not smuggle in a default vertical.
    with pytest.raises(ValidationError):
        ReasoningQuery.model_validate({"task": "assess_state"})
    assert "immortalization" not in str(ReasoningQuery.model_fields["domain"])


@pytest.mark.parametrize("bad", ["", "   "])
def test_blank_domain_or_task_is_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        _query(domain=bad)
    with pytest.raises(ValidationError):
        _query(task=bad)


def test_invalid_explanation_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _query(explanation_level="phd-student")


def test_explanation_levels_are_an_explicit_set() -> None:
    assert {level.value for level in ExplanationLevel} == {"novice", "practitioner", "expert"}


@pytest.mark.parametrize("bad", [[""], ["  "], [None], [3]])
def test_invalid_target_measurements_are_rejected(bad: list) -> None:
    with pytest.raises(ValidationError):
        _query(target_measurements=bad)


def test_target_measurements_are_cleaned_and_deduplicated() -> None:
    query = _query(target_measurements=[" TERT ", "CDK4", "TERT"])
    assert query.target_measurements == ["TERT", "CDK4"]  # order preserved


def test_question_is_optional_and_blank_becomes_none() -> None:
    assert _query(question=None).question is None
    assert _query(question="   ").question is None


def test_allow_literature_defaults_to_false_and_is_explicit() -> None:
    assert _query().allow_literature is False
    assert ReasoningQuery(domain="d", task="t").allow_literature is False


# --- response ---------------------------------------------------------------


def _response() -> ReasoningResponse:
    return ReasoningResponse(
        domain="immortalization",
        task="assess_state",
        summary="A summary.",
        supporting_evidence=[
            Claim(
                statement="TERT supports telomere maintenance.",
                tier=EvidenceTier.ESTABLISHED,
                confidence=0.9,
                citations=["curated:immortalization_seed"],
            )
        ],
        contradicting_evidence=[
            Claim(statement="p16 is elevated.", tier=EvidenceTier.HYPOTHESIS, confidence=0.5)
        ],
        mechanistic_links=[
            MechanisticLink(
                target_id="mechanism:telomere_maintenance",
                target_name="Telomere maintenance",
                hops=1,
                tier=EvidenceTier.ESTABLISHED,
                confidence=0.9,
                path=["TERT -promotes-> Telomere maintenance"],
            )
        ],
        decision_support=DecisionSupport(
            status="possible_candidate", flags=["trend_needed"], trend_required=True
        ),
        limitations=["Sustained proliferation does not establish genomic stability."],
        literature=LiteratureOutcome(status=LiteratureStatus.NOT_REQUESTED),
        provenance=QueryProvenance(
            domain="immortalization",
            task="assess_state",
            pack="immortalization.reference.v1",
            engine="immortalization_assessment",
            explanation_level=ExplanationLevel.PRACTITIONER,
        ),
        domain_details={"decision_report": {"conclusion": "A summary.", "flags": ["trend_needed"]}},
    )


def test_response_round_trips_without_losing_evidence_or_provenance() -> None:
    original = _response()
    restored = ReasoningResponse.model_validate(original.model_dump(mode="json"))

    assert restored == original
    # Tiers and citations survive serialisation — the traceability that matters.
    assert restored.supporting_evidence[0].tier is EvidenceTier.ESTABLISHED
    assert restored.supporting_evidence[0].citations == ["curated:immortalization_seed"]
    assert restored.contradicting_evidence[0].tier is EvidenceTier.HYPOTHESIS
    assert restored.mechanistic_links[0].path == ["TERT -promotes-> Telomere maintenance"]
    assert restored.provenance.pack == "immortalization.reference.v1"
    assert restored.decision_support.trend_required is True


def test_domain_extension_payload_is_preserved() -> None:
    restored = ReasoningResponse.model_validate(_response().model_dump(mode="json"))
    assert restored.domain_details["decision_report"]["flags"] == ["trend_needed"]


def test_literature_states_are_distinguishable() -> None:
    # A failure to look and a look that found nothing are different states.
    assert LiteratureStatus.PROVIDER_ERROR != LiteratureStatus.ZERO_RESULTS
    assert {s.value for s in LiteratureStatus} == {
        "not_requested",
        "unavailable",
        "success",
        "zero_results",
        "provider_error",
        "timeout",
    }
