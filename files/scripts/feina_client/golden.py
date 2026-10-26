"""Compare one workbook row with a hand-checked day, when one is supplied.

This repository does not contain expected cells for a past AFSA day.
"20 Oct 2026 = workbook row 294" is an example of the layout (one row per
business day, with column H still present). It is not a stored result.
"""

from __future__ import annotations

import json
from pathlib import Path

from .workbook_guard import column_h_hidden, read_row_cells, sheet_xml

EXAMPLE_ONLY = (
    "No hand-checked day is supplied in this repository. "
    "20 Oct 2026 = workbook row 294 is an example of the one-row-per-day layout, "
    "not an expected value."
)


def golden_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "golden"


def supplied_days(directory: Path | None = None) -> list[dict]:
    directory = directory or golden_dir()
    if not directory.is_dir():
        return []
    days = []
    for path in sorted(directory.glob("*.json")):
        days.append(json.loads(path.read_text(encoding="utf-8")))
    return days


def compare_day(workbook: Path, spec: dict) -> dict:
    """Cell-by-cell compare. A later hand-checked JSON can call this unchanged."""
    row_number = int(spec["row_number"])
    expected = [str(cell) for cell in spec.get("cells") or []]
    found = read_row_cells(workbook, row_number)
    hidden = column_h_hidden(sheet_xml(workbook)) if workbook.is_file() else True
    ok = (
        found is not None
        and len(expected) >= 8
        and found[: len(expected)] == expected
        and len(found) >= 8
        and found[7] == expected[7]
        and not hidden
    )
    return {
        "supplied": True,
        "ok": ok,
        "date": spec.get("date"),
        "row_number": row_number,
        "reason": "ok" if ok else "mismatch",
    }


def harness_report(directory: Path | None = None, workbook: Path | None = None) -> dict:
    days = supplied_days(directory)
    if not days:
        return {"supplied": False, "ok": False, "note": EXAMPLE_ONLY, "days": []}
    if workbook is None or not workbook.is_file():
        return {"supplied": True, "ok": False, "note": "workbook missing", "days": []}
    results = [compare_day(workbook, spec) for spec in days]
    return {
        "supplied": True,
        "ok": all(item["ok"] for item in results),
        "note": "",
        "days": results,
    }
