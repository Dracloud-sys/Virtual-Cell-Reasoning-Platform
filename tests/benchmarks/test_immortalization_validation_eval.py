"""CI wrapper for the validation-loop scorecard.

Kept separate from `test_immortalization_eval.py` because the two answer different questions.
That one asks whether the vertical judges a culture correctly; this one asks whether it can
read back the measurements it asked for. A regression in either should name itself.
"""

from __future__ import annotations

import pytest
from eval_immortalization_validation_v0 import evaluate, load_spec, run_scenario

from virtualcell.platform.packs.immortalization import ImmortalizationDomainPack

_PASSED, _TOTAL, _ROWS = evaluate()
_BY_ID = {row["id"]: row for row in _ROWS}


def test_all_six_scenarios_are_covered() -> None:
    assert _TOTAL == 6
    assert set(_BY_ID) == {f"IMM-VAL-{n}" for n in range(1, 7)}


@pytest.mark.parametrize("qid", sorted(_BY_ID))
def test_every_scenario_closes_its_loop(qid: str) -> None:
    row = _BY_ID[qid]
    assert row["ok"], f"{qid} ({row['title']}): {row['failures']}"


def test_no_validation_axis_moved_the_status() -> None:
    """Stated once over all six, because it is one claim and not six: the axes report
    beside the verdict, never through it."""
    assert {row["status"] for row in _ROWS} == {"possible_candidate"}


def test_the_scorecard_runs_the_product_path(monkeypatch) -> None:
    seen: list[str] = []
    original = ImmortalizationDomainPack.execute

    def spy(self, query, store):
        seen.append(query.task)
        return original(self, query, store)

    monkeypatch.setattr(ImmortalizationDomainPack, "execute", spy)
    passed, total, _ = evaluate()

    assert len(seen) == 6 == total == passed
    assert set(seen) == {"assess_state"}


def test_every_scenario_varies_exactly_one_validation_axis() -> None:
    """The benchmark's own precondition: if two things changed, nothing is attributable."""
    spec = load_spec()
    axes = {"genomic_stability", "adipogenic_retention"}
    for question in spec["questions"]:
        varied = axes & set(question["experiment"])
        assert len(varied) == 1, question["id"]


def test_repeated_evaluation_is_identical() -> None:
    first = {r["id"]: (r["ok"], r["status"], tuple(r["flags"])) for r in evaluate()[2]}
    second = {r["id"]: (r["ok"], r["status"], tuple(r["flags"])) for r in evaluate()[2]}
    assert first == second


def test_the_spec_and_the_product_agree_on_the_pack() -> None:
    # A scenario must reach this domain's pack, not be silently routed elsewhere.
    response = run_scenario(load_spec()["questions"][0])
    assert response.domain == "immortalization"
