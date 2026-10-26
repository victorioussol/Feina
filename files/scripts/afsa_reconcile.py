#!/usr/bin/env python3
"""Reconcile files already on disk and verify the workbook by reading it back.

The nightly job calls the library directly. This entrypoint is what the agent
runs after membr_download.py, so the model does not parse the spreadsheets.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feina_client.cliutil import enabled, resolve_business_date  # noqa: E402
from feina_client.jobs import save_night  # noqa: E402
from feina_client.reconcile import lines_from_xlsx, reconcile_lines, verify_drive_readback, write_workbook  # noqa: E402
from feina_client.runtime import client_root, madrid_now, sha256_file  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Reconcile AFSA inputs and verify the workbook")
    parser.add_argument("--date", default="yesterday")
    parser.add_argument("--membr", required=False)
    parser.add_argument("--paycomet", default="")
    parser.add_argument("--harlands", default="")
    parser.add_argument("--workbook", default="")
    parser.add_argument("--verify-drive", default="")
    args = parser.parse_args(argv)
    if not enabled("afsa-ingresos"):
        return 0
    business = resolve_business_date(args.date)
    night = (date.fromisoformat(business) + timedelta(days=1)).isoformat()
    if args.verify_drive:
        meta = json.loads(Path(args.verify_drive).read_text(encoding="utf-8"))
        book = Path(args.workbook) if args.workbook else client_root() / "workbooks" / "AFSA-Ingresos.xlsx"
        ok, reason = verify_drive_readback(meta, local_sha=sha256_file(book), madrid_day=madrid_now().date())
        sys.stdout.write(json.dumps({"drive_ok": ok, "reason": reason}) + "\n")
        return 0 if ok else 2
    if not args.membr:
        sys.stderr.write("membr xlsx required\n")
        return 2
    membr = Path(args.membr)
    pay = Path(args.paycomet) if args.paycomet else None
    har = Path(args.harlands) if args.harlands else None
    result = reconcile_lines(
        lines_from_xlsx(membr, "membr"),
        lines_from_xlsx(pay, "paycomet") if pay and pay.is_file() else None,
        lines_from_xlsx(har, "harlands") if har and har.is_file() else None,
        business_date=date.fromisoformat(business),
    )
    book = Path(args.workbook) if args.workbook else client_root() / "workbooks" / "AFSA-Ingresos.xlsx"
    hashes = {"membr_pos": sha256_file(membr)}
    written = write_workbook(book, night=night, result=result, source_hashes=hashes)
    status = "CONFIRMED" if written["confirmed_write"] else "FAILED"
    payload = {
        "night": night,
        "business_date": business,
        "status": status,
        "confirmed_write": written["confirmed_write"],
        "workbook": written["path"],
        "workbook_sha256": written["workbook_sha256"],
        "readback": written["readback"],
        "mismatches": result.public_mismatches(),
        "failed_debits": [item.as_dict() for item in result.failed_debits],
        "model_calls": 0,
        "drive": "NOT_RUN",
        "sources": hashes,
    }
    save_night(payload)
    sys.stdout.write(json.dumps({"status": status, "confirmed_write": written["confirmed_write"]}) + "\n")
    return 0 if written["confirmed_write"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
