"""CI wrapper for the third vertical's scorecard.

The point of a third scorecard is not more coverage of genome editing. It is that the
benchmark *shape* — product path, hard contracts, safety phrases scored over assertion fields
only — transferred to a domain whose rules, vocabulary and failure modes share nothing with the
two it was designed against.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from eval_genome_editing_v0 import evaluate, load_spec, run_scenario

from virtualcell.platform.packs.genome_editing import GenomeEditingDomainPack

_PASSED, _TOTAL, _ROWS = evaluate()
_BY_ID = {row["id"]: row for row in _ROWS}


def test_all_ten_questions_are_answered() -> None:
    assert _TOTAL == 10
    assert set(_BY_ID) == {f"GE-Q{n}" for n in range(1, 11)}


@pytest.mark.parametrize("qid", sorted(_BY_ID))
def test_every_question_passes(qid: str) -> None:
    row = _BY_ID[qid]
    assert row["ok"], f"{qid} ({row['title']}): {row['failures']}"


def test_the_scorecard_is_perfect() -> None:
    assert _PASSED == _TOTAL == 10


def test_status_stays_inside_the_declared_vocabulary() -> None:
    from virtualcell.agents.genome_editing.models import EditStatus

    allowed = {None, *(s.value for s in EditStatus)}
    assert all(row["status"] in allowed for row in _ROWS)


def test_a_band_never_reaches_a_verdict() -> None:
    """GE-Q2 is the reason this vertical was chosen: the answer turns on the instrument."""
    row = _BY_ID["GE-Q2"]
    assert row["status"] == "insufficient_evidence"
    assert "weak_assay" in row["flags"]


def test_every_positive_call_reports_what_it_did_not_verify() -> None:
    for row in _ROWS:
        if row["status"] in ("edited_clonal", "edited_mosaic"):
            spec = next(q for q in load_spec()["questions"] if q["id"] == row["id"])
            answered = spec["experiment"].get("off_target_screened") == "genome_wide"
            assert answered or "off_target_unassessed" in row["flags"], row["id"]


def test_the_scorecard_runs_the_product_path(monkeypatch) -> None:
    seen: list[str] = []
    original = GenomeEditingDomainPack.execute

    def spy(self, query, store):
        seen.append(query.task)
        return original(self, query, store)

    monkeypatch.setattr(GenomeEditingDomainPack, "execute", spy)
    passed, total, _ = evaluate()

    assert len(seen) == 10 == total == passed
    assert {"assess_state", "explain_mechanism"} <= set(seen)


def test_the_harness_does_not_dispatch_builders_directly() -> None:
    import eval_genome_editing_v0 as harness

    source = Path(harness.__file__).read_text(encoding="utf-8")
    for forbidden in ("build_mechanism_report", "from virtualcell.agents.genome_editing import"):
        assert forbidden not in source, f"benchmark bypasses the pack via {forbidden}"


def test_repeated_evaluation_is_identical() -> None:
    first = {r["id"]: (r["ok"], r["status"], tuple(r["flags"])) for r in evaluate()[2]}
    second = {r["id"]: (r["ok"], r["status"], tuple(r["flags"])) for r in evaluate()[2]}
    assert first == second


def test_the_scenarios_reach_this_domain() -> None:
    assert run_scenario(load_spec()["questions"][0]).domain == "genome_editing"
