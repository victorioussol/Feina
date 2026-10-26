"""Paths, clock, file lock, backups, and the ops Slack alert.

Ops alerts are allow-listed status codes. They never carry member rows,
conversation text, cookies, or secrets.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

MADRID = ZoneInfo("Europe/Madrid")

ALERT_CODES = frozenset(
    {
        "login_page",
        "captcha",
        "token_expiry",
        "unknown_expiry",
        "no_profile",
        "workbook_missing",
        "not_confirmed",
        "wrong_night",
        "wrong_business_date",
        "file_missing",
        "stale_mtime",
        "readback_mismatch",
        "step_budget",
        "duration",
        "no_run_record",
        "session_stale",
        "session_check_failed",
        "rerun_failed",
        "script_error",
        "timezone_window",
        "lock_busy",
        "source_format_changed",
        "parse_failed",
        "needs_confirmation",
        "screen_mismatch",
        "checks_unavailable",
    }
)

# Login alerts share one slot per Madrid day. Evals use their own codes.
LOGIN_ALERT_CODES = frozenset(
    {"login_page", "captcha", "token_expiry", "unknown_expiry", "no_profile"}
)


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()


def client_root() -> Path:
    override = os.environ.get("FEINA_CLIENT_ROOT")
    if override:
        return Path(override).expanduser()
    return hermes_home() / "feina-client"


def madrid_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(MADRID)
    if now.tzinfo is None:
        return now.replace(tzinfo=MADRID)
    return now.astimezone(MADRID)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config must be a mapping: {path}")
    return data


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def part_enabled(name: str) -> bool:
    return (client_root() / "enabled" / name).is_file()


def client_config() -> dict:
    path = client_root() / "client.yaml"
    if not path.is_file():
        return {
            "client_slug": "client",
            "language": "es",
            "timezone": "Europe/Madrid",
            "slack_webhook_env": "FEINA_VINCE_SLACK_WEBHOOK",
        }
    return load_yaml(path)


def language() -> str:
    lang = str(client_config().get("language") or "es").lower()
    if lang not in {"fr", "es", "en"}:
        return "es"
    return lang


class JobLock:
    """Exclusive lock shared by the 04:00 job, Telegram long work, and re-runs.

    The lock is the open file descriptor. Callers keep the JobLock alive for
    the whole critical section.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (client_root() / "locks" / "afsa.lock")
        self._fh = None

    def acquire(self, blocking: bool = False) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(fh.fileno(), flags)
        except BlockingIOError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        self._fh.close()
        self._fh = None

    def held_by_other(self) -> bool:
        if not self.acquire(blocking=False):
            return True
        self.release()
        return False


def backup_file(path: Path, backup_root: Path | None = None) -> Path | None:
    """Copy `path` aside and record its SHA-256 before anyone edits it."""
    if not path.is_file():
        return None
    digest = sha256_file(path)
    root = backup_root or (client_root() / "backups")
    root.mkdir(parents=True, exist_ok=True)
    stamp = madrid_now().strftime("%Y%m%dT%H%M%S")
    dest = root / f"{path.name}.{stamp}.{digest[:16]}"
    shutil.copy2(path, dest)
    dest.with_suffix(dest.suffix + ".sha256").write_text(digest + "\n", encoding="utf-8")
    os.chmod(dest, 0o600)
    return dest


def format_alert(code: str, *, part: str, slug: str, when: datetime) -> str:
    if code not in ALERT_CODES:
        raise ValueError(f"alert code not allowed: {code}")
    when_s = madrid_now(when).strftime("%Y-%m-%dT%H:%M")
    text = f"[feina] {code}\nclient={slug}\nwhen={when_s}\npart={part}\ndetail={code}\n"
    assert_ops_text(text)
    return text


def assert_ops_text(text: str) -> None:
    """Reject anything that is not the fixed ops template."""
    lowered = text.lower()
    if "@" in text or "€" in text or "$" in text:
        raise ValueError("NO_CONTENT")
    for banned in ("password", "cookie", "bearer", "token=", "socio", "member"):
        if banned in lowered:
            raise ValueError("NO_CONTENT")
    if len(text) > 400:
        raise ValueError("NO_CONTENT")
    lines = [ln for ln in text.splitlines() if ln]
    if not lines or not lines[0].startswith("[feina] "):
        raise ValueError("NO_CONTENT")
    code = lines[0].split(" ", 1)[1].strip()
    if code not in ALERT_CODES:
        raise ValueError("NO_CONTENT")


def alert_state_path() -> Path:
    return client_root() / "state" / "alerts.json"


def should_send_alert(code: str, day: str, state: dict | None = None) -> bool:
    if state is None:
        state = read_json(alert_state_path())
    sent = state.get("sent") or {}
    if code in LOGIN_ALERT_CODES:
        return sent.get("login_day") != day
    return sent.get(code) != day


def mark_alert_sent(code: str, day: str, state: dict | None = None) -> dict:
    own = state is None
    state = read_json(alert_state_path()) if state is None else state
    sent = state.setdefault("sent", {})
    if code in LOGIN_ALERT_CODES:
        sent["login_day"] = day
    else:
        sent[code] = day
    if own:
        write_json(alert_state_path(), state)
    return state


def post_ops_alert(code: str, *, part: str, when: datetime | None = None) -> str:
    """Send one Slack webhook alert, or record it locally when the hook is unset.

    Returns 'sent', 'already', or 'no_webhook'. Never raises for a missing hook.
    """
    when = madrid_now(when)
    cfg = client_config()
    slug = str(cfg.get("client_slug") or "client")
    text = format_alert(code, part=part, slug=slug, when=when)
    day = when.date().isoformat()
    state = read_json(alert_state_path())
    if not should_send_alert(code, day, state):
        return "already"
    env_name = str(cfg.get("slack_webhook_env") or "FEINA_VINCE_SLACK_WEBHOOK")
    hook = os.environ.get(env_name, "").strip()
    mark_alert_sent(code, day, state)
    write_json(alert_state_path(), state)
    if not hook:
        pending = client_root() / "state" / "alerts-pending.log"
        pending.parent.mkdir(parents=True, exist_ok=True)
        with open(pending, "a", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(pending, 0o600)
        return "no_webhook"
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        hook,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    except urllib.error.URLError:
        return "no_webhook"
    return "sent"


def next_four_am(now: datetime) -> datetime:
    now = madrid_now(now)
    target = now.replace(hour=4, minute=0, second=0, microsecond=0)
    if now < target:
        return target
    return target + timedelta(days=1)


def night_id(now: datetime, grace_minutes: int = 10) -> str:
    """Madrid date of the 04:00 slot that should already have finished."""
    now = madrid_now(now)
    slot = now.replace(hour=4, minute=grace_minutes, second=0, microsecond=0)
    if now >= slot:
        return now.date().isoformat()
    return (now.date() - timedelta(days=1)).isoformat()


def business_date_for_night(night: str) -> str:
    year, month, day = (int(p) for p in night.split("-"))
    from datetime import date

    return (date(year, month, day) - timedelta(days=1)).isoformat()
