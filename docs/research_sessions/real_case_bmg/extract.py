"""Transcribe the per-well alamarBlue readings of Zenodo 8342247 into a tidy CSV, cell by cell.

The source workbook (``24 and 48 ORE Alamar blue.xlsx``) is a Tecan Spark export whose plate
grid was emptied except for the two ``AB`` wells; the other per-well values sit, typed in by the
author, in a side table on each sheet. This script copies those typed values and nothing else:

* every value keeps its sheet and cell (``source_sheet``, ``source_cell``);
* group labels are copied exactly as written (``TI-CTL``, ``TI-BMG``, ``POLY``, ``AB``);
* formula cells (the author's means, SDs and "% Viability") are not read;
* nothing is merged, averaged, renamed or dropped. Empty cells stay absent: there were four
  TI-CTL wells, not five with one missing;
* the 48 h values appear twice (on both sheets); the copies are compared and the 48 h sheet's
  copy is used. A disagreement stops the script.

Usage: python extract.py <workbook.xlsx> <out.csv> <report.json>
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import openpyxl

#: Where the typed values sit, per sheet: each group's label cell, and the value columns (the
#: author's summary columns, headed "media", start right after them).
SIDE_TABLES = {
    ("24 hours", 24): ({"TI-CTL": "K22", "TI-BMG": "K23", "POLY": "K24"}, ("L", "P")),
    ("48 hours", 48): ({"TI-CTL": "N7", "TI-BMG": "N8", "POLY": "N9"}, ("O", "S")),
}
#: The 48 h side table also copied onto the 24 h sheet; compared, not used.
DUPLICATE_48H = ({"TI-CTL": "K30", "TI-BMG": "K31", "POLY": "K32"}, ("L", "P"))
#: The AB wells, which stayed in the plate grid: label cell, and the value cells to its right.
AB_CELLS = {("24 hours", 24): ("A45", ["B45", "C45"]), ("48 hours", 48): ("G28", ["H28", "I28"])}
#: Read metadata, per sheet, as the export records it.
READ_META = {"24 hours": ("E41", "E42"), "48 hours": ("E22", "E23")}


def _typed_values(ws, label_cell: str, columns: tuple[str, str]) -> list[tuple[str, float]]:
    """The typed numbers in the value columns of a label's row. Empty cells stay absent."""
    row = ws[label_cell].row
    first, last = (openpyxl.utils.column_index_from_string(c) for c in columns)
    out = []
    for col in range(first, last + 1):
        cell = ws.cell(row=row, column=col)
        if cell.value in (None, ""):
            continue
        if isinstance(cell.value, str) and cell.value.startswith("="):
            raise SystemExit(f"{ws.title}!{cell.coordinate} is a formula, not a reading")
        if isinstance(cell.value, bool) or not isinstance(cell.value, (int, float)):
            raise SystemExit(f"{ws.title}!{cell.coordinate} is not a number: {cell.value!r}")
        out.append((cell.coordinate, cell.value))
    return out


def main() -> None:
    source, out_csv, out_report = map(Path, sys.argv[1:4])
    raw = source.read_bytes()
    wb = openpyxl.load_workbook(source, data_only=False)
    rows = []
    for (sheet, hours), (labels, columns) in SIDE_TABLES.items():
        ws = wb[sheet]
        started, temperature = (ws[c].value for c in READ_META[sheet])
        for label, cell in labels.items():
            if ws[cell].value != label:
                raise SystemExit(f"{sheet}!{cell} reads {ws[cell].value!r}, expected {label!r}")
            for coord, value in _typed_values(ws, cell, columns):
                rows.append((sheet, coord, label, hours, value, started, temperature))
        label_cell, value_cells = AB_CELLS[(sheet, hours)]
        if ws[label_cell].value != "AB":
            raise SystemExit(f"{sheet}!{label_cell} reads {ws[label_cell].value!r}, expected 'AB'")
        for coord in value_cells:
            rows.append((sheet, coord, "AB", hours, ws[coord].value, started, temperature))

    ws24 = wb["24 hours"]
    duplicate_check = {}
    duplicate_labels, duplicate_columns = DUPLICATE_48H
    for label, cell in duplicate_labels.items():
        if ws24[cell].value != label:
            raise SystemExit(f"24 hours!{cell} reads {ws24[cell].value!r}, expected {label!r}")
        copy = [v for _, v in _typed_values(ws24, cell, duplicate_columns)]
        used = [r[4] for r in rows if r[0] == "48 hours" and r[2] == label]
        if copy != used:
            raise SystemExit(f"48 h copies of {label} disagree: {copy} vs {used}")
        duplicate_check[label] = {"24 hours sheet copy": copy, "48 hours sheet (used)": used}

    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "source_sheet",
                "source_cell",
                "group_label",
                "culture_hours",
                "rfu",
                "read_started",
                "read_temperature_c",
            ]
        )
        w.writerows(rows)
    report = {
        "source_file": source.name,
        "source_md5": hashlib.md5(raw).hexdigest(),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "tidy_csv": out_csv.name,
        "tidy_csv_sha256": hashlib.sha256(out_csv.read_bytes()).hexdigest(),
        "rows": len(rows),
        "per_group": {
            f"{h} h {g}": sum(1 for r in rows if r[3] == h and r[2] == g)
            for (_, h) in SIDE_TABLES
            for g in ("TI-CTL", "TI-BMG", "POLY", "AB")
        },
        "duplicate_48h_check": duplicate_check,
        "not_read": "formula cells (author's means, SDs, '% Viability'); instrument header rows",
    }
    out_report.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
