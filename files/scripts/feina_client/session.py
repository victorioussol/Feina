"""Will the saved Membr session still be valid at 04:00, and should we re-run?

The session signal is the page: the dashboard loads, or the login form or a
captcha is showing. Membr keeps that login in page storage. Cookie names are
not a login signal. A successful page load does not slide the 24 hour clock
forward; that clock starts only when a login wall has just cleared.

The watcher reads local Chrome cookie metadata (name, host, creation, expiry)
to notice a file change after a wall. It does not read cookie values, it does
not treat a cookie name as proof of a Membr session, and it does not poll
Membr to keep a session warm.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .runtime import MADRID, madrid_now

CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def chrome_expiry_to_datetime(microseconds: int | None) -> datetime | None:
    if microseconds is None or microseconds <= 0:
        return None
    return CHROME_EPOCH + timedelta(microseconds=int(microseconds))


def covers_0400(
    *,
    now: datetime,
    target: datetime,
    page_status: str,
    token_expiry: datetime | None,
    login_observed_at: datetime | None,
    near_minutes: int = 45,
    session_hours: int = 24,
) -> tuple[bool, str]:
    """Return (will_cover_target, reason).

    page_status is 'ok', 'login', 'captcha', or 'no_profile'.
    """
    if page_status == "captcha":
        return False, "captcha"
    if page_status == "login":
        return False, "login_page"
    if page_status == "no_profile":
        return False, "no_profile"
    if page_status != "ok":
        return False, "session_check_failed"
    if token_expiry is not None:
        expiry = token_expiry.astimezone(MADRID) if token_expiry.tzinfo else token_expiry.replace(tzinfo=MADRID)
        ok = expiry > madrid_now(target) + timedelta(minutes=5)
        return ok, "token_expiry"
    if login_observed_at is not None:
        observed = madrid_now(login_observed_at)
        ends = observed + timedelta(hours=session_hours)
        return ends > madrid_now(target), "observed_24h"
    if madrid_now(target) - madrid_now(now) <= timedelta(minutes=near_minutes):
        return True, "page_ok_near_run"
    return False, "unknown_expiry"


def note_page_result(state: dict, *, page_status: str, now: datetime) -> dict:
    """Update login bookkeeping. A fresh login is only a wall that just cleared."""
    now = madrid_now(now)
    previous = state.get("last_page")
    state["last_page"] = page_status
    state["last_check_at"] = now.isoformat()
    if page_status == "ok" and previous in {"login", "captcha"}:
        state["login_observed_at"] = now.isoformat()
        state["fresh_login"] = True
    elif page_status in {"login", "captcha", "no_profile"}:
        state["fresh_login"] = False
    else:
        state["fresh_login"] = False
    return state


def apply_login_check(
    state: dict,
    *,
    now: datetime,
    page_status: str,
    token_expiry: datetime | None = None,
) -> tuple[bool, str]:
    """Record the page result, then decide if 04:00 is covered.

    The transition is recorded first so a login we just saw counts toward
    the 24 hour window. A page that was already logged in does not move
    that timestamp.
    """
    from .runtime import next_four_am

    note_page_result(state, page_status=page_status, now=now)
    ok, reason = covers_0400(
        now=now,
        target=next_four_am(now),
        page_status=page_status,
        token_expiry=token_expiry,
        login_observed_at=parse_observed(state),
    )
    state["last_reason"] = reason
    state["last_ok"] = ok
    return ok, reason


def parse_observed(state: dict) -> datetime | None:
    raw = state.get("login_observed_at")
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def cookie_fingerprint(rows: list[dict]) -> str:
    """Hash name, host, creation and expiry. Values are not accepted."""
    parts = []
    for row in rows:
        if "value" in row or "encrypted_value" in row:
            raise ValueError("cookie values must not be fingerprinted")
        parts.append(
            "|".join(
                [
                    str(row.get("host") or ""),
                    str(row.get("name") or ""),
                    str(row.get("creation_utc") or ""),
                    str(row.get("expires_utc") or ""),
                ]
            )
        )
    payload = "\n".join(sorted(parts)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def earliest_expiry(rows: list[dict], names: tuple[str, ...] | None = None) -> datetime | None:
    """Earliest real expiry among an explicit set of cookie names.

    An empty or missing name list returns None. Cookie names are not a Membr
    login signal, so there is no default list. Session cookies (no expiry)
    are ignored.
    """
    if not names:
        return None
    wanted = set(names)
    found: list[datetime] = []
    for row in rows:
        if row.get("name") not in wanted:
            continue
        host = str(row.get("host") or "")
        if "membr.com" not in host:
            continue
        when = row.get("expires_at")
        if isinstance(when, datetime):
            found.append(when)
            continue
        expires_utc = row.get("expires_utc")
        converted = chrome_expiry_to_datetime(expires_utc if isinstance(expires_utc, int) else None)
        if converted is not None:
            found.append(converted)
    if not found:
        return None
    return min(found)


def read_cookie_metadata(db_path: Path, host_contains: str = "membr.com") -> list[dict]:
    """Read Chrome's cookie table without the value columns."""
    if not db_path.is_file():
        return []
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return []
    try:
        try:
            cur = conn.execute(
                "SELECT host_key, name, creation_utc, expires_utc FROM cookies"
            )
            fetched = cur.fetchall()
        except sqlite3.Error:
            return []
    finally:
        conn.close()
    rows = []
    for host, name, creation, expires in fetched:
        if host_contains not in str(host):
            continue
        rows.append(
            {
                "host": host,
                "name": name,
                "creation_utc": int(creation or 0),
                "expires_utc": int(expires or 0),
            }
        )
    return rows


def watcher_decision(
    *,
    fingerprint_changed: bool,
    last_page_status: str | None,
    night_status: str | None,
    rerun_already: bool,
    lock_busy: bool,
    too_early: bool,
) -> str:
    """What the local watcher should do. It does not itself open Membr."""
    if too_early:
        return "too_early"
    if not fingerprint_changed:
        return "idle"
    if last_page_status not in {"login", "captcha"}:
        return "ignore_rotation"
    if night_status not in {"FAILED", "LOGIN_REQUIRED", "SKIPPED", "SKIPPED_BUSY", "MISSING"}:
        return "night_ok"
    if rerun_already:
        return "already"
    if lock_busy:
        return "busy"
    return "rerun"
