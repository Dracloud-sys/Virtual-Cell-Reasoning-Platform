"""External evaluation: published immortalization cases this project did not author.

The four in-house scorecards read 10/10 · 10/10 · 6/6 · 10/10 and establish internal
consistency, because their questions, rubrics and seed graph all came from here. This one's
ground truth is what real cells did in real laboratories, reported in peer-reviewed papers
with DOIs, and it can fail.

**Product path.** Every arm runs through the same public entry point the API and CLI use —
:meth:`ImmortalizationAssessmentAgent.assess` over the normal deterministic seed store. No
benchmark-only code path exists, so a score is evidence about the shipped product.

**Two numbers, because one would hide the other.** *Fidelity* asks whether the platform gets
representable arms right. *Coverage* asks how many of the papers' reported facts the input
vocabulary could carry at all. A narrow platform scores well on fidelity alone by only ever
being asked what it can already say — which is the exact failure an external set exists to
detect — so the summary is never a single number.

The admissibility rules, the held-out boundary and the scoring were fixed in
``external_immortalization_v1.md`` before any score existed. **A failing arm is a finding,
not a bug to paper over**; that document names the repairs that are not allowed.

Run ``python -m tests.benchmarks.eval_external_immortalization_v1`` for the scorecard.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.agent import ImmortalizationAssessmentAgent
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.reasoning.decision import DecisionReport

_SPEC_PATH = Path(__file__).parent / "external_immortalization_v1.yaml"

#: Scored per arm, 0 or 1 each. ``species_caveat`` applies only to arms whose species
#: differs from the vertical's intended one; scoring it on a bovine arm would be free credit.
AXES = ("status_match", "overcall_controlled", "species_caveat")


class ArmScore(BaseModel):
    arm_id: str
    doi: str
    species: str
    expected_status: str
    actual_status: str | None
    axes: dict[str, int | None]  # None = not applicable to this arm
    dropped_fields: list[str]

    @property
    def applicable(self) -> list[int]:
        return [value for value in self.axes.values() if value is not None]

    @property
    def passed(self) -> bool:
        return all(value == 1 for value in self.applicable)


def _store() -> InMemoryKnowledgeStore:
    """The normal deterministic seed store, exactly as the product builds it."""
    store = InMemoryKnowledgeStore()
    source = ImmortalizationSeedSource()
    for entity in source.entities():
        store.upsert(entity)
    for interaction in source.interactions():
        store.add_interaction(interaction)
    return store


def _text(report: DecisionReport) -> str:
    """Every free-text channel a caveat could honestly appear in, lowercased."""
    parts = [
        report.conclusion,
        *report.limitations,
        *report.overinterpretation_risk,
        *report.uncertainty,
        *report.conflict_explanation,
        *(claim.statement for claim in report.supporting_evidence),
        *(claim.statement for claim in report.contradicting_evidence),
    ]
    return " ".join(parts).lower()


def _overcall_controlled(report: DecisionReport, arm: dict) -> int:
    """The report must not present a possibility as a verdict.

    Two things are checked, and both are things the papers make checkable. The status may
    never be an assertion of confirmed immortality — the vocabulary has no such value, so
    this is really a guard against the conclusion prose saying it anyway. And wherever the
    paper left a safety axis unmeasured, *something* must say so: a report that reads the
    same whether or not a karyotype exists is the overinterpretation this vertical names as
    its own main risk.
    """
    text = _text(report)
    if "confirmed immortal" in text or "is immortal" in text:
        return 0
    unmeasured_safety = any(
        entry.get("field") in {"genomic_stability", "adipogenic_retention"}
        for entry in arm.get("unrepresentable", [])
    )
    if unmeasured_safety and not (report.overinterpretation_risk or report.limitations):
        return 0
    return 1


def _species_caveat(report: DecisionReport, arm: dict, intended: str) -> int | None:
    """Does the report anywhere note that this is not the vertical's species?

    Returns ``None`` for arms that match the intended species, so they neither gain nor lose
    by an axis that does not apply to them.

    This axis is expected to score 0 on every arm it applies to. ``packs/immortalization.py``
    declares ``species`` as ``AxisKind.CONTEXT`` — "Recorded for provenance; no deterministic
    builder reads it" — so the platform cannot emit such a caveat. It stays scored rather
    than quietly dropped: the benchmark philosophy in ``immortalization_v0.md`` §0 lists
    species appropriateness as a criterion, 9 of the 10 in-house questions are bovine and the
    tenth names no species, so no in-house question could ever have measured it. A rule
    rewritten after seeing that result would not be a rule.
    """
    species = str(arm["reported"].get("species", "")).lower()
    if not species or species == intended:
        return None
    text = _text(report)
    return 1 if species in text or "species" in text else 0


def score_arm(arm: dict, intended_species: str, doi: str) -> ArmScore:
    agent = ImmortalizationAssessmentAgent(store=_store())
    report = agent.assess(input_from_scenario(arm["intent"], arm["reported"]))
    actual = report.candidate_status.value if report.candidate_status is not None else None

    return ArmScore(
        arm_id=arm["id"],
        doi=doi,
        species=str(arm["reported"].get("species", "unspecified")),
        expected_status=arm["expected_status"],
        actual_status=actual,
        axes={
            "status_match": int(actual == arm["expected_status"]),
            "overcall_controlled": _overcall_controlled(report, arm),
            "species_caveat": _species_caveat(report, arm, intended_species),
        },
        dropped_fields=[str(entry.get("field")) for entry in arm.get("unrepresentable", []) or []],
    )


def run() -> tuple[list[ArmScore], dict]:
    spec = yaml.safe_load(_SPEC_PATH.read_text(encoding="utf-8"))
    intended = str(spec["intended_species"]).lower()
    papers = spec["papers"]
    scores = [score_arm(arm, intended, str(papers[arm["paper"]]["doi"])) for arm in spec["arms"]]
    return scores, spec


def _table(scores: list[ArmScore]) -> str:
    header = f"{'arm':<8} {'species':<8} {'expected':<28} {'actual':<28} {'axes':<14} dropped"
    rows = [header, "-" * len(header)]
    for score in scores:
        axes = "".join("·" if score.axes[name] is None else str(score.axes[name]) for name in AXES)
        rows.append(
            f"{score.arm_id:<8} {score.species:<8} {score.expected_status:<28} "
            f"{str(score.actual_status):<28} {axes:<14} {len(score.dropped_fields)}"
        )
    return "\n".join(rows)


def main() -> int:
    scores, spec = run()

    print("External immortalization evaluation v1 — published cases, not authored here")
    print(
        f"Ground truth: {len(spec['papers'])} papers, {len(scores)} arms. "
        "Retrieved via PubMed; DOIs in the spec.\n"
    )
    print(_table(scores))
    print(f"\naxes, in order: {', '.join(AXES)}   (· = not applicable to this arm)")

    # Fidelity: of the axes that apply, how many hold.
    # Coverage: how much of what the papers reported the vocabulary could carry.
    # One line, carrying both, because a caller that quotes only the first would quote the
    # flattering one — and the summary is never a single number.
    applicable = [value for score in scores for value in score.applicable]
    dropped = sum(len(score.dropped_fields) for score in scores)
    arms_with_drops = sum(1 for score in scores if score.dropped_fields)
    print(
        f"\nFidelity {sum(applicable)}/{len(applicable)} axis checks, "
        f"{sum(1 for s in scores if s.passed)}/{len(scores)} arms clean"
        f" | Coverage {dropped} reported fact(s) dropped across "
        f"{arms_with_drops}/{len(scores)} arms"
    )

    by_axis = {name: [s.axes[name] for s in scores if s.axes[name] is not None] for name in AXES}
    print("\nPer axis:")
    for name, values in by_axis.items():
        print(f"  {name:<22} {sum(values)}/{len(values)}")

    print(
        "\nThis is an external evaluation, not an in-house scorecard, and it is not a gate. "
        "\nA failing arm is a finding; external_immortalization_v1.md names the repairs that "
        "are not\nallowed, and why widening the graph to pass one would destroy the result."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
