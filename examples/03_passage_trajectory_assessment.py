"""Passage-aware trajectory assessment (PR7).

Runs the same tricky cases as ``02_immortalization_assessment.py``, but now feeds
the *raw passage series* those cases only hinted at. The platform derives the
trend from the data instead of trusting a hand-written snapshot label, and reports
a deterministic trajectory alongside (never as) the candidate status:

1. rising doublings with a worsening doubling time  -> ``progressive_slowdown``
2. a plateau followed by a single recovery point     -> ``transient_recovery``
   (durability not established — not the same as steady growth)
3. a snapshot ``DT_trend=stable`` that the raw series contradicts -> the series
   wins, and the disagreement is surfaced as an ``input_conflict``.

Contrast with example 02: there, case 1's ``DT_series 42->80->100`` could only
enter as the label "worsening" and case 2's plateau->recovery collapsed to one
label. Here the time axis is structured and consumed.

Run: ``python examples/03_passage_trajectory_assessment.py``
"""

from __future__ import annotations

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.reasoning.decision import DecisionReport

# (title, intent, scenario, note). ``observations`` is the raw per-passage series;
# snapshot markers, where present, are the v0 fallback the series now overrides.
CASES = [
    (
        "Rising doublings, worsening doubling time (raw series)",
        "immortalization_assessment",
        {
            "species": "bovine",
            "cell_type": "preadipocyte",
            "observations": [
                {"passage": 25, "culture_day": 110, "cumulative_PDL": 22.0, "DT_hours": 42},
                {"passage": 30, "culture_day": 145, "cumulative_PDL": 25.5, "DT_hours": 80},
                {"passage": 35, "culture_day": 180, "cumulative_PDL": 27.0, "DT_hours": 100},
            ],
        },
        "DT 42->80->100 is now derived from the data (fold ~2.38), not a label.",
    ),
    (
        "Plateau then a single recovery point",
        "immortalization_assessment",
        {
            "species": "bovine",
            "cell_type": "fibroblast",
            "observations": [
                {"passage": 20, "cumulative_PDL": 18.0, "DT_hours": 34},
                {"passage": 25, "cumulative_PDL": 22.0, "DT_hours": 36},
                {"passage": 30, "cumulative_PDL": 22.4, "DT_hours": 70},
                {"passage": 35, "cumulative_PDL": 25.0, "DT_hours": 40},
            ],
        },
        "transient_recovery: recovery observed but durability not yet established.",
    ),
    (
        "Snapshot says stable, the raw series says worsening",
        "immortalization_assessment",
        {
            "species": "bovine",
            "cell_type": "preadipocyte",
            "DT_trend": "stable",  # user-provided snapshot
            "PDL_trend": "increasing",
            "observations": [
                {"passage": 25, "cumulative_PDL": 22.0, "DT_hours": 42},
                {"passage": 30, "cumulative_PDL": 25.5, "DT_hours": 80},
                {"passage": 35, "cumulative_PDL": 27.0, "DT_hours": 100},
            ],
        },
        "The series-derived trend is used and the conflict is reported, not hidden.",
    ),
]


def _print_report(report: DecisionReport) -> None:
    flags = ", ".join(f.value for f in report.flags) or "-"
    print(f"  status     : {report.candidate_status}   flags: {flags}")
    if report.trajectory is not None:
        t = report.trajectory
        print(
            f"  trajectory : {t['state']}  "
            f"(PDL {t['derived_PDL_trend']}, DT {t['derived_DT_trend']}, "
            f"DT_fold {t['DT_fold_change']})"
        )
    if report.derived_input:
        print(f"  derived    : {report.derived_input}")

    def _lines(label: str, items: list[str]) -> None:
        if items:
            print(f"  {label}:")
            for item in items:
                print(f"    - {item}")

    _lines("input conflicts", report.input_conflicts)
    _lines("uncertainty", report.uncertainty)
    _lines("contradicting", [c.statement for c in report.contradicting_evidence])
    _lines("next experiment", report.next_experiment)


def main() -> None:
    store = InMemoryKnowledgeStore()
    load_into(ImmortalizationSeedSource(), store)
    agent = ImmortalizationAssessmentAgent(store=store)

    for title, intent, scenario, note in CASES:
        print("=" * 78)
        print(title)
        print(f"note: {note}")
        report = agent.assess(input_from_scenario(intent, scenario))
        _print_report(report)
        print()


if __name__ == "__main__":
    main()
