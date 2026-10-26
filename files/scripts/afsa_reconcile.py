#!/usr/bin/env python3
"""Run the approved AFSA checks on files already on disk.

The nightly job calls the library directly. This entrypoint is what the agent
runs after membr_download.py. Harlands is not an argument: it is not an input
of the daily AFSA row.
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

    parser = argparse.ArgumentParser(description="Run the approved AFSA checks and stage the workbook")
    parser.add_argument("--date", default="yesterday")
    parser.add_argument("--membr", default="")
    parser.add_argument("--pdf", action="append", default=[])
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--payload", default="")
    parser.add_argument("--workbook", default="")
    parser.add_argument("--since", default="")
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
    membr = Path(args.membr) if args.membr else None
    screen_count, screen_total = _screen_from_manifest(membr) if membr else (None, None)
    book = Path(args.workbook) if args.workbook else client_root() / "workbooks" / "AFSA-Ingresos.xlsx"
    payload = Path(args.payload) if args.payload else None
    reviewed = review_day(
        business_date=date.fromisoformat(business),
        membr=membr if membr and membr.is_file() else None,
        pdfs=[Path(item) for item in args.pdf],
        evidence=[Path(item) for item in args.evidence],
        payload_path=payload if payload and payload.is_file() else None,
        workbook=book if book.is_file() else None,
        screen_count_text=screen_count,
        screen_total_text=screen_total,
        since=args.since or None,
    )
    payload_out = {"night": night, "model_calls": 0, "drive": "NOT_RUN"}
    payload_out.update(reviewed)
    save_night(payload_out)
    public = {
        "status": payload_out.get("status"),
        "outcome": payload_out.get("outcome"),
        "confirmed_write": payload_out.get("confirmed_write"),
        "figures_final": payload_out.get("figures_final"),
        "reason": payload_out.get("reason"),
        "phrase": payload_out.get("phrase"),
        "export_covered": payload_out.get("export_covered"),
    }
    sys.stdout.write(json.dumps(public) + "\n")
    return 0 if payload_out.get("figures_final") else 2


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
