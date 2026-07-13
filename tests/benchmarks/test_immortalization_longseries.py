"""LONGSERIES-IMM-V01 — end-to-end check on a long-culture adversarial pattern.

This is the case the PR7 hardening exists for: a historical plateau/recovery/
plateau crisis followed by long terminal growth, plus a single terminal DT spike.
The original engine returned ``re_arrest`` (terminal state ignored); the hardened
engine must anchor on the terminal (growing) state, surface the recent DT
deterioration separately, and still not confirm a candidate from the series alone.
"""

from __future__ import annotations

import json
from pathlib import Path

from virtualcell.agents.immortalization.adapters import input_from_scenario
from virtualcell.agents.immortalization.rules import build_decision_report

_FIXTURE = Path(__file__).parent / "fixtures" / "longseries_imm_v01.json"


def _report():
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    scenario = {k: v for k, v in payload.items() if k not in ("intent", "_note")}
    return build_decision_report(input_from_scenario(payload["intent"], scenario))


def test_terminal_growth_is_not_re_arrest() -> None:
    report = _report()
    assert report.trajectory["state"] != "re_arrest"
    assert report.trajectory["state"] == "recovery_after_plateau"


def test_terminal_dt_spike_is_surfaced_not_hidden() -> None:
    report = _report()
    assert report.trajectory["terminal_dt_spike"] is True
    assert any("terminal spike" in u.lower() for u in report.uncertainty)


def test_series_alone_still_does_not_confirm_a_candidate() -> None:
    report = _report()
    # No senescence axis measured -> the invariant holds despite sustained growth.
    assert report.candidate_status == "insufficient_evidence"


def test_historical_crisis_is_distinguished_in_rationale() -> None:
    report = _report()
    rationale = " ".join(report.trajectory["rationale"]).lower()
    assert "earlier plateau" in rationale and "terminal" in rationale
