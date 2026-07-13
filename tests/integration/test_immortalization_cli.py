"""CLI integration tests for `virtualcell assess immortalization` (PR6)."""

from __future__ import annotations

import json

from virtualcell.cli import main
from virtualcell.reasoning.decision import DecisionReport


def _write(tmp_path, payload: dict) -> str:
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_assess_json_output_round_trips(tmp_path, capsys) -> None:
    path = _write(
        tmp_path,
        {
            "intent": "immortalization_assessment",
            "PDL_trend": "increasing",
            "DT_trend": "worsening",
            "gammaH2AX": "normal",
            "SA_b_gal": "normal",
            "p16": "high",
            "p21": "high",
        },
    )
    rc = main(["assess", "immortalization", "--input", path, "--format", "json"])
    assert rc == 0
    report = DecisionReport.model_validate(json.loads(capsys.readouterr().out))
    assert report.candidate_status == "senescence_or_stress_prone"
    assert "trend_needed" in [f.value for f in report.flags]


def test_assess_mechanism_uses_seed_graph(tmp_path, capsys) -> None:
    # No --load: the seed graph must be auto-constructed for mechanism grounding.
    path = _write(tmp_path, {"intent": "mechanism_explanation", "construct": "TERT_plus_CDK4"})
    rc = main(["assess", "immortalization", "--input", path, "--format", "json"])
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["candidate_status"] is None
    assert result["mechanistic_chain"]  # grounded from the seed


def test_assess_text_output(tmp_path, capsys) -> None:
    path = _write(tmp_path, {"intent": "hypothesis_handling"})
    rc = main(["assess", "immortalization", "--input", path])
    assert rc == 0
    out = capsys.readouterr().out
    assert "status: insufficient_evidence" in out


def test_assess_observations_series_includes_trajectory(tmp_path, capsys) -> None:
    path = _write(
        tmp_path,
        {
            "intent": "immortalization_assessment",
            "observations": [
                {"passage": 25, "cumulative_PDL": 22.0, "DT_hours": 42},
                {"passage": 30, "cumulative_PDL": 25.5, "DT_hours": 80},
                {"passage": 35, "cumulative_PDL": 27.0, "DT_hours": 100},
            ],
        },
    )
    rc = main(["assess", "immortalization", "--input", path, "--format", "json"])
    assert rc == 0
    report = DecisionReport.model_validate(json.loads(capsys.readouterr().out))
    assert report.trajectory["state"] == "progressive_slowdown"
    assert report.derived_input["DT_trend"] == "worsening"


def test_assess_text_output_surfaces_blocked_override(tmp_path, capsys) -> None:
    path = _write(
        tmp_path,
        {
            "intent": "immortalization_assessment",
            "PDL_trend": "plateau",
            "observations": [
                {"passage": 20, "cumulative_PDL": 25.0, "DT_hours": 40},
                {"passage": 25, "cumulative_PDL": 24.0, "DT_hours": 42},
                {"passage": 30, "cumulative_PDL": 26.0, "DT_hours": 41},
            ],
        },
    )
    rc = main(["assess", "immortalization", "--input", path])
    assert rc == 0
    out = capsys.readouterr().out
    assert "blocked overrides" in out
    assert "usable timepoints" in out


def test_assess_invalid_observation_exits_nonzero(tmp_path, capsys) -> None:
    # A negative doubling time is an input error -> non-zero exit, not a traceback.
    path = _write(
        tmp_path,
        {"intent": "immortalization_assessment", "observations": [{"passage": 25, "DT_hours": -5}]},
    )
    rc = main(["assess", "immortalization", "--input", path])
    assert rc == 1


def test_assess_missing_file_exits_nonzero(capsys) -> None:
    rc = main(["assess", "immortalization", "--input", "does-not-exist.json"])
    assert rc == 1


def test_assess_invalid_input_exits_nonzero(tmp_path, capsys) -> None:
    path = _write(tmp_path, {"intent": "immortalization_assessment", "p16": "nope"})
    rc = main(["assess", "immortalization", "--input", path])
    assert rc == 1
