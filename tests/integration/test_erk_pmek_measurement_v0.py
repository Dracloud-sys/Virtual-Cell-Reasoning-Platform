"""The pMEK measurement record (docs/research_sessions/erk_pmek_measurement_v0/).

These tests check the record's links and that values were not changed on the way in. They do
not require the paper and the model to agree, and they do not compare figure estimates as exact
values.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs" / "research_sessions"
CASE = DOCS / "erk_pmek_measurement_v0"
# Doses such as "0.5 and 1 uM" or "0.5-10 uM" are conditions, not measured values.
DOSES = r"\d+(?:\.\d+)?(?:\s*(?:and|-|,)\s*\d+(?:\.\d+)?)*\s*uM"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_checksums_hold():
    for line in (CASE / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split()
        assert hashlib.sha256((CASE / name).read_bytes()).hexdigest() == digest, name


def test_extracted_values_are_strings_with_lines_and_the_authors_units():
    e = _json(CASE / "extracted.json")
    assert "normalised to PBS treated cells" in e["fig6B"]["header"]
    assert "normalised by one 0-timepoint" in " ".join(e["fig6C"]["column_labels"][1])
    lines = [r["line"] for r in e["fig6B"]["rows"]]
    assert lines == sorted(set(lines)) and lines[0] == 4
    for r in e["fig6B"]["rows"]:
        assert isinstance(r["value"], str)
        float(r["value"])  # parseable, but kept as written
    for cell, s in e["fig6B"]["by_cell_line"].items():
        assert s["controls"]["PBS (reference, defined as 1)"] == ["1"], cell
        # The repeated control rows are flagged, not counted as further measurements.
        assert len(s["control_rows_repeated_verbatim"]) == 3, cell
        assert len(s["controls"]["untreated"]) == 2 and len(s["controls"]["DMSO"]) == 1


def test_observations_cite_lines_that_hold_the_numbers_they_quote():
    e = _json(CASE / "extracted.json")
    by_line = {r["line"]: r["value"] for r in e["fig6B"]["rows"]}
    record = _json(CASE / "measurement_record.json")
    for o in record["observations"]:
        if o["level"] != "B" or o["panel"] != "6B":
            continue
        cited = set()
        for a, b in re.findall(
            r"(\d+)(?:-(\d+))?", re.sub(r"\([^)]*\)", "", o["lines"].split("lines", 1)[1])
        ):
            cited |= set(range(int(a), int(b or a) + 1))
        values = [by_line[n] for n in cited]
        for quoted in re.findall(r"\d+\.\d+", re.sub(DOSES, "", o["statement"])):
            # every quoted number is the leading part of a value on a cited line
            assert any(
                v.startswith(quoted) or f"{float(v):.2f}" == quoted or f"{float(v):.3f}" == quoted
                for v in values
            ), (o["id"], quoted)


def test_figure_readings_are_marked_as_estimates():
    record = _json(CASE / "measurement_record.json")
    d = record["panels"]["6D"]
    assert d["levels"][0].startswith("D")
    assert "None" in d["source_data"]
    assert "uncertainty" in d["readings"]["method"]
    assert all(o["level"] != "A" for o in record["observations"])


def test_model_outputs_quoted_are_the_stored_ones():
    w = _json(DOCS / "logic_window_v0" / "window_results.json")
    r0 = _json(DOCS / "logic_biology_v1" / "results.json")
    for key, run in w.items():
        assert run["run_sha256"] == r0[key]["run_sha256"]
        t = next(t for t in run["window"]["targets"] if t["target"] == "pMEK1_S217_S221_BioPlex")
        assert run["window"]["request"]["first"] == 18 and run["window"]["request"]["last"] == 24
        assert t["paired"]["directions"] == (
            ["increase", "no_change"] if key == "M1_feedback_on_RAF/KRAS" else ["no_change"]
        )


def test_earlier_records_are_unchanged():
    for folder in ("logic_biology_v1", "logic_biology_v1/revision_r1", "logic_window_v0"):
        for line in (DOCS / folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            digest, name = line.split()
            assert hashlib.sha256((DOCS / folder / name).read_bytes()).hexdigest() == digest


@pytest.mark.skipif(
    not os.environ.get("ERK_PMEK_SOURCE_CACHE"),
    reason="needs the downloaded source data files (set ERK_PMEK_SOURCE_CACHE)",
)
def test_extraction_reruns_byte_for_byte(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("erk_pmek_extract", CASE / "extract.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HERE", tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["extract.py", "--cache", os.environ["ERK_PMEK_SOURCE_CACHE"], "--offline"]
    )
    module.main()
    assert (tmp_path / "extracted.json").read_bytes() == (CASE / "extracted.json").read_bytes()
