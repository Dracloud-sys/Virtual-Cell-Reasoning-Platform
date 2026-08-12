"""The minimal adipogenesis vertical — the second data point for PR14b.

This vertical exists to be an *independent* second implementation, so these tests pin the
two things that make it useful as evidence:

* its own science holds (a marker panel is not a fat cell), and
* it reaches a real report through the **kernel**, not through a copy of the
  immortalization builder.

It is minimal on purpose. There is no benchmark, no trajectory engine, and no attempt at
completeness — those belong to the expansion step after PR14b.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from virtualcell.agents.adipogenesis import (
    AdipogenesisAssessmentInput,
    AdipogenesisFlag,
    AdipogenesisIntent,
    AdipogenesisSafetyError,
    DifferentiationStatus,
    UnsupportedAdipogenesisIntentError,
    assess,
    build_mechanism_report,
)
from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.adipogenesis_seed import AdipogenesisSeedSource
from virtualcell.knowledge.sources.base import load_into


def _store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(AdipogenesisSeedSource(), store)
    return store


def _assess(**markers):
    return assess(AdipogenesisAssessmentInput(**markers), _store())


# --- the science: a marker panel is not a fat cell ----------------------------


def test_program_plus_lipid_is_differentiation() -> None:
    outcome = _assess(PPARG="high", CEBPA="high", FABP4="high", lipid_accumulation="high")
    assert outcome.status is DifferentiationStatus.DIFFERENTIATING
    assert AdipogenesisFlag.FUNCTION_UNMEASURED not in outcome.flags


def test_a_positive_panel_without_a_lipid_measurement_is_not_differentiation() -> None:
    """The overcall this vertical exists to refuse. The program running says the cell is
    trying; lipid says it succeeded, and nothing here measured lipid."""
    outcome = _assess(PPARG="high", CEBPA="high", FABP4="high", ADIPOQ="high")
    assert outcome.status is DifferentiationStatus.INSUFFICIENT_EVIDENCE
    assert AdipogenesisFlag.FUNCTION_UNMEASURED in outcome.flags
    assert "lipid_accumulation" in outcome.report.missing_axes
    assert any("Oil Red O" in e for e in outcome.report.next_experiment)


def test_the_report_says_why_expression_alone_is_not_enough() -> None:
    outcome = _assess(PPARG="high", CEBPA="high")
    assert any(
        "does not establish differentiation" in claim.statement
        for claim in outcome.report.contradicting_evidence
    )


def test_an_absent_program_with_absent_lipid_is_not_differentiating() -> None:
    outcome = _assess(PPARG="low", CEBPA="low", lipid_accumulation="absent")
    assert outcome.status is DifferentiationStatus.NOT_DIFFERENTIATING


def test_being_held_back_is_reported_differently_from_simply_failing() -> None:
    """Two findings, two next steps: a program that never started is a protocol question,
    one held down by WNT is a biology question. Collapsing them loses the actionable half."""
    inhibited = _assess(
        PPARG="low", CEBPA="low", lipid_accumulation="absent", WNT_signalling="high"
    )
    assert inhibited.status is DifferentiationStatus.DIFFERENTIATION_INHIBITED
    assert AdipogenesisFlag.INHIBITOR_ACTIVE in inhibited.flags
    assert any("WNT" in e for e in inhibited.report.next_experiment)

    plain = _assess(PPARG="low", CEBPA="low", lipid_accumulation="absent")
    assert plain.status is DifferentiationStatus.NOT_DIFFERENTIATING


def test_nothing_measured_is_insufficient_and_names_every_missing_axis() -> None:
    outcome = _assess()
    assert outcome.status is DifferentiationStatus.INSUFFICIENT_EVIDENCE
    assert set(outcome.report.missing_axes) == {
        "PPARG",
        "CEBPA",
        "FABP4",
        "ADIPOQ",
        "PLIN1",
        "lipid_accumulation",
    }


def test_unknown_is_not_a_reading() -> None:
    outcome = _assess(PPARG="unknown", lipid_accumulation="unknown")
    assert "PPARG" in outcome.report.missing_axes
    assert outcome.status is DifferentiationStatus.INSUFFICIENT_EVIDENCE


# --- evidence discipline ------------------------------------------------------


def test_measurements_and_interpretations_carry_different_tiers() -> None:
    """Via the kernel's constructors, so the convention cannot drift from the first
    vertical's."""
    outcome = _assess(PPARG="high", CEBPA="high", lipid_accumulation="high")
    tiers = {claim.tier for claim in outcome.report.supporting_evidence}
    assert EvidenceTier.ESTABLISHED in tiers  # the readings
    assert EvidenceTier.HYPOTHESIS in tiers  # what they are taken to mean

    measured = [c for c in outcome.report.supporting_evidence if " measured as " in c.statement]
    assert all(c.tier is EvidenceTier.ESTABLISHED for c in measured)
    assert all(c.assumptions for c in measured)


