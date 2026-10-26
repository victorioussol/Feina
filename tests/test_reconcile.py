"""Stop conditions for a downloaded day. Nothing here adjusts a platform figure."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from feina_client.approved import find_approved
from feina_client.proactive import compose_daily
from feina_client.reconcile import review_day
from feina_client.runtime import sha256_file
from feina_client.source_gate import inspect_table, inspect_xlsx, parse_amount
from feina_client.workbook_guard import apply_day_row, row_xml_map, sheet_xml, splice_row
from feina_client.xlsxio import read_xlsx, write_xlsx

DAY = date(2026, 10, 25)
HEADER = ["Fecha", "Importe", "Método de pago", "Recibo", "Estado"]
MADRID = ZoneInfo("Europe/Madrid")


def _source(path: Path, rows: list[tuple], when: str = "2026-10-25") -> None:
    table = [HEADER]
    for ref, amount, method, status in rows:
        table.append([when, amount, method, ref, status])
    write_xlsx(path, {"POS": table})


def _screen(rows: list[tuple]) -> tuple[str, str]:
    total = sum((parse_amount(amount) or Decimal("0")) for _ref, amount, _method, _status in rows)
    return str(len(rows)), f"{total:.2f}"


def _book(path: Path, row_number: int, current: list[str]) -> dict[int, str]:
    rows = [["day", "a", "b", "c", "d", "e", "note", "H"]]
    while len(rows) < row_number - 1:
        kept = f"keep-{len(rows)}"
        rows.append([kept, "1.00", "1.00", "0.00", "0", "keep", "keep", "H"])
    rows.append(current)
    write_xlsx(path, {"AFSA": rows})
    return row_xml_map(sheet_xml(path))


def _approved(monkeypatch, fixtures: Path, payload: dict, mode: str = "splice") -> None:
    monkeypatch.setenv("FEINA_AFSA_CHECKS", str(fixtures / "approved" / "afsa_checks.py"))
    monkeypatch.setenv("FEINA_UPDATE_WORKBOOK", str(fixtures / "approved" / "update_workbook.py"))
    monkeypatch.setenv("FEINA_TEST_CHECKS_JSON", json.dumps(payload))
    monkeypatch.setenv("FEINA_TEST_UPDATE", mode)


def _hide_column_h(path: Path) -> None:
    import zipfile

    from feina_client.workbook_guard import _sheet_name

    with zipfile.ZipFile(path) as zf:
        name = _sheet_name(zf)
        xml = zf.read(name).decode("utf-8")
        payload = {item: zf.read(item) for item in zf.namelist() if item != name}
    xml = xml.replace(
        "<sheetData>",
        '<cols><col min="8" max="8" hidden="1"/></cols><sheetData>',
        1,
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item, data in payload.items():
            zf.writestr(item, data)
        zf.writestr(name, xml.encode("utf-8"))


def test_approved_scripts_are_not_shipped_in_this_repository():
    root = Path(__file__).resolve().parents[1]
    shipped = []
    for name in ("afsa_checks.py", "update_workbook.py", "af-ingresos-daily.md"):
        for path in root.rglob(name):
            if "tests/fixtures" in str(path):
                continue
            shipped.append(path)
    skill = [path for path in root.rglob("*") if path.name == "membr-card-reconciliation"]
    assert shipped == []
    assert skill == []


def test_unrecognized_headers_stop_and_do_not_return_an_empty_list(fixtures: Path):
    gate = inspect_xlsx(fixtures / "shared-strings.xlsx", business_date=DAY)
    assert gate.status == "SOURCE_FORMAT_CHANGED"
    assert gate.rows is None
    assert gate.rows != []
    assert "ref" in gate.reason and "method" in gate.reason and "status" in gate.reason
    blank = inspect_table(
        [["Not a date", "Something else"]],
        business_date=DAY,
        require_screen=True,
        screen_count_text="0",
        screen_total_text="0",
    )
    assert blank.status == "SOURCE_FORMAT_CHANGED"
    assert blank.rows is None


def test_unparsed_date_or_amount_stops_and_counts_every_bad_row(tmp_path: Path):
    path = tmp_path / "bad.xlsx"
    write_xlsx(
        path,
        {
            "POS": [
                HEADER,
                ["2026-10-25", "10.00", "visa", "OK", "paid"],
                ["yesterday", "10.00", "visa", "BAD-DATE", "paid"],
                ["2026-10-25", "nope", "visa", "BAD-AMOUNT", "paid"],
                ["2026-10-25", "3.00", "visa", "", "paid"],
            ]
        },
    )
    gate = inspect_xlsx(path, business_date=DAY, screen_count_text="1", screen_total_text="10.00", require_screen=True)
    assert gate.status == "PARSE_FAILED"
    assert gate.reason == "unparsed_rows"
    assert gate.unparsed_count == 3
    assert gate.rows is None


def test_empty_zero_and_wrong_range_are_not_a_confirmed_zero_day(tmp_path: Path, fixtures: Path, client):
    empty = tmp_path / "empty.xlsx"
    empty.write_bytes(b"")
    zero = tmp_path / "zero.xlsx"
    write_xlsx(zero, {"POS": [HEADER]})
    other = tmp_path / "other.xlsx"
    _source(other, [("M1", "10.00", "visa", "paid")], when="2026-10-24")
    book = client / "AFSA-Ingresos.xlsx"
    _book(book, 2, ["2026-10-25", "", "", "", "", "", "", "H"])
    before = sha256_file(book)

    for path, reason in ((empty, "empty_file"), (zero, "zero_rows"), (other, "date_range")):
        gate = inspect_xlsx(path, business_date=DAY, require_screen=True)
        assert gate.status == "NEEDS_CONFIRMATION"
        assert gate.reason == reason
        assert gate.rows is None
        reviewed = review_day(
            business_date=DAY,
            membr=path,
            paycomet=None,
            harlands=None,
            workbook=book,
            screen_count_text="0",
            screen_total_text="0.00",
        )
        assert reviewed["status"] == "NEEDS_CONFIRMATION"
        assert reviewed["figures_final"] is False
        assert reviewed["confirmed_write"] is False
        assert reviewed["items"] == []
        assert sha256_file(book) == before
        message = compose_daily("fr", reviewed, when_clean=True)
        assert "définitif" in message
        assert "0.00" not in message
        assert "10.00" not in message

    ranged = inspect_xlsx(fixtures / "membr.xlsx", business_date=DAY)
    assert ranged.status == "NEEDS_CONFIRMATION"
    assert ranged.reason == "date_range"
    assert ranged.rows is None


def test_screen_count_and_total_must_match_exactly_with_no_tolerance(tmp_path: Path):
    path = tmp_path / "membr.xlsx"
    rows = [("M1", "100.00", "visa", "paid"), ("M2", "0.01", "card", "paid")]
    _source(path, rows)
    count, total = _screen(rows)
    assert inspect_xlsx(
        path,
        business_date=DAY,
        screen_count_text=f"Rows: {count}",
        screen_total_text=f"Total {total} €",
        require_screen=True,
    ).status == "OK"
    short = inspect_xlsx(
        path,
        business_date=DAY,
        screen_count_text="Rows: 1",
        screen_total_text=f"Total {total} €",
        require_screen=True,
    )
    assert short.status == "SCREEN_MISMATCH" and short.reason == "screen_count" and short.rows is None
    off_by_one_cent = inspect_xlsx(
        path,
        business_date=DAY,
        screen_count_text=f"Rows: {count}",
        screen_total_text="Total 100.00 €",
        require_screen=True,
    )
    assert off_by_one_cent.status == "SCREEN_MISMATCH"
    assert off_by_one_cent.reason == "screen_total"
    assert off_by_one_cent.rows is None
    missing = inspect_xlsx(path, business_date=DAY, require_screen=True)
    assert missing.status == "NEEDS_CONFIRMATION" and missing.reason == "screen_not_captured"


def test_each_source_reports_its_check_state_and_membr_only_is_not_clean(tmp_path: Path, client):
    membr = tmp_path / "membr.xlsx"
    pay = tmp_path / "pay.xlsx"
    rows = [("M1", "10.00", "visa", "paid")]
    _source(membr, rows)
    _source(pay, [("P1", "10.00", "card", "paid")])
    count, total = _screen(rows)
    book = client / "AFSA-Ingresos.xlsx"
    _book(book, 2, ["old"] * 8)
    before = sha256_file(book)
    only = review_day(
        business_date=DAY,
        membr=membr,
        paycomet=None,
        harlands=None,
        workbook=book,
        screen_count_text=count,
        screen_total_text=total,
    )
    assert only["phrase"] == "Membr only, not cross-checked"
    assert only["outcome"] == "unverified"
    assert only["figures_final"] is False
    assert only["sources_state"] == {"membr": "checked", "paycomet": "not_checked", "harlands": "not_checked"}
    assert sha256_file(book) == before
    message = compose_daily("fr", only, when_clean=True)
    assert "pas de contrôle croisé" in message
    assert "10.00" not in message

    partial = review_day(
        business_date=DAY,
        membr=membr,
        paycomet=pay,
        harlands=tmp_path / "missing-harlands.xlsx",
        workbook=book,
        screen_count_text=count,
        screen_total_text=total,
    )
    assert partial["phrase"] == "Membr only, not cross-checked"
    assert partial["sources_state"]["paycomet"] == "checked"
    assert partial["sources_state"]["harlands"] == "not_checked"

    broken = tmp_path / "broken.xlsx"
    write_xlsx(broken, {"POS": [["Fecha"], ["2026-10-25"]]})
    mismatched = review_day(
        business_date=DAY,
        membr=broken,
        paycomet=pay,
        harlands=pay,
        workbook=book,
    )
    assert mismatched["status"] == "SOURCE_FORMAT_CHANGED"
    assert mismatched["sources_state"]["membr"] == "mismatch"
    assert mismatched["figures_final"] is False


def test_unclassified_and_duplicate_receipts_are_listed_and_not_written(tmp_path: Path, client, monkeypatch, fixtures: Path):
    membr = tmp_path / "membr.xlsx"
    pay = tmp_path / "pay.xlsx"
    har = tmp_path / "har.xlsx"
    membr_rows = [
        ("M1", "10.00", "visa", "paid"),
        ("M1", "10.00", "visa", "paid"),
        ("CASH", "5.00", "efectivo", "paid"),
        ("NEG", "-2.00", "cash", "paid"),
    ]
    _source(membr, membr_rows)
    _source(pay, [("P1", "10.00", "card", "paid")])
    _source(har, [("H1", "40.00", "domiciliacion", "paid")])
    count, total = _screen(membr_rows)
    book = client / "AFSA-Ingresos.xlsx"
    _book(book, 2, ["old"] * 8)
    before = sha256_file(book)
    _approved(
        monkeypatch,
        fixtures,
        {"status": "match", "row_number": 2, "row": ["2026-10-25", "1", "1", "0", "0", "ok", "n", "H"], "items": []},
    )
    reviewed = review_day(
        business_date=DAY,
        membr=membr,
        paycomet=pay,
        harlands=har,
        workbook=book,
        screen_count_text=count,
        screen_total_text=total,
    )
    assert reviewed["status"] == "NEEDS_CONFIRMATION"
    assert reviewed["reason"] == "duplicate_ref"
    assert reviewed["figures_final"] is False
    assert reviewed["confirmed_write"] is False
    assert "membr:M1" in reviewed["review_refs"]
    assert "membr:CASH" in reviewed["review_refs"]
    assert "membr:NEG" in reviewed["review_refs"]
    assert reviewed["sources_state"]["membr"] == "mismatch"
    assert sha256_file(book) == before
    assert find_approved()["checks"].name == "afsa_checks.py"
    message = compose_daily("fr", reviewed, when_clean=True)
    assert "10.00" not in message and "5.00" not in message

    cash_only = tmp_path / "cash.xlsx"
    cash_rows = [("CASH", "5.00", "efectivo", "paid"), ("CARD", "5.00", "tarjeta", "paid")]
    _source(cash_only, cash_rows)
    count, total = _screen(cash_rows)
    listed = review_day(
        business_date=DAY,
        membr=cash_only,
        paycomet=pay,
        harlands=har,
        workbook=book,
        screen_count_text=count,
        screen_total_text=total,
    )
    assert listed["reason"] == "unclassified"
    assert listed["review_refs"] == ["membr:CASH"]
    assert listed["figures_final"] is False


def test_matching_day_writes_only_the_target_row_and_reads_it_back(tmp_path: Path, client, monkeypatch, fixtures: Path):
    membr, pay, har = tmp_path / "m.xlsx", tmp_path / "p.xlsx", tmp_path / "h.xlsx"
    _source(membr, [("M1", "12.50", "visa", "paid")])
    _source(pay, [("P1", "12.50", "card", "paid")])
    _source(har, [("H1", "40.00", "adeudo", "collected")])
    book = client / "AFSA-Ingresos.xlsx"
    before_rows = _book(book, 3, ["2026-10-25", "0", "0", "0", "0", "old", "old", "H"])
    before_hash = sha256_file(book)
    cells = ["2026-10-25", "12.50", "12.50", "40.00", "0", "ok", "note", "VISIBLE"]
    _approved(
        monkeypatch,
        fixtures,
        {"status": "match", "row_number": 3, "row": cells, "items": []},
    )
    reviewed = review_day(
        business_date=DAY,
        membr=membr,
        paycomet=pay,
        harlands=har,
        workbook=book,
        screen_count_text="1",
        screen_total_text="12.50",
    )
    assert reviewed["status"] == "CONFIRMED"
    assert reviewed["outcome"] == "verified_match"
    assert reviewed["figures_final"] is True
    assert reviewed["tolerance"] is None
    assert reviewed["readback"]["cells"] == cells
    assert read_xlsx(book)[0][2][:8] == cells
    after_rows = row_xml_map(sheet_xml(book))
    for number, xml in before_rows.items():
        if number == 3:
            assert after_rows[number] != xml
        else:
            assert after_rows[number] == xml
    backup = Path(reviewed["backup"])
    assert sha256_file(backup) == before_hash == reviewed["backup_sha256"]
    sidecar = backup.with_suffix(backup.suffix + ".sha256")
    assert sidecar.read_text(encoding="utf-8").startswith(before_hash)
    message = compose_daily("fr", reviewed, when_clean=True)
    assert "Vérifié" in message and "AFSA Ingresos" in message


def test_disagreement_is_reported_as_coaching_and_a_failed_write_restores(tmp_path, client, monkeypatch, fixtures: Path):
    membr, pay, har = tmp_path / "m.xlsx", tmp_path / "p.xlsx", tmp_path / "h.xlsx"
    _source(membr, [("M1", "12.00", "visa", "paid")])
    _source(pay, [("P1", "10.00", "card", "paid")])
    _source(har, [("H1", "40.00", "sepa", "collected")])
    book = client / "AFSA-Ingresos.xlsx"
    cells = ["2026-10-25", "12.00", "10.00", "40.00", "1", "check", "note", "H"]
    _book(book, 3, ["old"] * 8)
    _approved(
        monkeypatch,
        fixtures,
        {
            "status": "disagree",
            "row_number": 3,
            "row": cells,
            "items": [
                {
                    "receipt": "M1",
                    "membr": "12.00",
                    "paycomet": "10.00",
                    "harlands": "40.00",
                    "check": "Look up receipt M1 in Membr or Paycomet.",
                }
            ],
        },
    )
    reviewed = review_day(
        business_date=DAY,
        membr=membr,
        paycomet=pay,
        harlands=har,
        workbook=book,
        screen_count_text="1",
        screen_total_text="12.00",
    )
    assert reviewed["outcome"] == "verified_disagree"
    assert reviewed["figures_final"] is True
    assert reviewed["items"][0]["membr"] == "12.00"
    assert reviewed["items"][0]["paycomet"] == "10.00"
    message = compose_daily("fr", reviewed, when_clean=True)
    assert "12.00" in message and "10.00" in message
    assert "Look up receipt M1" in message
    assert "écart" in message

    before = sha256_file(book)
    monkeypatch.setenv("FEINA_TEST_UPDATE", "rewrite")
    failed = review_day(
        business_date=DAY,
        membr=membr,
        paycomet=pay,
        harlands=har,
        workbook=book,
        screen_count_text="1",
        screen_total_text="12.00",
    )
    assert failed["status"] == "FAILED"
    assert failed["outcome"] == "unverified"
    assert failed["figures_final"] is False
    assert failed["items"] == []
    assert failed["reason"] == "other_rows_changed"
    assert sha256_file(book) == before
    quiet = compose_daily("fr", failed, when_clean=True)
    assert "12.00" not in quiet
    assert "définitif" in quiet


def test_write_guards_refuse_a_short_row_a_hidden_column_h_and_a_missing_workbook(tmp_path: Path, client, monkeypatch, fixtures: Path):
    membr, pay, har = tmp_path / "m.xlsx", tmp_path / "p.xlsx", tmp_path / "h.xlsx"
    _source(membr, [("M1", "10.00", "visa", "paid")])
    _source(pay, [("P1", "10.00", "card", "paid")])
    _source(har, [("H1", "10.00", "sepa", "paid")])
    book = client / "AFSA-Ingresos.xlsx"
    _book(book, 2, ["2026-10-25", "0", "0", "0", "0", "old", "old", "H"])
    before = sha256_file(book)
    _approved(
        monkeypatch,
        fixtures,
        {"status": "match", "row_number": 2, "row": ["only", "seven", "cells", "here", "no", "column", "h"], "items": []},
    )
    short = review_day(
        business_date=DAY,
        membr=membr,
        paycomet=pay,
        harlands=har,
        workbook=book,
        screen_count_text="1",
        screen_total_text="10.00",
    )
    assert short["confirmed_write"] is False
    assert short["reason"] == "column_h_missing"
    assert short["figures_final"] is False
    assert sha256_file(book) == before

    _hide_column_h(book)
    hidden_before = sha256_file(book)
    _approved(
        monkeypatch,
        fixtures,
        {"status": "match", "row_number": 2, "row": ["2026-10-25", "10", "10", "10", "0", "ok", "n", "H"], "items": []},
    )
    hidden = review_day(
        business_date=DAY,
        membr=membr,
        paycomet=pay,
        harlands=har,
        workbook=book,
        screen_count_text="1",
        screen_total_text="10.00",
    )
    assert hidden["reason"] == "column_h_hidden"
    assert sha256_file(book) == hidden_before

    missing = client / "does-not-exist.xlsx"
    absent = review_day(
        business_date=DAY,
        membr=membr,
        paycomet=pay,
        harlands=har,
        workbook=missing,
        screen_count_text="1",
        screen_total_text="10.00",
    )
    assert absent["status"] == "NEEDS_CONFIRMATION"
    assert absent["reason"] == "workbook_missing"
    assert absent["figures_final"] is False
    assert not missing.exists()

    fresh = client / "fresh.xlsx"
    _book(fresh, 2, ["2026-10-25", "0", "0", "0", "0", "old", "old", "H"])
    original = read_xlsx(fresh)
    called = {"n": 0}

    def writer():
        called["n"] += 1
        splice_row(fresh, 2, ["nope"] * 8)

    refused = apply_day_row(fresh, row_number=9, cells=["2026-10-25", "1", "1", "1", "0", "ok", "n", "H"], writer=writer)
    assert refused["reason"] == "row_missing"
    assert called["n"] == 0
    assert read_xlsx(fresh) == original

    def hide_after():
        splice_row(fresh, 2, ["2026-10-25", "1", "1", "1", "0", "ok", "n", "H"])
        _hide_column_h(fresh)

    digest = sha256_file(fresh)
    restored = apply_day_row(
        fresh,
        row_number=2,
        cells=["2026-10-25", "1", "1", "1", "0", "ok", "n", "H"],
        writer=hide_after,
    )
    assert restored["reason"] == "column_h_hidden"
    assert sha256_file(fresh) == digest

    def wrong_cells():
        splice_row(fresh, 2, ["WRONG"] * 8)

    mismatch = apply_day_row(
        fresh,
        row_number=2,
        cells=["2026-10-25", "1", "1", "1", "0", "ok", "n", "H"],
        writer=wrong_cells,
    )
    assert mismatch["reason"] == "readback_mismatch"
    assert sha256_file(fresh) == digest
    assert read_xlsx(fresh) == original


def test_missing_approved_scripts_leave_the_workbook_untouched(tmp_path: Path, client, monkeypatch):
    monkeypatch.setenv("FEINA_AFSA_CHECKS", str(tmp_path / "no-checks.py"))
    monkeypatch.setenv("FEINA_UPDATE_WORKBOOK", str(tmp_path / "no-update.py"))
    assert find_approved() is None
    membr, pay, har = tmp_path / "m.xlsx", tmp_path / "p.xlsx", tmp_path / "h.xlsx"
    _source(membr, [("M1", "10.00", "visa", "paid")])
    _source(pay, [("P1", "10.00", "card", "paid")])
    _source(har, [("H1", "10.00", "sepa", "paid")])
    book = client / "AFSA-Ingresos.xlsx"
    _book(book, 2, ["old"] * 8)
    before = sha256_file(book)
    reviewed = review_day(
        business_date=DAY,
        membr=membr,
        paycomet=pay,
        harlands=har,
        workbook=book,
        screen_count_text="1",
        screen_total_text="10.00",
    )
    assert reviewed["status"] == "CHECKS_UNAVAILABLE"
    assert reviewed["outcome"] == "unverified"
    assert reviewed["figures_final"] is False
    assert reviewed["tolerance"] is None
    assert sha256_file(book) == before
    message = compose_daily("fr", reviewed, when_clean=True)
    assert "définitif" in message
    assert "10.00" not in message


def test_unconfirmed_night_is_failed_and_makes_no_model_calls(client, monkeypatch, fixtures: Path, tmp_path: Path):
    from feina_client.jobs import run_nightly

    business = "2026-10-25"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    membr = run_dir / "membr.xlsx"
    _source(membr, [("M1", "10.00", "visa", "paid")])
    inbox = client / "inbox"
    inbox.mkdir()
    _source(inbox / f"paycomet-{business}.xlsx", [("P1", "10.00", "card", "paid")])
    _source(inbox / f"harlands-{business}.xlsx", [("H1", "10.00", "sepa", "paid")])
    book = client / "AFSA-Ingresos.xlsx"
    _book(book, 3, ["old"] * 8)
    before = sha256_file(book)

    def fake_download(cfg, **kwargs):
        dest = Path(kwargs["out_dir"]) / "membr-pos-2026-10-25.xlsx"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(membr.read_bytes())
        return {
            "status": "OK",
            "files": [
                {
                    "report": "pos_transactions",
                    "path": str(dest),
                    "sha256": "abc",
                    "bytes": dest.stat().st_size,
                    "screen_count_text": "1",
                    "screen_total_text": "10.00",
                }
            ],
        }

    monkeypatch.setattr("feina_client.jobs.run_download", fake_download)
    _approved(
        monkeypatch,
        fixtures,
        {
            "status": "match",
            "row_number": 3,
            "row": ["2026-10-25", "10.00", "10.00", "10.00", "0", "ok", "n", "H"],
            "items": [],
        },
        mode="rewrite",
    )
    result = run_nightly(
        {"pos_report_id": "pos_transactions", "sources": {}},
        now=datetime(2026, 10, 26, 4, 5, tzinfo=MADRID),
        session=object(),
        inbox=inbox,
        workbook=book,
    )
    assert result["status"] == "FAILED"
    assert result["confirmed_write"] is False
    assert result["figures_final"] is False
    assert result["model_calls"] == 0
    assert sha256_file(book) == before
