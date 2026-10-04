"""The ERK-feedback application case (docs/research_sessions/logic_biology_v1).

These tests pin the record's internal links and its reproducibility. They do not require the
model to agree with the paper: the expected classes below are whatever the pre-registered rules
give, and a 미결정 or 불일치 row is as valid an outcome as a 부합 one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[2] / "docs" / "research_sessions" / "logic_biology_v1"
CLASSES = {"부합", "불일치", "미결정", "비교 불가"}


def _json(name: str) -> dict:
    return json.loads((CASE / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def case() -> dict:
    return _json("prereg/case.json")


@pytest.fixture(scope="module")
def obs() -> dict:
    return _json("observations.json")


@pytest.fixture
def run_case(monkeypatch):
    spec = importlib.util.spec_from_file_location("logic_biology_run_case", CASE / "run_case.py")
    module = importlib.util.module_from_spec(spec)
    # Importing it would otherwise leave a __pycache__ inside the case record.
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec.loader.exec_module(module)
    return module


# --- the pre-registration is the version that was run ------------------------------------ #


def test_the_preregistration_checksums_hold():
    for line in (CASE / "prereg" / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split()
        assert hashlib.sha256((CASE / "prereg" / name).read_bytes()).hexdigest() == digest, name


def test_the_run_record_names_the_preregistered_inputs():
    run = _json("run.json")
    for name, digest in run["inputs"].items():
        assert hashlib.sha256((CASE / name).read_bytes()).hexdigest() == digest, name


# --- evidence, rules, interventions and observations link up ------------------------------ #


def test_every_rule_evidence_id_is_a_listed_source(case):
    listed = set(re.findall(r"lit-[0-9a-f]{12}", (CASE / "prereg" / "PREREG.md").read_text()))
    for model in case["models"]:
        for rule in model["rules"]:
            assert set(rule["evidence_ids"]) <= listed, rule["id"]
    for readout in case["readouts"]:
        assert set(re.findall(r"lit-[0-9a-f]{12}", readout["basis"])) <= listed


def test_the_alternative_changes_only_the_feedback_rules(case):
    m1, m2 = ({r["target"]: r for r in m["rules"]} for m in case["models"])
    assert m1.keys() == m2.keys()
    changed = {t for t in m1 if m1[t]["expr"] != m2[t]["expr"]}
    assert changed == {"RAS", "RAF"}
    assert case["models"][0]["components"] == case["models"][1]["components"]


def test_readouts_questions_and_scenarios_resolve(case):
    components = {c["id"] for c in case["models"][0]["components"]}
    inputs = {c["id"] for c in case["models"][0]["components"] if c["kind"] == "input"}
    readouts = {r["readout"]: r for r in case["readouts"]}
    assert all(r["state"] in components for r in readouts.values())
    for q in case["questions"]:
        assert q["readout"] in readouts
        assert q["group"] in case["comparisons"] or q.get("precommitted_class") == "비교 불가"
    for pair in case["comparisons"].values():
        a, b = case["scenarios"][pair["scenario"]], case["scenarios"][pair["baseline"]]
        assert set(a["inputs"]) == set(b["inputs"]) == inputs
        # The comparison is the MEK inhibitor and nothing else.
        assert {k for k in inputs if a["inputs"][k] != b["inputs"][k]} == {"MEKi"}


def test_every_observation_cites_a_span_read_after_the_preregistration(case, obs):
    read = {e for section in obs["read"] for e in section["evidence_ids"]}
    prereg_text = (CASE / "prereg" / "PREREG.md").read_text(encoding="utf-8")
    questions = {q["id"] for q in case["questions"]}
    for row in obs["rows"]:
        assert row["evidence_id"] in read, row["id"]
        assert row["evidence_id"] not in prereg_text, row["id"]
        assert row["question"] in questions
        assert row["direction"] in (None, "increase", "decrease", "no_change")
    for item in obs["unregistered"]:
        assert item["evidence_id"] in read


# --- the comparison: reproducible, complete, not forced ----------------------------------- #


def test_the_case_reruns_to_the_recorded_results(run_case, case, obs):
    results, comparison, calls = run_case.compute(case, obs)
    dump = json.dumps(results, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    assert dump == (CASE / "results.json").read_text(encoding="utf-8")
    dump = json.dumps(comparison, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    assert dump == (CASE / "comparison.json").read_text(encoding="utf-8")
    assert len(calls) == 8
    again, _, _ = run_case.compute(case, obs)
    assert again == results


def test_every_row_is_classified_and_counted(case, obs):
    comparison = _json("comparison.json")
    assert [r["row"] for r in comparison["rows"]] == [r["id"] for r in obs["rows"]]
    columns = [f"{m['id']}/{r}" for m in case["models"] for r in ("strict", "ordinal")]
    for row in comparison["rows"]:
        for col in columns:
            assert row[col]["class"] in CLASSES
    for col in columns:
        assert sum(comparison["tally_of_all_rows"][col].values()) == comparison["rows_total"]


def test_drafts_stay_assumptions_and_runs_complete():
    for run in _json("results.json").values():
        assert run["draft_basis"] == ["assumption"]
        assert run["exploration_complete"] and run["limits_reached"] == []


def test_classification_follows_the_preregistered_rules(run_case):
    q = {"id": "Ox"}
    row = {"group": "KRAS", "direction": "increase"}
    assert run_case.classify(row, q, "increase")[0] == "부합"
    assert run_case.classify(row, q, "no_change")[0] == "불일치"
    assert run_case.classify(row, q, "undetermined")[0] == "미결정"
    assert run_case.classify({**row, "direction": None}, q, "increase")[0] == "비교 불가"
    assert run_case.classify({**row, "group": "no_scenario"}, q, "increase")[0] == "비교 불가"
    pre = {"precommitted_class": "비교 불가", "why": "no node"}
    assert run_case.classify(row, pre, "increase")[0] == "비교 불가"


def test_the_strict_reading_needs_one_direction_over_the_window(run_case):
    out = {
        "readouts": [
            {"readout": "R", "t": t, "paired": {"c0": d, "c1": d}}
            for t, d in ((1, "decrease"), (2, "increase"), (3, "increase"))
        ]
    }
    assert run_case.strict_reading(out, "R", range(2, 4))["direction"] == "increase"
    assert run_case.strict_reading(out, "R", range(1, 4))["direction"] == "undetermined"


def test_the_ordinal_reading_orders_window_classes(run_case):
    def case(label, values):
        return {"case": label, "path": [{"X": v} for v in values]}

    out = {
        "cases": [case("a", [True, True, True]), case("b", [True, True, True])],
        "baseline_cases": [case("a", [True, False, True]), case("b", [False, True, False])],
    }
    assert run_case.ordinal_reading(out, "X", range(3))["direction"] == "increase"
    out["baseline_cases"][1] = case("b", [True, True, True])
    assert run_case.ordinal_reading(out, "X", range(3))["direction"] == "undetermined"
    out["baseline_cases"][1] = case("b", [True, None, True])
    assert run_case.ordinal_reading(out, "X", range(3))["direction"] == "undetermined"


# --- revision r1: the text, the recorded direction and the computation kept apart --------- #

R1 = CASE / "revision_r1"


def _load(monkeypatch, name: str):
    spec = importlib.util.spec_from_file_location(f"logic_biology_{name}", R1 / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec.loader.exec_module(module)
    return module


def test_r0_is_kept_byte_for_byte():
    for line in (CASE / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split()
        assert hashlib.sha256((CASE / name).read_bytes()).hexdigest() == digest, name


def test_r1_rebuilds_and_keeps_every_r0_class(monkeypatch):
    out = _load(monkeypatch, "compare_r1").build()
    dump = json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    assert dump == (R1 / "comparison_r1.json").read_text(encoding="utf-8")
    r0 = {r["row"]: r for r in _json("comparison.json")["rows"]}
    observations = {r["id"]: r for r in _json("observations.json")["rows"]}
    for row in out["rows"]:
        assert row["recorded_direction_r0"] == observations[row["row"]]["direction"]
        for col, cell in row.items():
            if "/" in col:
                assert cell["r0_class"] == r0[row["row"]][col]["class"]
                assert (cell["relation"] == "비교 제한") == (cell["r0_class"] == "비교 불가")
                if cell["relation"] == "비교 제한":
                    assert cell["limit_cause"]
    for counts in out["tally_of_rows"].values():
        assert sum(counts.values()) == out["rows_total"] == 16


def test_r1_never_reads_no_increase_or_equal_states_as_an_exact_match(monkeypatch):
    relate = _load(monkeypatch, "compare_r1").relate
    both_on = {"always_active -> always_active": 32}
    on_off = {"always_active -> always_inactive": 32}
    flicker = {"intermittent -> always_active": 32}
    assert relate("decrease", "decrease", "strict", on_off)[0] == "일치"
    assert relate("no_increase", "no_change", "strict", both_on)[0] == "조건부 양립"
    assert relate("no_increase", "decrease", "strict", on_off)[0] == "조건부 양립"
    assert relate("no_increase", "increase", "strict", flicker)[0].startswith("불일치")
    assert relate("no_change_observed", "no_change", "strict", both_on)[0] == "조건부 양립"
    assert relate("increase", "increase", "ordinal", flicker)[0] == "조건부 양립"
    relation, needs = relate("increase", "no_change", "strict", both_on)
    assert relation.startswith("불일치") and any("equal Boolean states" in n for n in needs)
    assert relate("increase", "undetermined", "strict", flicker) == ("미결정", [])


def test_fixed_points_do_not_depend_on_a_paper(monkeypatch):
    module = _load(monkeypatch, "fixed_points")
    case = _json("prereg/case.json")
    from virtualcell.mcp.server import build_server

    server = build_server()
    m1, m2 = case["models"]
    # With KRAS on and no inhibitor, M1 reduces to pERK = NOT pERK: no state is fixed.
    assert module.fixed_points(server, case, m1, "KRAS_control") == []
    assert len(module.fixed_points(server, case, m2, "KRAS_control")) == 1
    recorded = _json("revision_r1/fixed_points.json")
    assert recorded["M1_feedback_on_RAF/KRAS_control"] == []
    assert all(len(v) == 1 for k, v in recorded.items() if k != "M1_feedback_on_RAF/KRAS_control")
