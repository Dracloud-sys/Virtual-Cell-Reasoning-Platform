"""Shared decision-report assembly (PR14b).

Two functions, because two is what the comparison supported. These tests check the three
things that make an extraction worth having: the primitives do what both verticals were
doing, both verticals actually *call* them, and a domain that is not either of them can use
them without the kernel knowing anything about it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from virtualcell.agents.adipogenesis import AdipogenesisAssessmentInput, assess
from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.rules import build_decision_report
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.platform.bootstrap import seed_registered_domains
from virtualcell.reasoning.kernel import UNMEASURED, missing_axes, ordered_unique

# --- missing-axis assembly ----------------------------------------------------


def test_missing_axes_subtracts_measured_from_required() -> None:
    required = ("a", "b", "c")
    assert missing_axes(required, {"a": 1, "b": None, "c": "unknown"}) == ["b", "c"]
    assert missing_axes(required, {"a": 1, "b": 2, "c": 3}) == []


def test_missing_axes_keeps_declared_order_not_set_order() -> None:
    """A report a person reads must not shuffle its own gaps between runs."""
    required = ("z", "m", "a")
    assert missing_axes(required, dict.fromkeys(required)) == ["z", "m", "a"]


def test_an_axis_nobody_reported_counts_as_unmeasured() -> None:
    """Absent from the values map is the same as having no reading — a caller must not have
    to remember to write the key in before it counts."""
    assert missing_axes(("a", "b"), {"a": 1}) == ["b"]


def test_unknown_and_none_both_mean_no_reading_by_default() -> None:
    """Stated once: a domain counting "unknown" as measured would report an axis as covered
    when nobody looked at it."""
    assert set(UNMEASURED) == {None, "unknown"}
    assert missing_axes(("a", "b"), {"a": None, "b": "unknown"}) == ["a", "b"]


def test_a_domain_may_declare_its_own_spelling_of_no_reading() -> None:
    """Immortalization spells it ``MarkerValue.UNKNOWN``; the kernel does not care which
    sentinel a vertical uses, only that the vertical says which."""
    assert missing_axes(("a", "b"), {"a": "n/a", "b": 1}, unmeasured={"n/a"}) == ["a"]
    # ...and the default no longer applies once the caller states its own.
    assert missing_axes(("a",), {"a": None}, unmeasured={"n/a"}) == []


def test_missing_axes_knows_nothing_about_biology() -> None:
    """Rule 3: policy in, assembly out. The same call works on axes that are not markers."""
    assert missing_axes(("temperature", "pH"), {"temperature": 37.0}) == ["pH"]


# --- ordered suggestion assembly ----------------------------------------------


def test_ordered_unique_keeps_first_seen_order() -> None:
    assert ordered_unique(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_ordered_unique_preserves_priority_rather_than_sorting() -> None:
    """Sorting or set-ing would lose the order, and the order is the priority."""
    assert ordered_unique(["urgent", "later"]) != sorted(["urgent", "later"])
    assert ordered_unique([]) == []


# --- both verticals actually use them -----------------------------------------


def _store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    return store


def test_immortalization_reaches_its_missing_axes_through_the_kernel(monkeypatch) -> None:
    """Behaviour, not source inspection: if the shared primitive is bypassed, this fails."""
    import virtualcell.agents.immortalization.rules as rules

    calls: list[tuple] = []
    original = rules.missing_axes

    def spy(required, values, **kwargs):
        calls.append((tuple(required), tuple(sorted(values))))
        return original(required, values, **kwargs)

    monkeypatch.setattr(rules, "missing_axes", spy)
    report = build_decision_report(
        input_from_scenario("immortalization_assessment", {"PDL_trend": "increasing"})
    )
    assert calls, "the immortalization builder did not use the shared assembly"
    assert report.missing_axes


def test_adipogenesis_reaches_its_missing_axes_through_the_kernel(monkeypatch) -> None:
    import virtualcell.agents.adipogenesis.assessment as assessment

    calls: list[tuple] = []
    original = assessment.missing_axes

    def spy(required, values, **kwargs):
        calls.append(tuple(required))
        return original(required, values, **kwargs)

    monkeypatch.setattr(assessment, "missing_axes", spy)
    outcome = assess(AdipogenesisAssessmentInput(PPARG="high"), _store())
    assert calls, "the adipogenesis builder did not use the shared assembly"
    assert outcome.report.missing_axes


def test_one_primitive_two_different_answers() -> None:
    """Policy injection is the whole point: the same subtraction, different required axes,
    different results — with no branch inside the kernel."""
    immo = build_decision_report(input_from_scenario("immortalization_assessment", {}))
    adipo = assess(AdipogenesisAssessmentInput(), _store()).report
    assert set(immo.missing_axes).isdisjoint(adipo.missing_axes)
    assert immo.missing_axes and adipo.missing_axes


def test_the_two_domains_still_differ_everywhere_the_comparison_said_they_should() -> None:
    """A shared primitive must not have quietly homogenised the reports around it."""
    immo = build_decision_report(
        input_from_scenario("immortalization_assessment", {"gammaH2AX": "high"})
    )
    adipo = assess(AdipogenesisAssessmentInput(PPARG="high"), _store())
    assert immo.candidate_status is not None
    assert adipo.report.candidate_status is None  # still not representable, by design
    assert adipo.status.value == "insufficient_evidence"
    assert " ".join(immo.next_experiment) != " ".join(adipo.report.next_experiment)


# --- a domain the kernel has never heard of -----------------------------------


def test_a_third_domain_can_assemble_a_report_with_the_shared_primitives() -> None:
    """No third vertical is implemented — just enough policy to show the primitives take
    data and give back assembly, for a biology neither was written for."""
    required = ("myod1", "myogenin", "myotube_fusion_index")
    readings = {"myod1": "high", "myogenin": None, "myotube_fusion_index": "unknown"}

    gaps = missing_axes(required, readings)
    assert gaps == ["myogenin", "myotube_fusion_index"]

    assay_for = {
        "myod1": "Myogenic qPCR panel",
        "myogenin": "Myogenic qPCR panel",  # one assay covers two axes
        "myotube_fusion_index": "Fusion-index imaging",
    }
    suggestions = ordered_unique(assay_for[axis] for axis in gaps)
    assert suggestions == ["Myogenic qPCR panel", "Fusion-index imaging"]


def test_the_assembly_module_knows_about_no_domain() -> None:
    """The PR14a boundary, extended to the new module."""
    module = pathlib.Path("src/virtualcell/reasoning/kernel/assembly.py")
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(name.startswith("virtualcell.agents") for name in imported)
    # It imports nothing from the platform either: assembly is not dispatch.
    assert not any(name.startswith("virtualcell.platform") for name in imported)


@pytest.mark.parametrize("name", ["missing_axes", "ordered_unique", "UNMEASURED"])
def test_the_primitives_are_exported_from_the_kernel(name: str) -> None:
    import virtualcell.reasoning.kernel as kernel

    assert name in kernel.__all__
    assert hasattr(kernel, name)
