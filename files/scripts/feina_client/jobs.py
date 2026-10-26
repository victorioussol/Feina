"""The nightly AFSA run, the single re-run after a human login, and Telegram queueing.

One file lock covers all three so a chat request and the 04:00 job cannot
download Membr at the same time.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from pathlib import Path

from .download import NoProfile, run_download
from .reconcile import lines_from_xlsx, reconcile_lines, write_workbook
from .runtime import (
    business_date_for_night,
    client_root,
    madrid_now,
    night_id,
    read_json,
    sha256_file,
    write_json,
)
from .session import parse_observed, watcher_decision

RERUN_STATUSES = {"FAILED", "LOGIN_REQUIRED", "SKIPPED", "SKIPPED_BUSY", "MISSING"}


def night_path(night: str) -> Path:
    return client_root() / "state" / "nights" / f"{night}.json"


def load_night(night: str) -> dict:
    return read_json(night_path(night))


def save_night(payload: dict) -> None:
    write_json(night_path(payload["night"]), payload)


def _empty_status(night: str, business: str, status: str, **extra) -> dict:
    payload = {
        "night": night,
        "business_date": business,
        "status": status,
        "confirmed_write": False,
        "model_calls": 0,
        "drive": "NOT_RUN",
        "mismatches": [],
        "failed_debits": [],
        "sources": {},
    }
    payload.update(extra)
    return payload


def run_nightly(
    cfg: dict,
    *,
    now: datetime | None = None,
    session=None,
    lock=None,
    membr_dir: Path | None = None,
    inbox: Path | None = None,
    workbook: Path | None = None,
) -> dict:
    """Download, reconcile, write, read back. model_calls stays 0 on this path."""
    now = madrid_now(now)
    started = time.monotonic()
    night = night_id(now, grace_minutes=0)
    business = business_date_for_night(night)
    if lock is not None and not lock.acquire(blocking=False):
        payload = _empty_status(night, business, "SKIPPED_BUSY")
        save_night(payload)
        return payload
    try:
        previous = load_night(night)
        if previous.get("confirmed_write") and previous.get("business_date") == business:
            return previous
        out_dir = membr_dir or (client_root() / "runs" / business)
        if session is None:
            payload = _empty_status(night, business, "LOGIN_REQUIRED", reason="no_profile")
            payload["duration_sec"] = round(time.monotonic() - started, 3)
            save_night(payload)
            return payload
        try:
            manifest = run_download(
                cfg,
                business_date=business,
                out_dir=out_dir,
                session=session,
                mode="download",
            )
        except NoProfile:
            manifest = {"status": "LOGIN_REQUIRED", "reason": "no_profile", "files": []}
        if manifest.get("status") == "LOGIN_REQUIRED":
            payload = _empty_status(
                night,
                business,
                "LOGIN_REQUIRED",
                reason=manifest.get("reason") or "login_page",
            )
            payload["duration_sec"] = round(time.monotonic() - started, 3)
            save_night(payload)
            return payload
        if manifest.get("status") != "OK":
            payload = _empty_status(night, business, "FAILED", reason="download_failed")
            payload["duration_sec"] = round(time.monotonic() - started, 3)
            save_night(payload)
            return payload
        files = {item["report"]: Path(item["path"]) for item in manifest.get("files") or []}
        membr_path = files.get(cfg.get("pos_report_id") or "pos_transactions")
        if membr_path is None or not membr_path.is_file():
            payload = _empty_status(night, business, "FAILED", reason="membr_file_missing")
            payload["duration_sec"] = round(time.monotonic() - started, 3)
            save_night(payload)
            return payload
        inbox_dir = inbox or (client_root() / "inbox")
        paycomet_path = inbox_dir / f"paycomet-{business}.xlsx"
        harlands_path = inbox_dir / f"harlands-{business}.xlsx"
        pay_required = bool((cfg.get("sources") or {}).get("paycomet", {}).get("required", False))
        har_required = bool((cfg.get("sources") or {}).get("harlands", {}).get("required", False))
        business_day = date.fromisoformat(business)
        result = reconcile_lines(
            lines_from_xlsx(membr_path, "membr"),
            lines_from_xlsx(paycomet_path, "paycomet") if paycomet_path.is_file() else None,
            lines_from_xlsx(harlands_path, "harlands") if harlands_path.is_file() else None,
            business_date=business_day,
            paycomet_required=pay_required,
            harlands_required=har_required,
        )
        book = workbook or (client_root() / "workbooks" / "AFSA-Ingresos.xlsx")
        hashes = {"membr_pos": sha256_file(membr_path)}
        if paycomet_path.is_file():
            hashes["paycomet"] = sha256_file(paycomet_path)
        if harlands_path.is_file():
            hashes["harlands"] = sha256_file(harlands_path)
        written = write_workbook(book, night=night, result=result, source_hashes=hashes)
        status = "CONFIRMED" if written["confirmed_write"] else "FAILED"
        payload = _empty_status(night, business, status)
        payload.update(
            {
                "confirmed_write": bool(written["confirmed_write"]),
                "workbook": written["path"],
                "workbook_sha256": written["workbook_sha256"],
                "readback": written["readback"],
                "mismatches": result.public_mismatches(),
                "failed_debits": [item.as_dict() for item in result.failed_debits],
                "sources": hashes,
                "model_calls": 0,
                "duration_sec": round(time.monotonic() - started, 3),
                "drive": "NOT_RUN",
            }
        )
        save_night(payload)
        return payload
    finally:
        if lock is not None:
            lock.release()


def decide_rerun(
    state: dict,
    *,
    now: datetime,
    fingerprint: str | None,
    lock_busy: bool,
) -> str:
    now = madrid_now(now)
    minutes = now.hour * 60 + now.minute
    # Leave 03:30–04:10 to the scheduled check and the 04:00 job.
    too_early = (3 * 60 + 30) <= minutes < (4 * 60 + 10)
    night = night_id(now)
    previous_fp = state.get("cookie_fingerprint")
    changed = bool(fingerprint) and fingerprint != previous_fp
    record = load_night(night)
    status = record.get("status") if record else "MISSING"
    if not record and night != now.date().isoformat():
        status = "MISSING"
    decision = watcher_decision(
        fingerprint_changed=changed,
        last_page_status=state.get("last_page"),
        night_status=status,
        rerun_already=state.get("rerun_night") == night,
        lock_busy=lock_busy,
        too_early=too_early,
    )
    # Keep the new fingerprint unseen when we could not act, so a later tick
    # still notices the login. A rotation we deliberately ignore is consumed.
    if fingerprint and decision not in {"too_early", "busy"}:
        state["cookie_fingerprint"] = fingerprint
    return decision


def mark_rerun(state: dict, night: str) -> None:
    state["rerun_night"] = night
    state["fresh_login"] = False


def long_job_state() -> dict:
    return read_json(client_root() / "state" / "long_jobs.json")


def save_long_jobs(state: dict) -> None:
    write_json(client_root() / "state" / "long_jobs.json", state)


LONG_HINTS = (
    "membr",
    "ingresos",
    "informe",
    "report",
    "excel",
    "xlsx",
    "paycomet",
    "harlands",
    "redsys",
    "navegador",
    "browser",
    "reconciliation",
    "rapprochement",
    "conciliation",
    "descarga",
    "telecharg",
    "télécharg",
    "workbook",
    "tableur",
)


def is_long_request(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in LONG_HINTS)


def start_long_job(chat_id: str, label: str, *, lock_busy: bool, now: datetime | None = None) -> str:
    """Return 'start' or 'queued'. One active long job per chat."""
    now = madrid_now(now)
    state = long_job_state()
    chat = state.setdefault(chat_id, {"active": None, "queue": []})
    if chat.get("active") or lock_busy:
        chat["queue"].append({"label": label, "at": now.isoformat()})
        save_long_jobs(state)
        return "queued"
    chat["active"] = {"label": label, "at": now.isoformat()}
    save_long_jobs(state)
    return "start"


def finish_long_job(chat_id: str, *, lock_busy: bool = False) -> dict | None:
    """Clear the active job and promote the next one when the lock is free."""
    state = long_job_state()
    chat = state.setdefault(chat_id, {"active": None, "queue": []})
    chat["active"] = None
    queue = chat.get("queue") or []
    if not queue or lock_busy:
        save_long_jobs(state)
        return None
    nxt = queue.pop(0)
    chat["queue"] = queue
    chat["active"] = nxt
    save_long_jobs(state)
    return nxt


def queue_depth(chat_id: str) -> int:
    chat = long_job_state().get(chat_id) or {}
    return len(chat.get("queue") or [])


def observed_login(state: dict) -> datetime | None:
    return parse_observed(state)


def run_with_lock(cmd: list[str], lock) -> int:
    import subprocess

    if not lock.acquire(blocking=False):
        return 75
    try:
        return subprocess.call(cmd)
    finally:
        lock.release()