def test_every_report_carries_its_limitations_and_risks() -> None:
    outcome = _assess(PPARG="high", CEBPA="high", lipid_accumulation="high")
    assert any("mature adipocyte" in limit for limit in outcome.report.limitations)
    assert any("transdifferentiation" in risk for risk in outcome.report.overinterpretation_risk)


def test_guidance_naming_a_forbidden_phrase_is_not_itself_a_violation() -> None:
    """The kernel's assertion scope, exercised by a second domain: the report's own
    limitations quote "mature adipocyte" in order to forbid it, and that must not trip the
    safety check."""
    outcome = _assess(PPARG="high", CEBPA="high", lipid_accumulation="high")
    assert any("mature adipocyte" in limit for limit in outcome.report.limitations)  # it is there
    assert not any(
        "mature adipocyte" in claim.statement
        for claim in outcome.report.supporting_evidence  # ...and not asserted
    )


def test_a_forbidden_overclaim_in_an_assertion_is_refused() -> None:
    from virtualcell.agents.adipogenesis import assessment
    from virtualcell.reasoning.kernel import validate_assertions

    outcome = _assess(PPARG="high", CEBPA="high", lipid_accumulation="high")
    overclaimed = outcome.report.model_copy(
        update={"conclusion": "These are fully differentiated mature adipocytes."}
    )
    with pytest.raises(AdipogenesisSafetyError):
        validate_assertions(
            overclaimed,
            assessment._FORBIDDEN,
            error=AdipogenesisSafetyError,
            context="adipogenesis report",
        )


# --- it reaches a report through the kernel, not a copy -----------------------


def test_the_mechanism_chain_is_grounded_from_the_graph() -> None:
    report = build_mechanism_report(
        AdipogenesisAssessmentInput(intent=AdipogenesisIntent.MECHANISM_EXPLANATION), _store()
    )
    targets = {link.target_id for link in report.mechanistic_chain}
    assert "mechanism:adipogenic_transcription_program" in targets
    assert report.candidate_status is None  # a mechanism question has no status


def test_the_inhibitory_arm_is_grounded_as_well_as_the_driving_one() -> None:
    """Both directions are real biology; a chain that showed only the promoting arm would
    quietly present a one-sided mechanism."""
    report = build_mechanism_report(
        AdipogenesisAssessmentInput(intent=AdipogenesisIntent.MECHANISM_EXPLANATION), _store()
    )
    steps = [step for link in report.mechanistic_chain for step in link.path]
    assert any("-promotes->" in step for step in steps)
    assert any("-inhibits->" in step for step in steps)


def test_assay_edges_never_enter_the_mechanism_chain() -> None:
    """An assay reports on biology; it does not drive it. ``INDICATES`` is not in this
    pack's declared mechanistic relations, so the kernel refuses those paths."""
    report = build_mechanism_report(
        AdipogenesisAssessmentInput(intent=AdipogenesisIntent.MECHANISM_EXPLANATION), _store()
    )
    steps = [step for link in report.mechanistic_chain for step in link.path]
    assert not any("-indicates->" in step for step in steps)
    assert not any("-suggests_next_test->" in step for step in steps)


def test_the_vertical_uses_the_kernel_and_does_not_import_the_first_one() -> None:
    """The whole value of a second data point is that it was written independently. An
    import from the immortalization vertical would make any similarity an artifact."""
    package = pathlib.Path("src/virtualcell/agents/adipogenesis")
    modules = sorted(package.rglob("*.py"))
    assert modules

    uses_kernel = False
    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert not any(
            name.startswith("virtualcell.agents.immortalization") for name in imported
        ), f"{module.name} imports the first vertical"
        uses_kernel |= any(name.startswith("virtualcell.reasoning.kernel") for name in imported)
    assert uses_kernel, "the second vertical should reach its report through the kernel"


# --- intent discipline --------------------------------------------------------


def test_each_builder_refuses_the_other_intent() -> None:
    with pytest.raises(UnsupportedAdipogenesisIntentError):
        assess(
            AdipogenesisAssessmentInput(intent=AdipogenesisIntent.MECHANISM_EXPLANATION), _store()
        )
    with pytest.raises(UnsupportedAdipogenesisIntentError):
        build_mechanism_report(
            AdipogenesisAssessmentInput(intent=AdipogenesisIntent.DIFFERENTIATION_ASSESSMENT),
            _store(),
        )


def test_an_unknown_marker_field_is_refused_rather_than_ignored() -> None:
    """A typo'd marker silently dropped would read as 'not measured' — the same class of
    silent loss the ingestion layer refuses."""
    with pytest.raises(ValueError, match="extra"):
        AdipogenesisAssessmentInput(PPARGG="high")


def test_assessment_is_deterministic() -> None:
    first = _assess(PPARG="high", CEBPA="high", lipid_accumulation="high")
    second = _assess(PPARG="high", CEBPA="high", lipid_accumulation="high")
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
