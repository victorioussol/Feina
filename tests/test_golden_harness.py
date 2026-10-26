"""The golden harness waits for a hand-checked day. None is in this repository."""

from __future__ import annotations

from feina_client.golden import EXAMPLE_ONLY, compare_day, golden_dir, harness_report
from feina_client.xlsxio import write_xlsx


def test_repository_has_no_hand_checked_day():
    report = harness_report()
    assert report["supplied"] is False
    assert report["ok"] is False
    assert report["note"] == EXAMPLE_ONLY
    assert "20 Oct 2026" in report["note"]
    assert "294" in report["note"]
    assert list(golden_dir().glob("*.json")) == []


def test_compare_day_fails_until_the_supplied_cells_match(tmp_path):
    book = tmp_path / "AFSA-Ingresos.xlsx"
    cells = ["2026-10-20", "1.00", "1.00", "0.00", "0", "ok", "note", "H"]
    write_xlsx(book, {"AFSA": [["day", "a", "b", "c", "d", "e", "f", "H"], cells]})
    spec = {"date": "2026-10-20", "row_number": 2, "cells": cells}
    assert compare_day(book, spec)["ok"] is True
    spec["cells"] = ["2026-10-20", "9.99", "1.00", "0.00", "0", "ok", "note", "H"]
    mismatch = compare_day(book, spec)
    assert mismatch["supplied"] is True
    assert mismatch["ok"] is False
    assert mismatch["reason"] == "mismatch"
    supplied = tmp_path / "golden"
    supplied.mkdir()
    spec["cells"] = cells
    (supplied / "2026-10-20.json").write_text(__import__("json").dumps(spec), encoding="utf-8")
    report = harness_report(supplied, book)
    assert report["supplied"] is True
    assert report["ok"] is True
    assert report["days"][0]["row_number"] == 2
