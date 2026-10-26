"""Spreadsheet parsing, pairing, and workbook read-back."""

from __future__ import annotations

import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from feina_client.reconcile import (
    Line,
    lines_from_xlsx,
    reconcile_lines,
    verify_workbook,
    write_workbook,
)
from feina_client.xlsxio import read_xlsx, write_xlsx

DAY = date(2026, 10, 25)
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _line(source, amount, method, ref, status="", member="", when=DAY):
    return Line(source, when, Decimal(amount), method, ref, status, member)


def test_amount_and_header_aliases_from_fixture_workbooks(fixtures: Path):
    membr = lines_from_xlsx(fixtures / "membr.xlsx", "membr")
    pay = lines_from_xlsx(fixtures / "paycomet.xlsx", "paycomet")
    har = lines_from_xlsx(fixtures / "harlands.xlsx", "harlands")
    assert {row.ref: row.amount for row in membr}["M-EU"] == Decimal("1234.56")
    assert {row.ref: row.amount for row in pay}["P-US"] == Decimal("1234.56")
    assert any(row.member_ref == "SOC-9" for row in har)
    day = [row for row in membr if row.when == DAY]
    assert {row.kind() for row in day} >= {"card", "refund", "debit"}


def test_shared_string_fixture_reads_headers(fixtures: Path):
    sheets = read_xlsx(fixtures / "shared-strings.xlsx")
    assert sheets[0][0][:2] == ["Fecha", "Importe"]
    assert sheets[0][1][1] == "15.50"


def test_pairs_within_five_euros_and_flags_a_larger_gap():
    close = reconcile_lines(
        [_line("membr", "100.00", "visa", "M1")],
        [_line("paycomet", "104.00", "card", "P1")],
        None,
        business_date=DAY,
    )
    assert close.mismatches == []

    wide = reconcile_lines(
        [_line("membr", "100.00", "visa", "M1")],
        [_line("paycomet", "106.00", "card", "P1")],
        None,
        business_date=DAY,
    )
    kinds = {item.kind for item in wide.mismatches}
    assert "unmatched_membr_card" in kinds
    assert "unmatched_paycomet" in kinds
    assert "total_gap" in kinds


def test_refund_pairs_on_absolute_cents_and_does_not_open_a_gap():
    result = reconcile_lines(
        [_line("membr", "-10.00", "reembolso", "M2")],
        [_line("paycomet", "10.00", "card", "P2", status="Refund")],
        None,
        business_date=DAY,
    )
    assert result.mismatches == []


def test_failed_debit_is_kept_even_when_the_amount_matches():
    result = reconcile_lines(
        [_line("membr", "25.00", "domiciliacion", "M3", member="SOC-9")],
        None,
        [_line("harlands", "25.00", "direct debit", "H2", status="failed", member="SOC-9")],
        business_date=DAY,
    )
    assert [item.kind for item in result.mismatches] == ["failed_debit"]
    assert result.failed_debits[0].member_ref == "SOC-9"
    assert "member_ref" not in result.public_mismatches()[0]


def test_paid_word_suppresses_a_failed_status_word_only_when_it_is_alone():
    paid = reconcile_lines(
        [_line("membr", "40.00", "adeudo", "M")],
        None,
        [_line("harlands", "40.00", "sepa", "H", status="collected")],
        business_date=DAY,
    )
    assert paid.failed_debits == []
    failed = reconcile_lines(
        [],
        None,
        [_line("harlands", "40.00", "sepa", "H", status="unpaid")],
        business_date=DAY,
    )
    assert failed.failed_debits


def test_optional_sources_can_be_missing_required_ones_cannot():
    optional = reconcile_lines([], None, None, business_date=DAY)
    assert optional.mismatches == []
    required = reconcile_lines(
        [],
        None,
        None,
        business_date=DAY,
        paycomet_required=True,
        harlands_required=True,
    )
    assert {item.ref for item in required.mismatches} == {"paycomet", "harlands"}


