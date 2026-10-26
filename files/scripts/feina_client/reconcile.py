"""Run the approved AFSA checks, then stage one workbook row.

Harlands is not an input of this daily row. There is no tolerance: the
approved scripts match dates and cents exactly. This module does not change
a platform figure and does not invent a payment total. `dates` checks PDF
dates only. The payment total has to already be in daily-payload.json.

`afsa_checks.py final` is the only step that marks a day verified. A staged
row is not a final figure.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .approved import find_approved, run_dates, run_export, run_final, run_gaps, run_update
from .runtime import backup_file, client_root, sha256_file

OUTCOME_MATCH = "verified_match"
OUTCOME_DISAGREE = "verified_disagree"
OUTCOME_UNVERIFIED = "unverified"


def verify_drive_readback(meta: dict, *, local_sha: str, madrid_day: date) -> tuple[bool, str]:
    """Check a Drive metadata dict the agent saved after uploading the workbook.

    This does not mark the day verified. `afsa_checks.py final` does that,
    and only after last-success.json exists at the path that script reads.
    """
    remote = str(meta.get("sha256") or meta.get("md5Checksum") or "")
    if meta.get("sha256") and remote != local_sha:
        return False, "hash_mismatch"
    modified = meta.get("modifiedTime")
    if not modified:
        return False, "not_today"
    when = datetime.fromisoformat(str(modified).replace("Z", "+00:00"))
    from .runtime import MADRID

    if when.astimezone(MADRID).date() != madrid_day:
        return False, "not_today"
    size = meta.get("size")
    if size is not None and int(size) <= 0:
        return False, "empty"
    return True, "ok"


def _unverified(business: str, reason: str, **extra) -> dict:
    payload = {
        "business_date": business,
        "status": extra.pop("status", "NEEDS_CONFIRMATION"),
        "reason": reason,
        "outcome": OUTCOME_UNVERIFIED,
        "figures_final": False,
        "confirmed_write": False,
        "tolerance": None,
        "export_covered": extra.pop("export_covered", False),
        "items": [],
        "phrase": extra.pop("phrase", ""),
        "problems": extra.pop("problems", []),
    }
    payload.update(extra)
    return payload


def _money_equal(left: object, right: object) -> bool:
    try:
        return Decimal(str(left)).quantize(Decimal("0.01")) == Decimal(str(right)).quantize(Decimal("0.01"))
    except Exception:
        return False


def review_day(
    *,
    business_date: date,
    membr: Path | None,
    pdfs: list[Path] | None,
    workbook: Path | None,
    evidence: list[Path] | None = None,
    payload_path: Path | None = None,
    screen_count_text: str | None = None,
    screen_total_text: str | None = None,
    since: str | None = None,
    slack_on_fail: bool = True,
) -> dict:
    """export, dates, update_workbook, final, gaps. Stop on the first failed check."""
    business = business_date.isoformat()
    screen = {
        "count_text": screen_count_text,
        "total_text": screen_total_text,
        "captured": bool(screen_count_text or screen_total_text),
    }
    found = find_approved()
    if not found or not found.get("ok"):
        return _unverified(
            business,
            "checks_unavailable",
            status="CHECKS_UNAVAILABLE",
            screen=screen,
            mismatched=(found or {}).get("mismatched") or [],
        )
    checks = found["checks"]
    pdfs = [path for path in (pdfs or []) if path.is_file()]
    evidence = [path for path in (evidence or []) if path.is_file()]
    export_covered = bool(membr and membr.is_file() and membr.stat().st_size > 0)
    export = None
    if export_covered:
        export = run_export(checks, business_date=business, xlsx=membr, slack_on_fail=slack_on_fail)
        if export.get("result") != "PASS":
            return _unverified(
                business,
                "export",
                status="CHECK_FAIL",
                export_covered=True,
                problems=list(export.get("problems") or []),
                screen=screen,
                checks={"export": export},
            )
    elif payload_path is None or not payload_path.is_file():
        return _unverified(
            business,
            "membr_export_missing",
            status="NEEDS_CONFIRMATION",
            export_covered=False,
            screen=screen,
        )
    if not pdfs and not evidence:
        return _unverified(
            business,
            "payment_reports_missing",
            status="NEEDS_CONFIRMATION",
            export_covered=export_covered,
            screen=screen,
            checks={"export": export} if export else {},
        )
    dates = run_dates(
        checks,
        business_date=business,
        pdfs=pdfs,
        evidence=evidence,
        slack_on_fail=slack_on_fail,
    )
    if dates.get("result") != "PASS":
        return _unverified(
            business,
            "dates",
            status="CHECK_FAIL",
            export_covered=export_covered,
            problems=list(dates.get("problems") or []),
            screen=screen,
            checks={"export": export, "dates": dates},
        )
    if payload_path is None or not payload_path.is_file():
        return _unverified(
            business,
            "payment_total_not_in_dates_check",
            status="NEEDS_CONFIRMATION",
            export_covered=export_covered,
            screen=screen,
            checks={"export": export, "dates": dates},
        )
    payload = json_load(payload_path)
    if export is not None:
        for key in ("pos_total_net", "pos_card", "pos_noncard_net"):
            if not _money_equal(payload.get(key), export.get(key)):
                return _unverified(
                    business,
                    "payload_does_not_match_export",
                    status="CHECK_FAIL",
                    export_covered=True,
                    screen=screen,
                    checks={"export": export, "dates": dates},
                )
    if workbook is None or not workbook.is_file():
        return _unverified(
            business,
            "workbook_missing",
            status="NEEDS_CONFIRMATION",
            export_covered=export_covered,
            screen=screen,
            checks={"export": export, "dates": dates},
        )
    before = sha256_file(workbook)
    backup = backup_file(workbook)
    staged = client_root() / "runs" / business / "staged-AFSA-Ingresos.xlsx"
    staged.parent.mkdir(parents=True, exist_ok=True)
    updated = run_update(found["update"], source=workbook, payload=payload_path, output=staged)
    if updated.get("returncode") != 0 or "row" not in updated:
        return _unverified(
            business,
            "update_failed",
            status="FAILED",
            export_covered=export_covered,
            screen=screen,
            backup=str(backup) if backup else "",
            backup_sha256=before,
            checks={"export": export, "dates": dates, "update": updated},
        )
    if sha256_file(workbook) != before:
        return _unverified(
            business,
            "source_workbook_changed",
            status="FAILED",
            export_covered=export_covered,
            screen=screen,
            backup=str(backup) if backup else "",
        )
    final = run_final(checks, business_date=business, since=since, slack_on_fail=slack_on_fail)
    verified = final.get("result") == "PASS"
    gaps = None
    if verified:
        gaps = run_gaps(
            checks,
            business_date=(business_date + timedelta(days=1)).isoformat(),
            slack_on_fail=slack_on_fail,
        )
    difference = Decimal(str(updated.get("difference") or "0"))
    if not verified:
        outcome = OUTCOME_UNVERIFIED
    elif difference == 0:
        outcome = OUTCOME_MATCH
    else:
        outcome = OUTCOME_DISAGREE
    items = []
    if verified:
        items.append(
            {
                "receipt": business,
                "membr": updated.get("pos_card"),
                "bank": updated.get("payment_reports_total"),
                "difference": updated.get("difference"),
                "check": "Look up that day's card receipts in Membr or the Paycomet and Redsys reports.",
            }
        )
    return {
        "business_date": business,
        "status": "CONFIRMED" if verified else "CHECK_FAIL",
        "reason": "ok" if verified else "final",
        "outcome": outcome,
        "figures_final": verified,
        "confirmed_write": verified,
        "staged": True,
        "staged_file": str(staged),
        "tolerance": None,
        "export_covered": export_covered,
        "items": items,
        "phrase": "",
        "problems": list(final.get("problems") or []),
        "screen": screen,
        "workbook": str(workbook),
        "workbook_sha256": before,
        "backup": str(backup) if backup else "",
        "backup_sha256": before,
        "column_H_hidden": updated.get("column_H_hidden"),
        "row": updated.get("row"),
        "year_tab": updated.get("year_tab"),
        "difference": updated.get("difference"),
        "checks": {"export": export, "dates": dates, "update": updated, "final": final, "gaps": gaps},
    }


def json_load(path: Path) -> dict:
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return data
