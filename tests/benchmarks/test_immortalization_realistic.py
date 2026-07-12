"""REALISTIC-IMM-V01 — end-to-end check on a representative, de-identified case.

Kept separate from the synthetic TS01-TS12 grid: this exercises the whole PR7
path (raw passage series -> trajectory -> effective markers -> DecisionReport) on
a case shaped like real bovine-preadipocyte data, and pins the behaviors that
matter operationally — raw DT is actually consumed, both proliferation and
slowdown are preserved, senescence markers land on the contradicting side, and
the report neither overcalls immortalization nor advises premature discard.
"""

from __future__ import annotations

import json
from pathlib import Path

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.rules import build_decision_report

_FIXTURE = Path(__file__).parent / "fixtures" / "realistic_imm_v01.json"


def _report():
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    scenario = {k: v for k, v in payload.items() if k not in ("intent", "_note")}
    return build_decision_report(input_from_scenario(payload["intent"], scenario))


def test_raw_dt_series_is_actually_consumed() -> None:
    report = _report()
    assert report.trajectory is not None
    # The trajectory was derived from raw DT hours, not from a snapshot label.
    assert report.trajectory["state"] == "progressive_slowdown"
    assert report.trajectory["DT_fold_change"] is not None
    assert report.derived_input["DT_trend"] == "worsening"


def test_proliferation_and_slowdown_are_both_preserved() -> None:
    report = _report()
    assert report.trajectory["derived_PDL_trend"] == "increasing"
    assert report.trajectory["derived_DT_trend"] == "worsening"


def test_p16_p21_elevation_is_contradicting_evidence() -> None:
    report = _report()
    blob = " ".join(c.statement.lower() for c in report.contradicting_evidence)
    assert "p16 is elevated" in blob
    assert "p21 is elevated" in blob


def test_status_does_not_overcall_and_reports_missing_axis() -> None:
    report = _report()
    assert report.candidate_status == "senescence_or_stress_prone"
    # SA-b-Gal was never measured and must be surfaced as a missing axis.
    assert "SA-b-Gal" in report.missing_axes


def test_premature_discard_risk_is_preserved() -> None:
    report = _report()
    assert any("do not discard prematurely" in r.lower() for r in report.overinterpretation_risk)


def test_telomere_tert_verification_is_suggested() -> None:
    report = _report()
    blob = " ".join(report.next_experiment).lower()
    assert "telomere" in blob and "tert" in blob