def test_fixture_night_reconciles_and_readback_matches(fixtures: Path, tmp_path: Path):
    result = reconcile_lines(
        lines_from_xlsx(fixtures / "membr.xlsx", "membr"),
        lines_from_xlsx(fixtures / "paycomet.xlsx", "paycomet"),
        lines_from_xlsx(fixtures / "harlands.xlsx", "harlands"),
        business_date=DAY,
    )
    kinds = [item.kind for item in result.mismatches]
    assert kinds == ["failed_debit"]
    book = tmp_path / "AFSA-Ingresos.xlsx"
    written = write_workbook(
        book,
        night="2026-10-26",
        result=result,
        source_hashes={"membr_pos": "abc"},
    )
    assert written["confirmed_write"] is True
    readback = verify_workbook(book, night="2026-10-26", business_date="2026-10-25")
    assert readback["ok"] is True
    assert readback["confirmed"] == "yes"
    assert readback["membr_total"] == f"{result.membr_total:.2f}"

    other = reconcile_lines(
        [_line("membr", "1.00", "visa", "N", when=date(2026, 10, 26))],
        [_line("paycomet", "1.00", "card", "N", when=date(2026, 10, 26))],
        [],
        business_date=date(2026, 10, 26),
    )
    again = write_workbook(book, night="2026-10-27", result=other, source_hashes={"membr_pos": "def"})
    assert again["confirmed_write"] is True
    sheets = read_xlsx(book)
    dates = [row[1] for row in sheets[0][1:]]
    assert dates == ["2026-10-25", "2026-10-26"]
    kept = [row[0] for row in sheets[1][1:]]
    assert "2026-10-25" in kept


def test_tampered_workbook_fails_readback(fixtures: Path, tmp_path: Path):
    result = reconcile_lines(
        lines_from_xlsx(fixtures / "membr.xlsx", "membr"),
        lines_from_xlsx(fixtures / "paycomet.xlsx", "paycomet"),
        lines_from_xlsx(fixtures / "harlands.xlsx", "harlands"),
        business_date=DAY,
    )
    book = tmp_path / "AFSA-Ingresos.xlsx"
    write_workbook(book, night="2026-10-26", result=result, source_hashes={})
    sheets = read_xlsx(book)
    sheets[0][1][0] = "1999-01-01"
    write_xlsx(book, {"Resumen": sheets[0], "Descuadres": sheets[1], "Control": sheets[2]})
    readback = verify_workbook(book, night="2026-10-26", business_date="2026-10-25")
    assert readback["ok"] is False
    assert readback["reason"] == "readback_mismatch"


def test_unconfirmed_write_is_a_failed_night(client, monkeypatch, fixtures: Path):
    from feina_client.jobs import run_nightly

    monkeypatch.setattr(
        "feina_client.jobs.run_download",
        lambda cfg, **kwargs: _copy_manifest(kwargs["out_dir"], fixtures),
    )
    monkeypatch.setattr(
        "feina_client.jobs.write_workbook",
        lambda *args, **kwargs: {
            "confirmed_write": False,
            "workbook_sha256": "0" * 64,
            "readback": {"ok": False},
            "path": "x",
        },
    )
    cfg = {"pos_report_id": "pos_transactions", "sources": {}}
    result = run_nightly(
        cfg,
        now=_madrid(2026, 10, 26, 4, 5),
        session=object(),
        inbox=client / "inbox",
        workbook=client / "book.xlsx",
    )
    assert result["status"] == "FAILED"
    assert result["confirmed_write"] is False
    assert result["model_calls"] == 0


def _copy_manifest(out_dir: Path, fixtures: Path) -> dict:
    dest = Path(out_dir) / "membr-pos-2026-10-25.xlsx"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes((fixtures / "membr.xlsx").read_bytes())
    return {
        "status": "OK",
        "files": [{"report": "pos_transactions", "path": str(dest), "sha256": "abc", "bytes": dest.stat().st_size}],
    }


def _madrid(year, month, day, hour, minute):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Europe/Madrid"))


def test_shared_string_workbook_is_well_formed(fixtures: Path):
    with zipfile.ZipFile(fixtures / "shared-strings.xlsx") as zf:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    texts = ["".join((node.text or "") for node in si.iter(f"{{{NS}}}t")) for si in root]
    assert "Fecha" in texts
