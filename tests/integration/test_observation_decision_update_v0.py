"""Observation-driven decision update v0 (docs/research_sessions/observation_decision_update_v0/).

Checks that the decision record points at the comparisons actually computed, that every target
and reference exists in the case's own records, that the source records are unchanged, and that
the run is reproducible. It does not check which decision the host took: keep / revise / hold are
the host's, not a computed answer.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from virtualcell.mcp.server import build_server
from virtualcell.research.contracts import HostDecision

pytest.importorskip("mcp.server.mcpserver.exceptions")
DOCS = Path(__file__).resolve().parents[2] / "docs" / "research_sessions"
CASE = DOCS / "observation_decision_update_v0"


def _json(path: Path):
    return json.loads(path.read_text())


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("odu_run", CASE / "run_comparison.py")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode, before = True, sys.dont_write_bytecode
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


@pytest.fixture(scope="module")
def computed(mod):
    return mod.compute(build_server())


@pytest.fixture(scope="module")
def recorded():
    return {
        "comparison": _json(CASE / "comparison.json"),
        "decision": _json(CASE / "decision.json"),
        "next": _json(CASE / "next_action.json"),
        "before": _json(CASE / "before.json"),
        "case": _json(DOCS / "logic_biology_v1" / "prereg" / "case.json"),
    }


# --- reproducibility ------------------------------------------------------------------------- #


def test_the_comparison_rebuilds_byte_for_byte_and_twice(mod, computed):
    text = json.dumps(computed, indent=1, sort_keys=True) + "\n"
    assert text == (CASE / "comparison.json").read_text()
    assert mod.compute(build_server()) == computed


def test_the_inputs_are_the_ones_hashed_in_run_json():
    run = _json(CASE / "run.json")
    for name, digest in run["inputs_sha256"].items():
        assert hashlib.sha256((DOCS / name).read_bytes()).hexdigest() == digest, name
    comparison = (CASE / "comparison.json").read_bytes()
    assert hashlib.sha256(comparison).hexdigest() == run["comparison_sha256"]
    assert run["calls"]["run_logic_model"] == 0


def test_the_model_results_are_the_stored_runs(mod, recorded):
    window = _json(DOCS / "logic_window_v0" / "window_results.json")
    stored = _json(DOCS / "logic_biology_v1" / "results.json")
    for entry in recorded["before"]["comparison_fixed"]["models"]:
        key = f"{entry['model_id']}/KRAS"
        result = mod.model_result(entry["model_id"])
        assert result["run_sha256"] == window[key]["run_sha256"] == stored[key]["run_sha256"]
        assert result["model_sha256"] == stored[key]["model_sha256"]


def test_the_links_use_what_before_json_fixed(mod, recorded):
    fixed = recorded["before"]["comparison_fixed"]
    for args in mod.comparison_args().values():
        link = args["link"]
        assert link["observation"]["rule"] == fixed["rule"]
        assert link["correspondence"]["table"] == fixed["table"]
        assert link["correspondence"]["stated_by"] == fixed["correspondence_stated_by"] == "host"
        assert link["correspondence"].get("accepted_by") is None


# --- the decision points at what was computed ------------------------------------------------ #


def test_each_read_entry_is_a_computed_comparison(recorded):
    comparison = recorded["comparison"]
    for entry in recorded["decision"]["read"]:
        out = comparison[entry["model_id"]]
        for key in (
            "comparison_id",
            "link_id",
            "link_sha256",
            "observations_sha256",
            "model_sha256",
            "run_sha256",
        ):
            assert entry[key] == out[key], (entry["model_id"], key)
        assert set(entry["fields_read"]) <= set(out)
    assert {e["model_id"] for e in recorded["decision"]["read"]} == set(comparison)


def test_decisions_are_host_decisions_on_targets_the_case_defines(recorded):
    case = recorded["case"]
    known = {m["id"] for m in case["models"]}
    known |= {r["id"] for m in case["models"] for r in m["rules"]}
    known |= {q["id"] for q in case["questions"]}
    next_id = recorded["next"]["id"]
    for raw in recorded["decision"]["decisions"]:
        decision = HostDecision(**raw)
        assert decision.target_id in known, decision.target_id
        assert decision.next_experiment_ids == [next_id]
    assert recorded["decision"]["next_action"] == next_id
    assert set(recorded["next"]["serves_decisions"]) == {
        d["target_id"] for d in recorded["decision"]["decisions"]
    }


def test_the_prior_is_the_fixed_d0(recorded):
    decision, before = recorded["decision"], recorded["before"]
    assert decision["prior"]["id"] == before["D0"]["id"]
    assert decision["question_id"] == before["question"]["id"]


def test_review_candidates_are_few_and_name_elements_of_this_comparison(recorded):
    candidates = recorded["decision"]["review_candidates"]
    assert 1 <= len(candidates) <= 3
    case = recorded["case"]
    rule_ids = {r["id"] for m in case["models"] for r in m["rules"]}
    before_text = json.dumps(recorded["before"])
    for c in candidates:
        named = c["element"]
        assert any(r in named for r in rule_ids) or any(
            field in named and field in before_text
            for field in ("table_assumption", "other_assumptions")
        ), c["id"]


def test_branches_lead_to_different_decisions(recorded):
    branches = recorded["next"]["branches"]
    assert len(branches) >= 2
    assert len({b["then"] for b in branches}) == len(branches)
    assert all(b["rests_on"] for b in branches)


# --- nothing earlier was changed ------------------------------------------------------------- #


@pytest.mark.parametrize(
    "folder",
    [
        "logic_biology_v1",
        "logic_biology_v1/prereg",
        "logic_window_v0",
        "erk_pmek_measurement_v0",
        "model_observation_link_v0",
        "model_observation_link_v0/review_r1",
        "model_observation_link_v0/review_r2",
        "observation_decision_update_v0",
        "observation_decision_update_v0/revision_r1",
    ],
)
def test_records_match_their_checksums(folder):
    for line in (DOCS / folder / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        assert hashlib.sha256((DOCS / folder / name).read_bytes()).hexdigest() == digest, name


# --- revision r1: corrections point at what exists ------------------------------------------- #


def test_revision_r1_cites_the_comparisons_and_limits_that_exist(recorded):
    corrections = _json(CASE / "revision_r1" / "corrections.json")
    reconfirmed = " ".join(corrections["new_vs_reconfirmed"]["reconfirmed_with_identifiers"])
    for out in recorded["comparison"].values():
        assert out["comparison_id"] in reconfirmed
    # The limits D0 left out are quoted from records that still say them.
    r1 = (DOCS / "logic_biology_v1" / "revision_r1" / "README.md").read_text()
    review = (DOCS / "erk_pmek_measurement_v0" / "review_r1" / "README.md").read_text()
    assert "not a refutation of feedback acting at RAS" in r1
    assert "not promoted to a verified result" in r1
    assert "says nothing about the size of pMek within" in review
    # The rule is described, not changed.
    rule = recorded["before"]["comparison_fixed"]["rule"]
    assert str(rule["increase_at_or_above"]) in corrections["rule_level"]["rule"]


def test_revision_r1_keeps_the_action_and_replaces_only_its_premises(recorded):
    n1 = _json(CASE / "revision_r1" / "corrections.json")["n1_r1"]
    assert "../next_action.json" in n1["supersedes"]
    assert recorded["next"]["id"] == recorded["decision"]["next_action"]
    assert len(n1["branches"]) == 3 and len({b["then"] for b in n1["branches"]}) == 3
