"""Representative immortalization assessment cases (for researcher evaluation).

Runs three realistic, tricky synthetic cases through the deterministic
``ImmortalizationAssessmentAgent`` and prints the evidence-graded ``DecisionReport``.
These are the cases a cell engineer actually struggles with:

1. proliferating but with a worsening doubling time,
2. a plateau followed by a transient recovery,
3. proliferation retained but differentiation capacity lost.

They also surface v0 limitations to feed benchmark v0.1 — notably that the marker
vocabulary is single-snapshot (no raw doubling-time hours, passage number, or
time-series), so case 2's transient recovery collapses to one label.

Run: ``python examples/02_immortalization_assessment.py``
"""

from __future__ import annotations

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.reasoning.decision import DecisionReport

# (title, intent, scenario, note) — scenario uses the normalized marker vocabulary;
# raw values that v0 cannot type are preserved under ``measurements``.
CASES = [
    (
        "Proliferating but doubling time worsening",
        "immortalization_assessment",
        {
            "species": "bovine",
            "cell_type": "fibroblast",
            "PDL_trend": "increasing",
            "DT_trend": "worsening",
            "DT_series_hours": {"P25": 42, "P30": 80, "P35": 100},
        },
        "v0 gap: raw DT hours (42->80->100) can only enter as the label 'worsening'.",
    ),
    (
        "Plateau then transient recovery",
        "immortalization_assessment",
        {
            "species": "bovine",
            "cell_type": "fibroblast",
            "PDL_trend": "increasing",  # snapshot taken during the recovery phase
            "DT_trend": "stable",
            "PDL_history": ["increasing", "plateau", "increasing"],
        },
        "v0 gap: single-snapshot only; the plateau->recovery trajectory is not modelled, "
        "so 'transient recovery' cannot be distinguished from steady growth.",
    ),
    (
        "Proliferation retained but adipogenic differentiation lost",
        "immortalization_vs_functionality",
        {
            "species": "bovine",
            "cell_type": "preadipocyte",
            "PDL_trend": "increasing",
            "DT_trend": "stable",
            "gammaH2AX": "low",
            "adipogenic_retention": "lost",
            "PPARG": "down",
            "CEBPA": "down",
            "FABP4": "down",
            "OilRedO": "weak",
        },
        "Immortalization axis is favourable, but utility for cultured meat is not.",
    ),
]


def _print_report(report: DecisionReport) -> None:
    flags = ", ".join(f.value for f in report.flags) or "-"
    print(f"  status : {report.candidate_status}   flags: {flags}")
    print(f"  why    : {report.conclusion}")

    def _lines(label: str, items: list[str]) -> None:
        if items:
            print(f"  {label}:")
            for item in items:
                print(f"    - {item}")

    _lines("supporting", [c.statement for c in report.supporting_evidence])
    _lines("contradicting", [c.statement for c in report.contradicting_evidence])
    _lines("missing axes", report.missing_axes)
    _lines("conflict", report.conflict_explanation)
    _lines("overinterpretation risk", report.overinterpretation_risk)
    _lines("validate (axes)", report.recommended_validation)
    _lines("next experiment", report.next_experiment)


def main() -> None:
    store = InMemoryKnowledgeStore()
    load_into(ImmortalizationSeedSource(), store)
    agent = ImmortalizationAssessmentAgent(store)

    for title, intent, scenario, note in CASES:
        print("=" * 78)
        print(title)
        print(f"note: {note}")
        report = agent.assess(input_from_scenario(intent, scenario))
        _print_report(report)
        print()


if __name__ == "__main__":
    main()
