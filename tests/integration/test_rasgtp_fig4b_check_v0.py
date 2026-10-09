"""N1 record check: Fig 4B Ras-activity source data (docs/research_sessions/rasgtp_fig4b_check_v0/).

Checks that what the record says is in the file is in the copied rows, that the checksums agree,
and that earlier records are unchanged. It does not require any BRAF data to exist or any model
to be right. The re-extraction needs the downloaded file and is skipped without it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs" / "research_sessions"
CASE = DOCS / "rasgtp_fig4b_check_v0"


def _json(path: Path):
    return json.loads(path.read_text())


def _extract_module():
    spec = importlib.util.spec_from_file_location("fig4b_extract", CASE / "extract.py")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode, before = True, sys.dont_write_bytecode
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


def test_the_recorded_cell_lines_and_treatments_are_the_files_rows():
    extracted = _json(CASE / "extracted.json")
    items = _json(CASE / "check.json")["items"]
    rows = extracted["rows"]
    assert [r["line"] for r in rows] == list(range(4, 4 + len(rows)))
    assert sorted({r["cell_line"] for r in rows}) == sorted(items["cell_lines"]["value"])
    assert {r["treatment"] for r in rows} == {"DMSO", "AZD6244"}
    # Every line the record cites as a source is a line the file has.
    assert "df4B lines 4-7" in items["cell_lines"]["sources"]
    assert extracted["header_lines"]["2"].split("\t")[2] == "GTP-bound Ras"


def test_the_checksums_agree_across_the_record():
    extracted = _json(CASE / "extracted.json")
    module = _extract_module()
    sources = json.dumps(_json(CASE / "sources.json"))
    assert extracted["md5"] == module.MANIFEST_MD5
    assert extracted["md5"] in sources and extracted["sha256"] in sources


@pytest.mark.skipif(
    not os.environ.get("RASGTP_FIG4B_SOURCE_CACHE"),
    reason="needs the downloaded source data file (set RASGTP_FIG4B_SOURCE_CACHE)",
)
def test_the_extraction_rebuilds_from_the_file():
    module = _extract_module()
    data, lines = module.read(Path(os.environ["RASGTP_FIG4B_SOURCE_CACHE"]))
    rebuilt = json.dumps(module.extract(data, lines), indent=1, ensure_ascii=False) + "\n"
    assert rebuilt == (CASE / "extracted.json").read_text(encoding="utf-8")
    assert module.extract(data, lines) == module.extract(data, lines)


@pytest.mark.parametrize(
    "folder",
    [
        "rasgtp_fig4b_check_v0",
        "erk_pmek_measurement_v0",
        "logic_biology_v1",
        "observation_decision_update_v0",
        "observation_decision_update_v0/revision_r1",
    ],
)
def test_records_match_their_checksums(folder):
    for line in (DOCS / folder / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        assert hashlib.sha256((DOCS / folder / name).read_bytes()).hexdigest() == digest, name
