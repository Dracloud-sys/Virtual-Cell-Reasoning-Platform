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
    "spec_version": "1.0",
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
    assert run["run_id"] == "ingestion:fibroblast_passages:cell_line=IMR%2090"
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
    bad.write_text(
        json.dumps({"spec_version": "1.0", "dataset_id": "d", "columns": []}), encoding="utf-8"
    )
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


# --- review round 2: three exit codes, three answers -------------------------


def _write(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_partial_import_exits_two_and_names_the_rejected_rows(files, tmp_path, capsys) -> None:
    """A partial import must not exit 0 (the rejects would go unseen) nor 1 (the runs it
    did produce are real)."""
    spec_path, _ = files
    source = _write(
        tmp_path,
        "partial.csv",
        "cell_line,passage,PDL,DT_min\nIMR 90,25,22.0,2520\nIMR 90,x,25.5,4800\n",
    )

    assert _run(["experiment", "import", "--spec", str(spec_path), "--input", str(source)]) == 2

    out = capsys.readouterr().out
    assert "status: partial" in out
    assert "rejected row 1 (unusable_time_point)" in out


def test_rejecting_every_row_exits_one(files, tmp_path, capsys) -> None:
    spec_path, _ = files
    source = _write(tmp_path, "none.csv", "cell_line,passage,PDL,DT_min\nIMR 90,x,22.0,2520\n")

    assert _run(["experiment", "import", "--spec", str(spec_path), "--input", str(source)]) == 1
    assert "status: no_valid_rows" in capsys.readouterr().out


def test_a_clean_import_still_exits_zero(files, capsys) -> None:
    spec_path, csv_path = files
    assert _run(["experiment", "import", "--spec", str(spec_path), "--input", str(csv_path)]) == 0
    assert "rejected row" not in capsys.readouterr().out


def test_rejected_rows_are_structured_in_the_json_surface(files, tmp_path, capsys) -> None:
    spec_path, _ = files
    source = _write(
        tmp_path,
        "partial.csv",
        "cell_line,passage,PDL,DT_min\nIMR 90,25,22.0,2520\n,30,25.5,4800\n",
    )
    _run(
        [
            "experiment",
            "import",
            "--spec",
            str(spec_path),
            "--input",
            str(source),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "partial"
    rejection = payload["rejected_rows"][0]
    assert (rejection["row_index"], rejection["reason"]) == (1, "unusable_identifier")
    assert rejection["column"] == "cell_line"


def test_an_unversioned_spec_is_refused_by_the_cli(tmp_path, capsys) -> None:
    unversioned = {key: value for key, value in SPEC.items() if key != "spec_version"}
    spec_path = _write(tmp_path, "unversioned.json", json.dumps(unversioned))
    source = _write(tmp_path, "x.csv", CSV)

    assert _run(["experiment", "import", "--spec", str(spec_path), "--input", str(source)]) == 1
    assert "invalid dataset spec" in capsys.readouterr().out


# --- review round 3: one bad cell must never become a traceback --------------


def test_an_overflowing_cell_does_not_abort_the_import(files, tmp_path, capsys) -> None:
    """A raw cell reading "1e999" must produce a structured QC verdict, not a crash: the
    CLI exits cleanly and the run it could build is still reported."""
    spec_path, _ = files
    source = _write(
        tmp_path,
        "overflow.csv",
        "cell_line,passage,PDL,DT_min\nIMR 90,25,1e999,2520\nIMR 90,30,25.5,4800\n",
    )

    exit_code = _run(
        [
            "experiment",
            "import",
            "--spec",
            str(spec_path),
            "--input",
            str(source),
            "--format",
            "json",
        ]
    )
    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    overflowing = next(
        m
        for m in payload["runs"][0]["observations"][0]["measurements"]
        if m["name"] == "cumulative_PDL"
    )
    assert overflowing["value"] is None
    assert overflowing["quality"] == "suspect"
    assert overflowing["provenance"]["metadata"]["raw_text"] == "1e999"


def test_a_spec_with_colliding_column_names_is_refused_by_the_cli(tmp_path, capsys) -> None:
    colliding = json.loads(json.dumps(SPEC))
    colliding["columns"].append({"header": "batch", "role": "identifier", "name": "cell_line"})
    spec_path = _write(tmp_path, "colliding.json", json.dumps(colliding))
    source = _write(tmp_path, "x.csv", CSV)

    assert _run(["experiment", "import", "--spec", str(spec_path), "--input", str(source)]) == 1
    assert "invalid dataset spec" in capsys.readouterr().out


# --- review round 4: an ambiguous header row is an unreadable source ---------


def test_duplicate_headers_exit_one_as_an_unreadable_source(files, tmp_path, capsys) -> None:
    """The file cannot be read unambiguously, so it is a source failure rather than a
    per-row QC outcome — reported as a typed status, with no traceback."""
    spec_path, _ = files
    source = _write(
        tmp_path,
        "duplicate.csv",
        "cell_line,cell_line,passage,PDL,DT_min\nIMR 90,BJ,25,22.0,2520\n",
    )

    assert _run(["experiment", "import", "--spec", str(spec_path), "--input", str(source)]) == 1

    out = capsys.readouterr().out
    assert "status: unreadable_source" in out
    assert "duplicate header" in out
    assert "Traceback" not in out
