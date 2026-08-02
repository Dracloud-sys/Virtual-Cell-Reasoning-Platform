"""``virtualcell experiment import`` — the CLI surface of PR13b ingestion.

The command's contract is narrow on purpose: read a declared spec, read a source, print
what was imported and what QC decided, and **write nothing**. Turning imported data into
asserted evidence is a separate, deliberate act, so this command cannot do it by accident.

Exit codes follow the literature CLI convention: the typed status is authoritative, and a
caller must never have to infer failure from counts in the output.
"""

from __future__ import annotations

import json

import pytest

from virtualcell.cli import main as cli_main

CSV = """cell_line,passage,PDL,DT_min
IMR 90,25,22.0,2520
IMR 90,30,25.5,4800
IMR 90,35,NA,6000
"""

SPEC = {
    "dataset_id": "fibroblast_passages",
    "source_format": "csv",
    "conditions": {"medium": "DMEM"},
    "columns": [
        {"header": "cell_line", "role": "identifier"},
        {"header": "passage", "role": "time_axis", "time_axis": "passage"},
        {
            "header": "PDL",
            "role": "measurement",
            "name": "cumulative_PDL",
            "value_type": "numeric",
            "unit": "population_doubling",
        },
        {
            "header": "DT_min",
            "role": "measurement",
            "name": "DT_hours",
            "value_type": "numeric",
            "unit": "hour",
            "source_unit": "minute",
            "unit_factor": 0.016666666666666666,
        },
    ],
}


@pytest.fixture
def files(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(SPEC), encoding="utf-8")
    csv_path = tmp_path / "passages.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    return spec_path, csv_path


def _run(args: list[str]) -> int:
    return cli_main(args)


def test_import_reports_runs_qc_and_normalization(files, capsys) -> None:
    spec_path, csv_path = files
    assert _run(["experiment", "import", "--spec", str(spec_path), "--input", str(csv_path)]) == 0

    out = capsys.readouterr().out
    assert "status: success" in out
    assert "runs: 1" in out
    assert "observations: 3" in out
    assert "minute -> hour" in out


def test_json_output_carries_the_canonical_runs(files, capsys) -> None:
    spec_path, csv_path = files
    _run(
        [
            "experiment",
            "import",
            "--spec",
            str(spec_path),
            "--input",
            str(csv_path),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    run = payload["runs"][0]
    assert run["run_id"] == "ingestion:fibroblast_passages:cell_line=IMR_90"
    assert run["checksum"].startswith("sha256:")
    assert run["schema_version"]
    # 2520 minutes read as 42 hours, by the factor the spec declared.
    doubling = next(m for m in run["observations"][0]["measurements"] if m["name"] == "DT_hours")
    assert doubling["value"] == 42.0
    assert payload["qc"]["decisions"]


def test_a_failed_import_exits_non_zero(files, capsys, tmp_path) -> None:
    """The status is authoritative — a caller must not infer failure from the counts."""
    spec_path, _ = files
    empty = tmp_path / "empty.csv"
    empty.write_text("cell_line,passage,PDL,DT_min\n", encoding="utf-8")

    assert _run(["experiment", "import", "--spec", str(spec_path), "--input", str(empty)]) == 1
    assert "status: no_rows" in capsys.readouterr().out


def test_a_missing_source_exits_non_zero_without_a_traceback(files, capsys) -> None:
    spec_path, _ = files
    assert _run(["experiment", "import", "--spec", str(spec_path), "--input", "no/such.csv"]) == 1
    assert "unreadable_source" in capsys.readouterr().out


def test_an_invalid_spec_is_rejected_before_any_reading(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"dataset_id": "d", "columns": []}), encoding="utf-8")
    source = tmp_path / "x.csv"
    source.write_text("a\n1\n", encoding="utf-8")

    assert _run(["experiment", "import", "--spec", str(bad), "--input", str(source)]) == 1
    assert "invalid dataset spec" in capsys.readouterr().out


def test_import_writes_nothing(files, tmp_path, capsys) -> None:
    """No knowledge-base side effect: the command has no --save, and produces no files."""
    spec_path, csv_path = files
    before = set(tmp_path.iterdir())
    _run(["experiment", "import", "--spec", str(spec_path), "--input", str(csv_path)])
    capsys.readouterr()
    assert set(tmp_path.iterdir()) == before
