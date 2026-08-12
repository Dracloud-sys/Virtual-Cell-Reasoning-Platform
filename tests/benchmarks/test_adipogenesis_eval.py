"""Benchmark-first regression for the second vertical: pin the adipogenesis scorecard.

Same contract as `test_immortalization_eval.py`, one domain over. The ten questions are
answered through the **product path** (`AdipogenesisDomainPack.execute`) and must clear the
rubric; the domain's guardrails — no maturity claim, no verdict from silence, no negative call
on a dying culture — are pinned here so a later change cannot quietly trade them away.

The point of a second scorecard is not more coverage of adipogenesis. It is evidence that the
benchmark *shape* transfers to a domain whose rules are entirely different.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from eval_adipogenesis_v0 import MAX_POINTS, PASS_THRESHOLD, evaluate, load_spec, run_scenario

from virtualcell.agents.adipogenesis import DifferentiationStatus
from virtualcell.platform.packs.adipogenesis import AdipogenesisDomainPack

_PASSED, _TOTAL, _ROWS = evaluate()
_BY_ID = {row["id"]: row for row in _ROWS}
_SPEC = {q["id"]: q for q in load_spec()["questions"]}
_MECHANISM = "ADI-Q10"


def test_all_ten_questions_are_answered() -> None:
    assert _TOTAL == 10
    assert len(_BY_ID) == 10


@pytest.mark.parametrize("qid", sorted(_BY_ID))
def test_every_question_passes_the_rubric(qid: str) -> None:
    row = _BY_ID[qid]
    assert row["ok"], (
        f"{qid} scored {row['score']}/{MAX_POINTS} (threshold {PASS_THRESHOLD}): {row['failures']}"
    )


def test_scorecard_is_perfect() -> None:
    # Stated as one number so a regression shows up in a single line of CI output.
    assert _PASSED == _TOTAL == 10


def test_mechanism_question_carries_no_status_but_a_chain() -> None:
    row = _BY_ID[_MECHANISM]
    assert row["status"] is None
    assert run_scenario(_SPEC[_MECHANISM]).mechanistic_links


# --- the domain guardrails ---------------------------------------------------


def test_no_question_claims_maturity() -> None:
    """The vertical's headline safety boundary, checked across all ten answers at once.

    ``differentiating`` never becomes ``mature``, and every positive call says so out loud.
    """
    positive = {
        DifferentiationStatus.DIFFERENTIATING.value,
        DifferentiationStatus.PARTIALLY_DIFFERENTIATED.value,
    }
    for row in _ROWS:
        if row["status"] in positive:
            assert "maturation_unverified" in row["flags"], row["id"]


def test_a_marker_panel_alone_never_reaches_a_positive_call() -> None:
    # ADI-Q2 is the whole reason the vertical exists: five markers high, no lipid, no verdict.
    row = _BY_ID["ADI-Q2"]
    assert row["status"] == DifferentiationStatus.INSUFFICIENT_EVIDENCE.value
    assert "function_unmeasured" in row["flags"]


def test_a_dying_culture_does_not_produce_a_negative_call() -> None:
    # Q3 and Q9 differ only in viability, and that difference must change the verdict.
    healthy, dying = _BY_ID["ADI-Q3"], _BY_ID["ADI-Q9"]
    assert healthy["status"] == DifferentiationStatus.NOT_DIFFERENTIATING.value
    assert dying["status"] == DifferentiationStatus.INSUFFICIENT_EVIDENCE.value
    assert "viability_compromised" in dying["flags"]


def test_lipid_without_the_program_is_a_conflict_not_a_weak_positive() -> None:
    row = _BY_ID["ADI-Q6"]
    assert row["status"] == DifferentiationStatus.INSUFFICIENT_EVIDENCE.value
    assert "conflicting_evidence" in row["flags"]


def test_status_stays_inside_the_declared_vocabulary() -> None:
    allowed = {None, *(s.value for s in DifferentiationStatus)}
    assert all(row["status"] in allowed for row in _ROWS)


# --- the benchmark must exercise the product path (PR10b) --------------------


def test_every_question_is_evaluated_through_the_pack(monkeypatch) -> None:
    """All ten questions must reach ``AdipogenesisDomainPack.execute``.

    Counts real calls rather than inspecting imports, so the harness cannot regress to
    calling ``assess`` (or a report builder) directly for some intents.
    """
    seen: list[str] = []
    original = AdipogenesisDomainPack.execute

    def spy(self, query, store):
        seen.append(query.task)
        return original(self, query, store)

    monkeypatch.setattr(AdipogenesisDomainPack, "execute", spy)
    passed, total, _ = evaluate()

    assert len(seen) == 10 == total == passed
    assert {"assess_state", "explain_mechanism"} <= set(seen)


def test_benchmark_does_not_dispatch_builders_directly() -> None:
    import eval_adipogenesis_v0 as harness

    source = Path(harness.__file__).read_text(encoding="utf-8")
    for forbidden in ("build_mechanism_report", "from virtualcell.agents.adipogenesis import"):
        assert forbidden not in source, f"benchmark bypasses the pack via {forbidden}"


def test_repeated_evaluation_is_identical() -> None:
    first = {r["id"]: (r["score"], r["status"], r["ok"]) for r in evaluate()[2]}
    second = {r["id"]: (r["score"], r["status"], r["ok"]) for r in evaluate()[2]}
    assert first == second
