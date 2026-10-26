"""No-LLM checks. They look at the workbook and the run record, not at cron's own OK."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .runtime import business_date_for_night, madrid_now, sha256_file


def workbook_eval(status: dict | None, workbook: Path | None, now: datetime) -> tuple[bool, str]:
    now = madrid_now(now)
    night = now.date().isoformat()
    business = business_date_for_night(night)
    if not status or not status.get("confirmed_write"):
        return False, "workbook_missing"
    if status.get("status") != "CONFIRMED":
        return False, "not_confirmed"
    final = ((status.get("checks") or {}).get("final") or {})
    if (
        status.get("outcome") not in {"verified_match", "verified_disagree"}
        or not status.get("figures_final")
        or final.get("result") != "PASS"
    ):
        return False, "not_confirmed"
    if status.get("column_H_hidden") is True:
        return False, "readback_mismatch"
    if status.get("night") != night:
        return False, "wrong_night"
    if status.get("business_date") != business:
        return False, "wrong_business_date"
    if workbook is None or not workbook.is_file():
        return False, "file_missing"
    modified = datetime.fromtimestamp(workbook.stat().st_mtime, tz=now.tzinfo).astimezone(now.tzinfo)
    if modified.date() != now.date():
        return False, "stale_mtime"
    return True, "ok"


def skill_hash_eval(recorded: dict, skill_dir: Path) -> tuple[bool, str]:
    """Compare the installed membr-card-reconciliation skill with the approved hashes."""
    files = (recorded or {}).get("files") or {}
    if not files:
        return False, "skill_hash_drift"
    for name, digest in files.items():
        path = skill_dir / name
        if not path.is_file() or sha256_file(path) != digest:
            return False, "skill_hash_drift"
    return True, "ok"


def step_budget(
    record: dict | None,
    *,
    max_calls: int = 15,
    max_minutes: int = 20,
) -> tuple[bool, str]:
    if not record:
        return False, "no_run_record"
    calls = int(record.get("model_calls") if record.get("model_calls") is not None else -1)
    if calls < 0:
        return False, "no_run_record"
    if calls >= max_calls:
        return False, "step_budget"
    duration = float(record.get("duration_sec") or 0)
    if duration >= max_minutes * 60:
        return False, "duration"
    return True, "ok"


def session_eval(last_check_at: str | None, ok: bool, now: datetime, *, max_age_hours: float = 12) -> tuple[bool, str]:
    """A stored login check is fresh enough for the morning. This does not open Membr."""
    now = madrid_now(now)
    if not last_check_at:
        return False, "session_stale"
    try:
        when = datetime.fromisoformat(last_check_at)
    except ValueError:
        return False, "session_check_failed"
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    age = (now - when.astimezone(now.tzinfo)).total_seconds()
    if age < 0 or age > max_age_hours * 3600:
        return False, "session_stale"
    if not ok:
        return False, "login_page"
    return True, "ok"
