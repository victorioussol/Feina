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
from feina_client.reconcile import review_day, verify_drive_readback  # noqa: E402
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
    book = Path(args.workbook) if args.workbook else client_root() / "workbooks" / "AFSA-Ingresos.xlsx"
    screen_count, screen_total = _screen_from_manifest(membr)
    reviewed = review_day(
        business_date=date.fromisoformat(business),
        membr=membr,
        paycomet=pay if pay and pay.is_file() else None,
        harlands=har if har and har.is_file() else None,
        workbook=book if book.is_file() else None,
        screen_count_text=screen_count,
        screen_total_text=screen_total,
    )
    payload = {
        "night": night,
        "model_calls": 0,
        "drive": "NOT_RUN",
    }
    payload.update(reviewed)
    save_night(payload)
    public = {
        "status": payload.get("status"),
        "outcome": payload.get("outcome"),
        "confirmed_write": payload.get("confirmed_write"),
        "figures_final": payload.get("figures_final"),
        "reason": payload.get("reason"),
        "phrase": payload.get("phrase"),
    }
    sys.stdout.write(json.dumps(public) + "\n")
    return 0 if payload.get("confirmed_write") else 2


def _screen_from_manifest(membr: Path) -> tuple[str | None, str | None]:
    manifest = membr.parent / "manifest.json"
    if not manifest.is_file():
        return None, None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, None
    for item in data.get("files") or []:
        if Path(str(item.get("path") or "")).name == membr.name:
            return item.get("screen_count_text"), item.get("screen_total_text")
    screen = data.get("screen") or {}
    return screen.get("count_text"), screen.get("total_text")


if __name__ == "__main__":
    raise SystemExit(main())
