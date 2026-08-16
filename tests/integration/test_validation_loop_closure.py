"""The acceptance test for PR16: a recommendation the platform makes must be one it can read.

Four steps, all through the shipped service — no direct builder calls, so this is a claim
about the product and not about a test harness:

    1. ask the *mechanism* path what needs verifying
    2. take an axis it named and actually measure it
    3. hand the measurement to the *assessment* path
    4. the measurement becomes evidence, and the same request stops being made

Step 4 is the one that was broken. The vertical asked for genomic stability in step 1 and,
handed the answer in step 3, produced a report byte-identical to never having measured it.
"""

from __future__ import annotations

import asyncio

import pytest

from virtualcell.agents.immortalization.models import GenomicStabilityValue, RetentionValue
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.platform.bootstrap import default_registry, seed_registered_domains
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.service import ReasoningService

CULTURE = {
    "species": "bovine",
    "cell_type": "fibroblast",
    "PDL_trend": "increasing",
    "DT_trend": "stable",
    "gammaH2AX": "low",
    "SA_b_gal": "low",
    "p16": "low",
    "p21": "low",
}


def _query(task: str, **experiment) -> ReasoningResponse:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    service = ReasoningService(store, default_registry())
    payload = {"domain": "immortalization", "task": task, "experiment": experiment}
    return asyncio.run(service.query(ReasoningQuery.model_validate(payload)))


def _mechanism_asks_for() -> list[str]:
    """Step 1 — what the vertical says a TERT+CDK4 line still needs."""
    return _query("explain_mechanism", construct="TERT_plus_CDK4", **CULTURE).recommended_validation


# --- step 1: the mechanism path names both axes ------------------------------


def test_the_mechanism_path_asks_for_both_validation_axes() -> None:
    asked = " | ".join(_mechanism_asks_for()).lower()
    assert "genomic stability" in asked
    assert "functionality" in asked  # "Adipogenic or myogenic functionality"


# --- steps 2-4: the assessment path reads the answer back --------------------


@pytest.mark.parametrize(
    ("axis", "measured", "adverse", "gap_assay"),
    [
        ("genomic_stability", "stable", "abnormal", "Karyotype / genomic-stability assay"),
        (
            "adipogenic_retention",
            "retained",
            "lost",
            "Differentiation assay (adipogenic / myogenic)",
        ),
    ],
)
def test_measuring_a_requested_axis_removes_the_request(
    axis: str, measured: str, adverse: str, gap_assay: str
) -> None:
    """The invariant: an answered question stops being asked.

    Checked in both directions, because a reassuring answer and an alarming one close the
    request for different reasons — one because there is nothing left to look at, the other
    because the next question is no longer "measure this".
    """
    unmeasured = _query("assess_state", **CULTURE, **{axis: "unknown"})
    assert gap_assay in unmeasured.recommended_next_experiments

    for value in (measured, adverse):
        answered = _query("assess_state", **CULTURE, **{axis: value})
        assert gap_assay not in answered.recommended_next_experiments, value


@pytest.mark.parametrize(
    ("axis", "value", "expected_statement"),
    [
        ("genomic_stability", "stable", "Genomic stability is reported as stable."),
        ("genomic_stability", "abnormal", "Genomic stability is reported as abnormal."),
        ("adipogenic_retention", "retained", "Adipogenic differentiation capacity is retained."),
        ("adipogenic_retention", "lost", "Adipogenic differentiation capacity is lost."),
    ],
)
def test_the_measurement_becomes_evidence(axis: str, value: str, expected_statement: str) -> None:
    response = _query("assess_state", **CULTURE, **{axis: value})
    stated = [
        claim.statement
        for claim in (*response.supporting_evidence, *response.contradicting_evidence)
    ]
    assert expected_statement in stated


@pytest.mark.parametrize(
    ("axis", "value"),
    [("genomic_stability", v) for v in GenomicStabilityValue]
    + [("adipogenic_retention", v) for v in RetentionValue],
)
def test_no_validation_axis_can_move_the_candidate_status(axis: str, value) -> None:
    """The line this PR must not cross, checked over each axis's *whole* vocabulary — so a
    value added later is covered without anyone remembering to extend this list.

    Whether the karyotype is clean says nothing about whether the cells are still dividing,
    and the status reports only the latter.
    """
    response = _query("assess_state", **CULTURE, **{axis: value.value})
    assert response.decision_support.status == "possible_candidate"


def test_an_adverse_result_is_not_treated_as_a_missing_measurement() -> None:
    """The subtler half of step 4. Re-requesting the assay would say the platform never
    registered the answer; the follow-up has to ask the *next* question."""
    unstable = _query("assess_state", **CULTURE, genomic_stability="abnormal")
    plan = " | ".join(unstable.recommended_next_experiments)
    assert "Karyotype / genomic-stability assay" not in plan
    assert "clonal and progressing" in plan

    lost = _query("assess_state", **CULTURE, adipogenic_retention="lost")
    plan = " | ".join(lost.recommended_next_experiments)
    assert "Differentiation assay (adipogenic / myogenic)" not in plan
    assert "earlier-passage reference" in plan


def test_closing_the_loop_did_not_license_a_clearance_claim() -> None:
    """Both axes answered favourably is the strongest input this vertical accepts, and it
    still may not read as a cleared line."""
    response = _query(
        "assess_state", **CULTURE, genomic_stability="stable", adipogenic_retention="retained"
    )
    asserted = " ".join(
        [
            response.summary,
            *(c.statement for c in response.supporting_evidence),
            *(c.statement for c in response.contradicting_evidence),
        ]
    ).lower()
    for phrase in ("safe cell line", "non-tumorigenic", "production-ready", "food safe"):
        assert phrase not in asserted

    # ...and it says so out loud rather than leaving the reader to infer it.
    risks = " ".join(response.overinterpretation_risks).lower()
    assert "does not establish a safe" in risks
    assert "one axis of utility" in risks
