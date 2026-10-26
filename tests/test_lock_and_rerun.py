"""The shared AFSA lock and the one-shot re-run after a human login."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from feina_client.jobs import decide_rerun, load_night, run_nightly, save_night, start_long_job
from feina_client.runtime import JobLock, night_id, write_json
from feina_client.session import cookie_fingerprint

MADRID = ZoneInfo("Europe/Madrid")


def at(hour, minute, day=26):
    return datetime(2026, 10, day, hour, minute, tzinfo=MADRID)


def _cookies(path, name="PHPSESSID", creation=10, expires=20, value="super-secret-cookie"):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB, creation_utc INTEGER, expires_utc INTEGER)"
    )
    conn.execute(
        "INSERT INTO cookies VALUES (?,?,?,?,?,?)",
        ("club.membr.com", name, value, b"encrypted-secret", creation, expires),
    )
    conn.commit()
    conn.close()


def test_lock_is_exclusive_and_a_busy_night_is_skipped(client):
    first = JobLock(client / "locks" / "afsa.lock")
    second = JobLock(client / "locks" / "afsa.lock")
    assert first.acquire() is True
    assert second.acquire() is False
    assert second.held_by_other() is True
    cfg = {"pos_report_id": "pos_transactions"}
    result = run_nightly(cfg, now=at(4, 5), session=object(), lock=second)
    assert result["status"] == "SKIPPED_BUSY"
    assert result["confirmed_write"] is False
    first.release()
    assert second.held_by_other() is False


def test_login_required_when_there_is_no_session(client):
    result = run_nightly({"pos_report_id": "pos_transactions"}, now=at(4, 5), session=None)
    assert result["status"] == "LOGIN_REQUIRED"
    assert result["reason"] == "no_profile"
    assert result["model_calls"] == 0
    assert load_night(result["night"])["confirmed_write"] is False


def test_rerun_once_and_quiet_window_does_not_consume_the_fingerprint(client):
    state = {"last_page": "login", "cookie_fingerprint": "old"}
    night = night_id(at(10, 0))
    save_night({"night": night, "status": "LOGIN_REQUIRED", "confirmed_write": False})
    assert decide_rerun(state, now=at(3, 45), fingerprint="new", lock_busy=False) == "too_early"
    assert "cookie_fingerprint" not in state or state["cookie_fingerprint"] == "old"

    state = {"last_page": "captcha", "cookie_fingerprint": "old"}
    assert decide_rerun(state, now=at(10, 0), fingerprint="new", lock_busy=True) == "busy"
    assert state["cookie_fingerprint"] == "old"

    state = {"last_page": "login", "cookie_fingerprint": "old"}
    assert decide_rerun(state, now=at(10, 0), fingerprint="new", lock_busy=False) == "rerun"
    assert state["cookie_fingerprint"] == "new"

    state["rerun_night"] = night
    assert decide_rerun(state, now=at(10, 15), fingerprint="newer", lock_busy=False) == "already"


def test_rotation_while_already_logged_in_does_not_rerun(client):
    state = {"last_page": "ok", "cookie_fingerprint": "old"}
    night = night_id(at(10, 0))
    save_night({"night": night, "status": "FAILED"})
    assert decide_rerun(state, now=at(10, 0), fingerprint="new", lock_busy=False) == "ignore_rotation"


def test_confirmed_night_is_left_alone(client):
    state = {"last_page": "login", "cookie_fingerprint": "old"}
    night = night_id(at(10, 0))
    save_night({"night": night, "status": "CONFIRMED", "confirmed_write": True})
    assert decide_rerun(state, now=at(10, 0), fingerprint="new", lock_busy=False) == "night_ok"


def test_cookie_reader_drops_values(client):
    from feina_client.session import read_cookie_metadata

    db = client / "Default" / "Cookies"
    _cookies(db)
    rows = read_cookie_metadata(db)
    assert rows and rows[0]["name"] == "PHPSESSID"
    assert "value" not in rows[0]
    assert "encrypted_value" not in rows[0]
    blob = str(rows)
    assert "super-secret-cookie" not in blob
    assert "encrypted-secret" not in blob
    assert cookie_fingerprint(rows)


def test_fingerprint_rejects_values():
    try:
        cookie_fingerprint([{"name": "PHPSESSID", "host": "club.membr.com", "value": "x"}])
    except ValueError as exc:
        assert "value" in str(exc)
    else:
        raise AssertionError("cookie values must be rejected")


def test_watcher_restores_fingerprint_when_the_lock_is_busy(client, monkeypatch):
    import membr_login_watch

    (client / "enabled").mkdir()
    (client / "enabled" / "membr-login-guard").write_text("enabled\n")
    (client / "enabled" / "afsa-ingresos").write_text("enabled\n")
    profile = client / "profile"
    db = profile / "Default" / "Cookies"
    _cookies(db, creation=99, expires=100)
    (client / "membr.reports.yaml").write_text(
        "club_base_url: https://club.membr.com\nbrowser:\n  user_data_dir: "
        + str(profile)
        + "\n",
        encoding="utf-8",
    )
    write_json(client / "state" / "login.json", {"last_page": "login", "cookie_fingerprint": "old"})
    now = datetime.now(MADRID)
    night = night_id(now)
    if (3 * 60 + 30) <= (now.hour * 60 + now.minute) < (4 * 60 + 10):
        # The watcher refuses this window. Move the clock with a patched now.
        now = now.replace(hour=10, minute=0)
        monkeypatch.setattr(membr_login_watch, "madrid_now", lambda: now)
        monkeypatch.setattr("feina_client.jobs.madrid_now", lambda now=None: now if now else datetime.now(MADRID))
        night = night_id(now)
    save_night({"night": night, "status": "FAILED", "confirmed_write": False})
    monkeypatch.setattr(membr_login_watch, "open_session", lambda cfg: (_ for _ in ()).throw(AssertionError("no browser")))
    calls = {}

    def _nightly(cfg, **kwargs):
        calls["n"] = calls.get("n", 0) + 1
        return {"status": "SKIPPED_BUSY", "night": night, "confirmed_write": False}

    monkeypatch.setattr(membr_login_watch, "run_nightly", _nightly)
    # open_session is called before run_nightly. Replace it with a dummy session.
    class Dummy:
        def close(self):
            pass

    monkeypatch.setattr(membr_login_watch, "open_session", lambda cfg: Dummy())
    assert membr_login_watch.main() == 0
    state = __import__("json").loads((client / "state" / "login.json").read_text())
    assert state["cookie_fingerprint"] == "old"
    assert calls["n"] == 1
    assert "rerun_night" not in state


def test_second_request_is_queued_while_a_long_job_or_the_night_lock_is_held(client):
    assert start_long_job("chat", "ingresos", lock_busy=False, now=at(11, 0)) == "start"
    assert start_long_job("chat", "another report", lock_busy=False, now=at(11, 1)) == "queued"
    assert start_long_job("other", "report", lock_busy=True, now=at(11, 2)) == "queued"
