"""Setting a revised draft beside the draft it revises (`revision` on check_research_draft).

The questions are in `docs/research_sessions/eval1_persistence/evidence_gap_v1/
benchmark_questions.md` (R1-R10), written before the code. Every test here goes through the
product path, `build_server()` and the MCP tools.

The small drafts below are synthetic on purpose: they test the contract (which change is
reported, which decision conflicts), not biology, and no result here is a research finding.
The last tests replay the real case recorded in that directory.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

mcp_server = pytest.importorskip(
    "virtualcell.mcp.server",
    reason="the MCP adapter needs the optional 'mcp' extra",
)
sdk_errors = pytest.importorskip("mcp.server.mcpserver.exceptions")

from virtualcell.mcp.payloads import ToolRefusal  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CASE_ROOT = REPO / "docs" / "research_sessions" / "eval1_persistence"
CASE = CASE_ROOT / "evidence_gap_v1"
PRIOR = CASE_ROOT / "records" / "condition_B_payload_2.json"


def _span(eid_hint: str, pmcid: str, text: str) -> dict[str, Any]:
    return {
        "id": eid_hint,
        "kind": "retrieved_source",
        "statement": f"Synthetic test span from {pmcid}",
        "locator": {"article": {"pmcid": pmcid}, "source_kind": "abstract", "source_text": text},
    }


def _draft() -> dict[str, Any]:
    """A two-hypothesis draft on a subject no domain covers (contract test only)."""
    return {
        "question": "Why does a biofilm keep growing after the nutrient pulse ends?",
        "assumptions": ["Synthetic: the pulse is the only nutrient source."],
        "open_conditions": ["Strain not fixed."],
        "hypotheses": [
            {
                "id": "HA",
                "statement": "Stored nutrient is used.",
                "support": "unverified_candidate",
            },
            {
                "id": "HB",
                "statement": "Cells switched to a persistent growth state.",
                "support": "unverified_candidate",
                "sub_question_ids": [],
            },
        ],
        "experiments": [
            {
                "id": "X1",
                "design": "Measure stored nutrient after the pulse.",
                "controls": ["no pulse"],
                "measurements": ["stored_nutrient"],
                "discriminates": ["HA", "HB"],
                "predictions": [
                    {
                        "hypothesis_id": "HA",
                        "readout": "stored_nutrient",
                        "expected": "increase",
                        "versus": "no pulse",
                        "basis": "assumption",
                        "assumptions": ["Storage is measurable."],
                    },
                    {
                        "hypothesis_id": "HB",
                        "readout": "stored_nutrient",
                        "expected": "no_change",
                        "versus": "no pulse",
                        "basis": "assumption",
                        "assumptions": ["Storage is measurable."],
                    },
                ],
            },
            {
                "id": "X2",
                "design": "Unrelated growth curve.",
                "controls": ["no pulse"],
                "measurements": ["growth"],
                "discriminates": ["HA", "HB"],
            },
        ],
        "evidence": [],
    }


def _revised(draft: dict[str, Any]) -> dict[str, Any]:
    """The same draft after reading two spans of one paper. Only HA and X1 change."""
    new = copy.deepcopy(draft)
    new["evidence"] = [
        _span("s1", "PMC0000001", "Synthetic span one about storage."),
        _span("s2", "PMC0000001", "Synthetic span two about storage, same paper."),
    ]
    new["hypotheses"][0]["supporting_evidence_ids"] = ["s1"]
    new["hypotheses"][0]["support"] = "evidence_linked"
    new["evidence_links"] = [
        {"evidence_id": "s1", "target_id": "HA", "role": "supports", "reading": "synthetic"},
        {"evidence_id": "s2", "target_id": "HA", "role": "method", "reading": "synthetic"},
    ]
    new["experiments"][0]["predictions"][0]["evidence_ids"] = ["s1"]
    return new


def _check(server, draft, prior=None, decisions=None, view="compact") -> dict[str, Any]:
    args = {**draft, "view": view}
    if prior is not None:
        args["prior_draft"] = prior
    if decisions is not None:
        args["revision_decisions"] = decisions
    result = asyncio.run(server.call_tool("check_research_draft", args))
    assert not result.is_error, result.content
    return result.structured_content


def _codes(revision: dict[str, Any]) -> list[str]:
    return [f["code"] for f in revision["findings"]]


@pytest.fixture(scope="module")
def server():
    return mcp_server.build_server()


def test_no_prior_means_no_revision(server):
    assert _check(server, _draft())["revision"] is None


def test_decisions_without_a_prior_are_refused(server):
    with pytest.raises(sdk_errors.ToolError) as caught:
        _check(server, _draft(), decisions=[{"target_id": "HA", "decision": "keep", "reason": "x"}])
    assert ToolRefusal.parse(str(caught.value)).error == "malformed_draft"


def test_r1_new_evidence_and_what_it_reaches(server):
    rev = _check(server, _revised(_draft()), prior=_draft())["revision"]
    assert rev["evidence"]["added"] == ["s1", "s2"]
    use = {u["evidence_id"]: u for u in rev["new_evidence_use"]}
    assert use["s1"]["supporting_for"] == ["HA"]
    assert use["s1"]["predictions"] == ["X1|HA|stored_nutrient||no pulse"]
    impact = rev["resting_on_new_evidence"]
    assert impact["affected_hypotheses"] == ["HA"]
    assert impact["affected_experiments"] == ["X1"]


def test_r1_an_edited_span_is_reported_as_edited(server):
    prior = _revised(_draft())
    revised = copy.deepcopy(prior)
    revised["evidence"][0]["locator"]["source_text"] = "Synthetic span one, edited."
    rev = _check(server, revised, prior=prior)["revision"]
    assert rev["evidence"]["edited"] == ["s1"]
    assert rev["evidence"]["added"] == []


def test_r2_roles_are_the_hosts_and_origin_is_unchanged(server):
    out = _check(server, _revised(_draft()), prior=_draft())
    use = {u["evidence_id"]: u for u in out["revision"]["new_evidence_use"]}
    assert use["s2"]["roles"] == ["HA:method"]
    assert {u["interpretation_by"] for u in use.values()} == {"host"}
    assert {o["origin"] for o in out["evidence_origins"]} == {"host_supplied"}
    assert out["scientific_validity_checked"] is False


def test_r3_a_method_span_listed_as_support_is_a_finding(server):
    revised = _revised(_draft())
    revised["hypotheses"][0]["supporting_evidence_ids"] = ["s1", "s2"]
    rev = _check(server, revised, prior=_draft())["revision"]
    promoted = [f for f in rev["findings"] if f["code"] == "non_supporting_role_listed_as_support"]
    assert [f["value"] for f in promoted] == ["s2"]


def test_r3_a_contradicting_span_is_not_counted_as_support(server):
    revised = _revised(_draft())
    revised["evidence_links"][0]["role"] = "contradicts"
    revised["hypotheses"][0]["supporting_evidence_ids"] = []
    revised["hypotheses"][0]["contradicting_evidence_ids"] = ["s1"]
    revised["hypotheses"][0]["support"] = "unverified_candidate"
    rev = _check(server, revised, prior=_draft())["revision"]
    use = {u["evidence_id"]: u for u in rev["new_evidence_use"]}
    assert use["s1"]["supporting_for"] == []
    assert use["s1"]["contradicting_for"] == ["HA"]


def test_r4_two_spans_of_one_paper_are_one_study(server):
    rev = _check(server, _revised(_draft()), prior=_draft())["revision"]
    assert rev["evidence"]["new_spans"] == 2
    assert rev["evidence"]["new_studies"] == 1


def test_r5_dropped_limits_are_removals(server):
    revised = _revised(_draft())
    revised["assumptions"] = []
    revised["experiments"][0]["predictions"][0]["assumptions"] = []
    rev = _check(server, revised, prior=_draft())["revision"]
    removed = [c["id"] for c in rev["changes"] if c["kind"] == "statement"]
    assert removed == ["assumptions: Synthetic: the pulse is the only nutrient source."]
    dropped = [f for f in rev["findings"] if f["code"] == "prediction_assumption_removed"]
    assert [f["value"] for f in dropped] == ["Storage is measurable."]


def test_r6_unrelated_parts_are_unchanged_and_untraced_changes_are_named(server):
    rev = _check(server, _revised(_draft()), prior=_draft())["revision"]
    assert rev["unchanged_experiments"] == ["X2"]
    assert rev["untraced_changes"] == []

    revised = _revised(_draft())
    revised["experiments"][1]["design"] = "Unrelated growth curve, now hourly."
    rev = _check(server, revised, prior=_draft())["revision"]
    assert rev["untraced_changes"] == ["experiment:X2"]
    assert "X2" in rev["undecided_changes"]


def test_r7_the_prior_is_named_by_hash_and_not_rewritten(server):
    prior = _draft()
    before = json.dumps(prior, sort_keys=True)
    rev = _check(server, _revised(_draft()), prior=prior)["revision"]
    same = _check(server, _draft(), prior=_draft())["revision"]
    assert json.dumps(prior, sort_keys=True) == before
    assert rev["prior_plan_sha256"] == same["prior_plan_sha256"] == same["revised_plan_sha256"]
    assert rev["revised_plan_sha256"] != rev["prior_plan_sha256"]
    assert same["changes"] == []


def test_r8_decisions_are_checked_against_what_changed(server):
    decisions = [
        {"target_id": "HA", "decision": "keep", "reason": "more grounds", "evidence_ids": ["s1"]},
        {"target_id": "X1", "decision": "keep", "reason": "x", "evidence_ids": ["s1"]},
        {"target_id": "X2", "decision": "revise", "reason": "x"},
        {"target_id": "HB", "decision": "unchanged_no_new_evidence", "reason": "x"},
        {"target_id": "HZ", "decision": "hold", "reason": "x", "evidence_ids": ["nope"]},
    ]
    revised = _revised(_draft())
    revised["experiments"][0]["controls"].append("vehicle")
    rev = _check(server, revised, prior=_draft(), decisions=decisions)["revision"]
    found = {(f["code"], f["where"]) for f in rev["findings"]}
    # HA: only its evidence grew, which a `keep` may carry; its support label changed too.
    assert ("decision_says_unchanged_but_changed", "decision:HA") in found
    assert ("decision_says_unchanged_but_changed", "decision:X1") in found
    assert ("revise_without_change", "decision:X2") in found
    assert ("decision_target_unknown", "decision:HZ") in found
    assert ("decision_evidence_unknown", "decision:HZ") in found
    assert not any(w == "decision:HB" for _, w in found)
    assert {d["stated_by"] for d in rev["decisions"]} == {"host"}


def test_r8_keep_may_carry_new_grounds_only(server):
    revised = _revised(_draft())
    revised["hypotheses"][0]["support"] = "unverified_candidate"
    revised["hypotheses"][0]["supporting_evidence_ids"] = ["s1"]
    decisions = [
        {"target_id": "HA", "decision": "keep", "reason": "grounds", "evidence_ids": ["s1"]},
        {"target_id": "X1", "decision": "keep", "reason": "grounds", "evidence_ids": ["s1"]},
    ]
    rev = _check(server, revised, prior=_draft(), decisions=decisions)["revision"]
    assert _codes(rev) == []


def test_r8_no_new_evidence_decision_cites_nothing(server):
    decisions = [
        {
            "target_id": "HB",
            "decision": "unchanged_no_new_evidence",
            "reason": "x",
            "evidence_ids": ["s1"],
        }
    ]
    rev = _check(server, _revised(_draft()), prior=_draft(), decisions=decisions)["revision"]
    assert "no_new_evidence_decision_cites_evidence" in _codes(rev)


def test_r9_a_moved_value_is_listed_and_nothing_moves_by_itself(server):
    revised = _revised(_draft())
    revised["experiments"][0]["predictions"][1]["expected"] = "decrease"
    rev = _check(server, revised, prior=_draft())["revision"]
    assert rev["value_changes"] == [
        {
            "prediction": "X1|HB|stored_nutrient||no pulse",
            "before": "no_change",
            "after": "decrease",
            "cites_new_evidence": [],
        }
    ]
    plain = _check(server, _revised(_draft()), prior=_draft())["revision"]
    assert plain["value_changes"] == []


def test_r10_the_compact_and_full_views_carry_the_same_revision(server):
    compact = _check(server, _revised(_draft()), prior=_draft())
    full = _check(server, _revised(_draft()), prior=_draft(), view="full")
    assert compact["revision"] == full["revision"]


def test_a_malformed_prior_is_refused(server):
    with pytest.raises(sdk_errors.ToolError) as caught:
        _check(server, _draft(), prior={"question": "q", "view": "full"})
    assert ToolRefusal.parse(str(caught.value)).error == "malformed_prior_draft"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_file_route_takes_the_prior_by_path_and_hash(tmp_path):
    root = tmp_path / "drafts"
    root.mkdir()
    (root / "v1.json").write_text(json.dumps(_draft()), encoding="utf-8")
    (root / "v2.json").write_text(json.dumps(_revised(_draft())), encoding="utf-8")
    server = mcp_server.build_server(draft_dir=root)
    args = {
        "path": "v2.json",
        "sha256": _sha(root / "v2.json"),
        "prior_path": "v1.json",
        "prior_sha256": _sha(root / "v1.json"),
    }
    out = asyncio.run(server.call_tool("check_research_draft_file", args)).structured_content
    assert out["prior_input_file"]["path"] == "v1.json"
    inline = _check(mcp_server.build_server(), _revised(_draft()), prior=_draft())
    assert out["revision"] == inline["revision"]

    with pytest.raises(sdk_errors.ToolError) as caught:
        asyncio.run(
            server.call_tool("check_research_draft_file", {**args, "prior_sha256": "0" * 64})
        )
    assert ToolRefusal.parse(str(caught.value)).error == "draft_file_hash_mismatch"
    with pytest.raises(sdk_errors.ToolError):
        asyncio.run(
            server.call_tool(
                "check_research_draft_file", {k: v for k, v in args.items() if k != "prior_sha256"}
            )
        )


# --- the recorded case ----------------------------------------------------------------- #


def test_the_case_prior_is_the_recorded_original():
    sums = (CASE_ROOT / "records" / "SHA256SUMS").read_text(encoding="utf-8")
    assert f"{_sha(PRIOR)}  condition_B_payload_2.json" in sums


def test_the_case_revision_replays(tmp_path):
    """The recorded revision is what this code computes from the recorded inputs."""
    root = tmp_path / "eval1"
    (root / "records").mkdir(parents=True)
    (root / "evidence_gap_v1").mkdir()
    shutil.copy(PRIOR, root / "records" / PRIOR.name)
    shutil.copy(CASE / "draft_revised.json", root / "evidence_gap_v1" / "draft_revised.json")
    server = mcp_server.build_server(draft_dir=root)
    revised = json.loads((CASE / "draft_revised.json").read_text(encoding="utf-8"))
    decisions = json.loads((CASE / "decisions.json").read_text(encoding="utf-8"))
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    out = _check(server, revised, prior=prior, decisions=decisions)
    recorded = json.loads((CASE / "revision_with_decisions.json").read_text(encoding="utf-8"))
    assert out["revision"] == recorded["revision"]
    rev = out["revision"]
    assert rev["unchanged_experiments"] == ["E2", "E3", "E4", "E5", "E6"]
    assert rev["value_changes"] == []
    assert rev["untraced_changes"] == [] and rev["undecided_changes"] == []
    assert rev["findings"] == []
    assert rev["evidence"]["new_studies"] == 3 and rev["evidence"]["new_spans"] == 10


def test_the_case_revised_draft_rebuilds_byte_for_byte(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_revised", CASE / "build_revised.py")
    module = importlib.util.module_from_spec(spec)
    # Importing it would otherwise leave a __pycache__ inside the case record.
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec.loader.exec_module(module)
    draft, decisions = module.build()
    text = json.dumps(draft, indent=1, ensure_ascii=False) + "\n"
    assert text == (CASE / "draft_revised.json").read_text(encoding="utf-8")
    assert json.dumps(decisions, indent=1, ensure_ascii=False) + "\n" == (
        CASE / "decisions.json"
    ).read_text(encoding="utf-8")


# --- conditions in the pair analysis ------------------------------------------------------ #
#
# Recorded first at 25c3af3 as a pinned finding: `plan._discriminate` kept one prediction per
# hypothesis and readout, so of two conditions only the last-listed was compared (the eval1 E1
# plan already had two conditions per readout). At 25c3af3 this draft returned no separated
# pair. The tests below are the behaviour required after the fix.


def _conditioned(*extra: dict[str, Any]) -> dict[str, Any]:
    draft = _draft()
    first, second = draft["experiments"][0]["predictions"]
    late = [{**first, "condition": "day 5"}, {**second, "condition": "day 5"}]
    draft["experiments"][0]["predictions"] = [*late, *extra]
    return draft


def _x1(server, draft) -> dict[str, Any]:
    return _check(server, draft, view="full")["plan_analysis"]["experiments"][0]


def test_every_condition_is_kept_and_compared_on_its_own(server):
    """Was the pinned defect: the 'day 1' pair used to hide the 'day 5' separation."""
    first, second = _draft()["experiments"][0]["predictions"]
    early = [
        {**first, "condition": "day 1", "expected": "decrease"},
        {**second, "condition": "day 1", "expected": "decrease"},
    ]
    x1 = _x1(server, _conditioned(*early))
    [pair] = x1["separated_pairs"]
    assert [(d["readout"], d["condition"]) for d in pair["readouts"]] == [
        ("stored_nutrient", "day 5")
    ]
    rows = {(r["condition"], tuple(sorted(r["by_expected"]))) for r in x1["outcome_table"]}
    assert rows == {("day 1", ("decrease",)), ("day 5", ("increase", "no_change"))}


def test_a_timepoint_written_in_the_condition_is_not_merged(server):
    first, second = _draft()["experiments"][0]["predictions"]
    x1 = _x1(
        server,
        _conditioned({**first, "condition": "day 1", "expected": "no_change"}),
    )
    # HA's day-1 value does not meet HB's day-5 value; HA's day-5 value does.
    [pair] = x1["separated_pairs"]
    assert {d["condition"] for d in pair["readouts"]} == {"day 5"}


def test_only_predictions_on_the_same_reference_are_compared(server):
    first, second = _draft()["experiments"][0]["predictions"]
    x1 = _x1(
        server,
        _conditioned(
            {**first, "condition": "day 5", "versus": "day 1", "expected": "decrease"},
            {**second, "condition": "day 5", "versus": "day 1", "expected": "decrease"},
        ),
    )
    [pair] = x1["separated_pairs"]
    assert [(d["versus"], d["expected"]) for d in pair["readouts"]] == [
        ("no pulse", {"HA": "increase", "HB": "no_change"})
    ]
    assert x1["readout_exclusions"] == []


def test_conditions_that_do_not_match_are_listed_with_their_reason(server):
    first, second = _draft()["experiments"][0]["predictions"]
    draft = _draft()
    draft["experiments"][0]["predictions"] = [
        {**first, "condition": "day 1"},
        {**second, "condition": "day 5"},
    ]
    x1 = _x1(server, draft)
    assert x1["separated_pairs"] == []
    assert x1["unseparated_pairs"] == [
        {"pair": ["HA", "HB"], "reason": "not_comparable_on_shared_readouts"}
    ]
    [excluded] = x1["readout_exclusions"]
    assert excluded["reason"] == "different_condition"


def test_reordering_the_predictions_changes_nothing(server):
    first, second = _draft()["experiments"][0]["predictions"]
    extra = [
        {**first, "condition": "day 1", "expected": "decrease"},
        {**second, "condition": "day 1", "expected": "no_change"},
    ]
    one = _conditioned(*extra)
    two = copy.deepcopy(one)
    two["experiments"][0]["predictions"].reverse()
    a, b = _x1(server, one), _x1(server, two)
    for key in ("separated_pairs", "unseparated_pairs", "readout_exclusions", "outcome_table"):
        assert a[key] == b[key], key


def test_conflicting_values_for_one_condition_are_reported_not_chosen(server):
    first, _ = _draft()["experiments"][0]["predictions"]
    for order in ("increase_last", "decrease_last"):
        clash = {**first, "condition": "day 5", "expected": "decrease"}
        draft = _conditioned(clash)
        if order == "decrease_last":
            preds = draft["experiments"][0]["predictions"]
            preds.insert(0, preds.pop())
        out = _check(server, draft, view="full")
        x1 = out["plan_analysis"]["experiments"][0]
        assert x1["separated_pairs"] == [], order
        codes = [f["code"] for f in out["findings"]]
        assert codes.count("conflicting_predictions") == 1, order


def test_a_single_condition_draft_is_compared_as_before(server):
    x1 = _x1(server, _draft())
    [pair] = x1["separated_pairs"]
    assert pair["readouts"][0]["expected"] == {"HA": "increase", "HB": "no_change"}
    assert pair["readouts"][0]["condition"] is None


# --- revision 2 of the case: readings narrowed, no new evidence -------------------------- #

R2 = CASE / "r2"


def test_revision_2_rebuilds_from_revision_1_byte_for_byte(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_r2", R2 / "build_r2.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec.loader.exec_module(module)
    draft, decisions = module.build()
    assert json.dumps(draft, indent=1, ensure_ascii=False) + "\n" == (
        R2 / "draft_revised_r2.json"
    ).read_text(encoding="utf-8")
    assert json.dumps(decisions, indent=1, ensure_ascii=False) + "\n" == (
        R2 / "decisions_r2.json"
    ).read_text(encoding="utf-8")


def test_revision_2_replays_and_moves_only_what_it_says(server):
    revised = json.loads((R2 / "draft_revised_r2.json").read_text(encoding="utf-8"))
    prior = json.loads((CASE / "draft_revised.json").read_text(encoding="utf-8"))
    decisions = json.loads((R2 / "decisions_r2.json").read_text(encoding="utf-8"))
    rev = _check(server, revised, prior=prior, decisions=decisions)["revision"]
    recorded = json.loads((R2 / "revision_r1_to_r2.json").read_text(encoding="utf-8"))
    assert rev == recorded["with_decisions"]["revision"]
    assert rev["value_changes"] == [
        {
            "prediction": (
                "E1|H2|pSmad2_nuclear|arm a (vehicle, cells), d5|arm a (vehicle, cells), d1"
            ),
            "before": "no_change",
            "after": "not_predicted",
            "cites_new_evidence": [],
        }
    ]
    assert rev["unchanged_experiments"] == ["E2", "E3", "E4", "E5", "E6"]
    assert rev["untraced_changes"] == [] and rev["undecided_changes"] == []
    # The overstated LAP sentence and the unobserved pSmad2 assumption are reported as dropped.
    assert [f["code"] for f in rev["findings"]] == ["prediction_assumption_removed"] * 3
