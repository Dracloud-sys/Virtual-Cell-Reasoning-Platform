"""The compact draft check must be shorter without being quieter.

Replayed on the payloads a real host sent in `docs/research_sessions/eval1_persistence/`:
the first draft wrote pair strings in `discriminates` and left `supporting_evidence_ids`
empty while `evidence_links` named the support; the revised one fixed both. Nothing here
generates new biology: the mixed-error draft is the revised payload with known edits.

What is held:

* one input mistake is one group, every location and value kept, and what follows from it is
  nested under it, counted, not dropped;
* a real hypothesis with no prediction stays its own finding, not folded into an input error;
* the three ``unsupported_evidence_link`` situations stay apart, and none promotes an id;
* the three predictions with an unstated assumption stay visible next to the input errors;
* the plan analysis and the what-if impact are the same in both views;
* compact says what it left out, and has no empty ``findings`` list to be read as clean.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest

mcp_server = pytest.importorskip(
    "virtualcell.mcp.server",
    reason="the MCP adapter needs the optional 'mcp' extra",
)

RECORDS = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research_sessions"
    / "eval1_persistence"
    / "records"
)


def _payload(name: str) -> dict[str, Any]:
    return json.loads((RECORDS / name).read_text(encoding="utf-8"))


FIRST = _payload("condition_B_payload_1.json")
REVISED = _payload("condition_B_payload_2.json")


def _check(payload: dict[str, Any], view: str | None = None) -> dict[str, Any]:
    arguments = dict(payload) if view is None else {**payload, "view": view}
    result = asyncio.run(mcp_server.build_server().call_tool("check_research_draft", arguments))
    assert not result.is_error, result.content
    return result.structured_content


def _size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False))


def _group(out: dict[str, Any], code: str, **match: Any) -> dict[str, Any]:
    hits = [
        g
        for g in out["finding_groups"]
        if g["code"] == code and all(g.get(k) == v for k, v in match.items())
    ]
    assert len(hits) == 1, [(g["code"], g.get("field"), g.get("case")) for g in hits]
    return hits[0]


@pytest.fixture(scope="module")
def first_full() -> dict[str, Any]:
    return _check(FIRST)


@pytest.fixture(scope="module")
def first_compact() -> dict[str, Any]:
    return _check(FIRST, "compact")


def test_the_default_view_is_unchanged_in_what_it_lists(first_full):
    assert first_full["view"] == "full"
    assert len(first_full["findings"]) == first_full["finding_count"] == 83
    assert first_full["plan_analysis"] is not None
    assert first_full["plan_summary"] is None


def test_one_input_mistake_is_one_group_with_its_consequence_nested(first_compact):
    group = _group(first_compact, "unknown_hypothesis_id", field="experiments[].discriminates")
    assert group["kind"] == "input"
    assert group["count"] == 39
    assert len(group["occurrences"]) == 39
    assert {o["value"] for o in group["occurrences"]} >= {"H1 vs H2", "H4 vs H8"}
    assert "one per entry" in group["detail"]
    (derived,) = group["derived"]
    assert derived["code"] == "discrimination_claimed_without_predictions"
    assert derived["count"] == 39
    assert derived["same_occurrences_as_parent"] is True
    assert not any(
        g["code"] == "discrimination_claimed_without_predictions"
        for g in first_compact["finding_groups"]
    )


def test_no_finding_is_lost_in_grouping(first_compact):
    grouped = sum(
        g["count"] + sum(d["count"] for d in g["derived"])
        for g in first_compact["finding_groups"]
        if g["source"] == "findings"
    )
    assert grouped == first_compact["finding_count"] == 83


def test_the_unstated_assumptions_stay_visible_beside_the_input_errors(first_compact):
    group = _group(first_compact, "assumption_without_stated_assumptions")
    assert group["kind"] == "review"
    assert group["source"] == "prediction_traces"
    assert [o["where"] for o in group["occurrences"]] == [
        "experiment:E2:H1:aSMA_in_naive_recipient",
        "experiment:E3:H1:clonal_bimodality",
        "experiment:E4:H1:GATA6_protein",
    ]
    kinds = [g["kind"] for g in first_compact["finding_groups"]]
    assert kinds == sorted(kinds), "input groups come before review groups"


def test_support_listed_only_in_evidence_links_is_an_input_mismatch_not_support(first_compact):
    group = _group(
        first_compact, "unsupported_evidence_link", case="supports_link_not_in_supporting_ids"
    )
    assert group["kind"] == "input"
    assert [o["where"] for o in group["occurrences"]] == [f"hypothesis:H{i}" for i in range(2, 7)]
    assert "unverified candidate" in group["detail"]


def test_the_plan_analysis_and_impact_are_the_same_in_both_views(first_full, first_compact):
    plan, summary = first_full["plan_analysis"], first_compact["plan_summary"]
    assert summary["impact"] == plan["impact"]
    assert summary["impact"]["affected_hypotheses"] == ["H4", "H1"]
    assert summary["impact"]["affected_experiments"] == ["E1", "E5"]
    assert [e["separated_pairs"] for e in summary["experiments"]] == [
        [p["pair"] for p in e["separated_pairs"]] for e in plan["experiments"]
    ]
    assert [e["unseparated_pairs"] for e in summary["experiments"]] == [
        e["unseparated_pairs"] for e in plan["experiments"]
    ]
    assert summary["pairs_never_separated"] == plan["pairs_never_separated"]
    assert summary["limits"] == plan["limits"]
    assert summary["prediction_count"] == len(plan["prediction_traces"])
    assert first_compact["evidence_origins"] == first_full["evidence_origins"]
    assert first_compact["not_checked"] == first_full["not_checked"]


def test_compact_is_short_and_says_what_it_left_out(first_full, first_compact):
    assert _size(first_compact) * 5 < _size(first_full)
    assert first_compact["findings"] is None, "an empty list would read as a clean result"
    assert first_compact["plan_analysis"] is None
    assert any("prediction_traces" in line for line in first_compact["omitted"])
    assert any("view='full'" in line for line in first_compact["omitted"])


def test_what_was_not_computed_is_said_and_not_passed(first_compact):
    lines = first_compact["not_computed"]
    assert any(line.startswith("experiment:E1: 12 discriminates") for line in lines)
    revised = _check(REVISED, "compact")
    assert revised["not_computed"] == [
        "what_if was not sent, so no dependency impact was computed."
    ]


def test_the_revised_draft_keeps_its_one_finding(first_compact):
    revised = _check(REVISED, "compact")
    assert revised["finding_count"] == 1
    (group,) = revised["finding_groups"]
    assert group["code"] == "understated_evidence_link"
    assert group["occurrences"][0]["where"] == "hypothesis:H7"


def _mixed() -> dict[str, Any]:
    draft = copy.deepcopy(REVISED)
    experiments = {e["id"]: e for e in draft["experiments"]}
    hypotheses = {h["id"]: h for h in draft["hypotheses"]}
    # an input mistake: a pair string where a hypothesis id belongs
    experiments["E1"]["discriminates"].append("H1 vs H4")
    # a real hypothesis that E2 says it separates, with no prediction for it in E2
    experiments["E2"]["predictions"] = [
        p for p in experiments["E2"]["predictions"] if p["hypothesis_id"] != "H8"
    ]
    # support linked in evidence_links only
    hypotheses["H2"]["supporting_evidence_ids"] = []
    # only non-supporting links left
    hypotheses["H6"]["supporting_evidence_ids"] = []
    draft["evidence_links"] = [
        link
        for link in draft["evidence_links"]
        if not (link["target_id"] == "H6" and link["role"] == "supports")
        and link["target_id"] != "H3"
    ]
    # nothing grounded linked at all
    hypotheses["H3"]["supporting_evidence_ids"] = []
    return draft


def test_a_real_missing_prediction_is_not_folded_into_an_input_error():
    out = _check(_mixed(), "compact")
    unknown = _group(out, "unknown_hypothesis_id", field="experiments[].discriminates")
    assert [(o["where"], o["value"]) for o in unknown["occurrences"]] == [
        ("experiment:E1", "H1 vs H4")
    ]
    assert [d["count"] for d in unknown["derived"]] == [1]
    real = _group(out, "discrimination_claimed_without_predictions")
    assert real["caused_by"] is None
    assert real["kind"] == "review"
    assert [(o["where"], o["value"]) for o in real["occurrences"]] == [("experiment:E2", "H8")]


def test_the_three_unsupported_situations_stay_apart():
    out = _check(_mixed(), "compact")
    cases = {
        g["case"]: [o["where"] for o in g["occurrences"]]
        for g in out["finding_groups"]
        if g["code"] == "unsupported_evidence_link"
    }
    assert cases == {
        "supports_link_not_in_supporting_ids": ["hypothesis:H2"],
        "only_non_supporting_links": ["hypothesis:H6"],
        "no_grounded_support": ["hypothesis:H3"],
    }
    kinds = {
        g["case"]: g["kind"]
        for g in out["finding_groups"]
        if g["code"] == "unsupported_evidence_link"
    }
    assert kinds["only_non_supporting_links"] == kinds["no_grounded_support"] == "review"


def test_the_published_schema_says_discriminates_takes_hypothesis_ids():
    tools = {t.name: t for t in asyncio.run(mcp_server.build_server().list_tools())}
    schema = tools["check_research_draft"].input_schema
    experiment = schema["properties"]["experiments"]["anyOf"][0]["items"]["properties"]
    field = experiment["discriminates"]
    assert "hypotheses[].id" in field["description"]
    assert "H1 vs H4" in field["description"]
    assert field["examples"] == [["H1", "H4"]]
    hypothesis = schema["properties"]["hypotheses"]["anyOf"][0]["items"]["properties"]
    assert "evidence_links" in hypothesis["supporting_evidence_ids"]["description"]
    assert set(schema["properties"]["view"]["enum"]) == {"full", "compact"}
