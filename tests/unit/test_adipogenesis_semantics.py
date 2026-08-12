"""The adipogenesis semantics that expansion must not change.

Written before the expansion, so the four rules the minimal vertical established are pinned
independently of the code that will grow around them. Every one of these is a claim about
biology, not about implementation, and each should survive any amount of new axes.

`test_adipogenesis_vertical.py` covers the vertical's behaviour in detail; this file exists to
state the load-bearing four on their own, where a regression cannot hide among 40 other
assertions.
"""

from __future__ import annotations

import pytest

from virtualcell.agents.adipogenesis import (
    AdipogenesisAssessmentInput,
    DifferentiationStatus,
    assess,
)
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.adipogenesis_seed import AdipogenesisSeedSource
from virtualcell.knowledge.sources.base import load_into


def _store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(AdipogenesisSeedSource(), store)
    return store


def _assess(**markers):
    return assess(AdipogenesisAssessmentInput(**markers), _store())


def test_a_marker_panel_alone_is_never_differentiation() -> None:
    """The rule the vertical was built around. The program running says the cell is trying;
    lipid says it succeeded, and nothing here measured lipid."""
    outcome = _assess(PPARG="high", CEBPA="high", FABP4="high", ADIPOQ="high")
    assert outcome.status is DifferentiationStatus.INSUFFICIENT_EVIDENCE


def test_program_plus_lipid_is_differentiation() -> None:
    outcome = _assess(PPARG="high", CEBPA="high", FABP4="high", lipid_accumulation="high")
    assert outcome.status is DifferentiationStatus.DIFFERENTIATING


def test_an_active_inhibitor_with_no_program_is_inhibition_not_absence() -> None:
    """A program that never started is a protocol question; one held down is a biology
    question. Collapsing them loses the more actionable finding."""
    outcome = _assess(PPARG="low", CEBPA="low", lipid_accumulation="absent", WNT_signalling="high")
    assert outcome.status is DifferentiationStatus.DIFFERENTIATION_INHIBITED


def test_no_useful_readings_is_insufficient_evidence() -> None:
    assert _assess().status is DifferentiationStatus.INSUFFICIENT_EVIDENCE
    assert _assess(PPARG="unknown").status is DifferentiationStatus.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize(
    "phrase", ["mature adipocyte", "fully differentiated", "transdifferentiation", "food safe"]
)
def test_the_safety_boundary_holds_for_every_status(phrase: str) -> None:
    """Expansion is exactly when a safety boundary erodes, so it is checked across the whole
    status space rather than on one happy path."""
    scenarios = [
        {"PPARG": "high", "CEBPA": "high", "FABP4": "high", "lipid_accumulation": "high"},
        {"PPARG": "high", "CEBPA": "high"},
        {"PPARG": "low", "CEBPA": "low", "lipid_accumulation": "absent"},
        {"PPARG": "low", "WNT_signalling": "high"},
        {},
    ]
    for scenario in scenarios:
        report = _assess(**scenario).report
        asserted = " ".join(
            [
                report.conclusion,
                *(c.statement for c in report.supporting_evidence),
                *(c.statement for c in report.contradicting_evidence),
            ]
        ).lower()
        assert phrase not in asserted


def test_lipid_is_never_equated_with_maturity_in_an_assertion() -> None:
    """The specific conflation the vertical exists to refuse: a cell storing lipid is doing
    what an adipocyte does, which is not the same as being a finished one."""
    report = _assess(
        PPARG="high", CEBPA="high", FABP4="high", ADIPOQ="high", lipid_accumulation="high"
    ).report
    assert any("mature" in limit.lower() for limit in report.limitations)  # said as a limit...
    assert "mature adipocyte" not in report.conclusion.lower()  # ...never as a claim
