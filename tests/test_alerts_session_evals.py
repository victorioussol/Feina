"""Ops alerts, session coverage, and the morning evals."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from feina_client.evals import session_eval, skill_hash_eval, step_budget, workbook_eval
from feina_client.runtime import assert_ops_text, format_alert, post_ops_alert, should_send_alert
from feina_client.session import apply_login_check, covers_0400, earliest_expiry, note_page_result
from feina_client.xlsxio import write_xlsx

MADRID = ZoneInfo("Europe/Madrid")


def at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=MADRID)


def test_ops_alert_is_allow_listed_and_one_login_alert_per_day(client, monkeypatch):
    when = at(2026, 10, 26, 20, 0)
    text = format_alert("login_page", part="membr-login-guard", slug="vince", when=when)
    assert_ops_text(text)
    assert "vince" in text
    assert "@" not in text
    for bad in (
        "[feina] login_page\nmember=1\n",
        "[feina] login_page\nclient=a@b.c\n",
        "x" * 401,
        "[feina] not_a_code\n",
    ):
        try:
            assert_ops_text(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)
    captured = {}

    def _open(req, timeout=0):
        captured["body"] = json.loads(req.data.decode())
        class Resp:
            def read(self):
                return b"ok"
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        return Resp()

    monkeypatch.setenv("FEINA_VINCE_SLACK_WEBHOOK", "http://127.0.0.1:9/hook")
    monkeypatch.setattr("feina_client.runtime.urllib.request.urlopen", _open)
    (client / "client.yaml").write_text(
        "client_slug: vince\nlanguage: fr\nslack_webhook_env: FEINA_VINCE_SLACK_WEBHOOK\n",
        encoding="utf-8",
    )
    assert post_ops_alert("login_page", part="membr-login-guard", when=when) == "sent"
    assert post_ops_alert("captcha", part="membr-login-guard", when=when) == "already"
    assert "member" not in captured["body"]["text"]
    assert "socio" not in captured["body"]["text"].lower()
    assert should_send_alert("workbook_missing", "2026-10-26") is True
    assert post_ops_alert("workbook_missing", part="afsa-evals", when=when) == "sent"
    assert post_ops_alert("workbook_missing", part="afsa-evals", when=when) == "already"


def test_missing_webhook_is_local_only(client):
    when = at(2026, 10, 26, 3, 30)
    assert post_ops_alert("no_profile", part="membr-login-guard", when=when) == "no_webhook"
    pending = (client / "state" / "alerts-pending.log").read_text(encoding="utf-8")
    assert pending.startswith("[feina] no_profile")
    assert "password" not in pending.lower()


def test_session_covers_0400_without_sliding_the_login_clock():
    now = at(2026, 10, 25, 20, 0)
    target = at(2026, 10, 26, 4, 0)
    assert covers_0400(now=now, target=target, page_status="captcha", token_expiry=None, login_observed_at=None) == (False, "captcha")
    assert covers_0400(now=now, target=target, page_status="login", token_expiry=None, login_observed_at=None)[0] is False
    assert covers_0400(now=now, target=target, page_status="no_profile", token_expiry=None, login_observed_at=None)[1] == "no_profile"
    later = target + timedelta(hours=2)
    ok, reason = covers_0400(now=now, target=target, page_status="ok", token_expiry=later, login_observed_at=None)
    assert ok and reason == "token_expiry"
    early = target
    ok, reason = covers_0400(now=now, target=target, page_status="ok", token_expiry=early, login_observed_at=None)
    assert ok is False and reason == "token_expiry"
    observed = at(2026, 10, 25, 5, 0)
    ok, reason = covers_0400(now=now, target=target, page_status="ok", token_expiry=None, login_observed_at=observed)
    assert ok and reason == "observed_24h"
    stale = at(2026, 10, 25, 3, 0)
    ok, reason = covers_0400(now=now, target=target, page_status="ok", token_expiry=None, login_observed_at=stale)
    assert ok is False and reason == "observed_24h"
    ok, reason = covers_0400(now=now, target=target, page_status="ok", token_expiry=None, login_observed_at=None)
    assert ok is False and reason == "unknown_expiry"
    near = at(2026, 10, 26, 3, 30)
    ok, reason = covers_0400(now=near, target=target, page_status="ok", token_expiry=None, login_observed_at=None)
    assert ok and reason == "page_ok_near_run"

    state = {"last_page": "ok", "login_observed_at": stale.isoformat()}
    note_page_result(state, page_status="ok", now=now)
    assert state["login_observed_at"] == stale.isoformat()
    state = {"last_page": "login"}
    ok, reason = apply_login_check(state, now=now, page_status="ok")
    assert state["fresh_login"] is True
    assert ok is True and reason == "observed_24h"


def test_cookies_are_not_a_membr_login_signal():
    when = at(2026, 10, 26, 12, 0)
    rows = [
        {"host": ".membr.com", "name": "__stripe_mid", "expires_at": when},
        {"host": ".membr.com", "name": "_hjSessionUser_1", "expires_at": when},
        {"host": ".membr.com", "name": "AWSALB", "expires_at": when},
        {"host": ".membr.com", "name": "PHPSESSID", "expires_at": when},
    ]
    assert earliest_expiry(rows) is None
    assert earliest_expiry(rows, ()) is None
    # A datetime expiry is used as a datetime. It is not Chrome microseconds.
    assert earliest_expiry(rows, ("PHPSESSID",)) == when


def test_workbook_step_and_session_evals(tmp_path):
    now = at(2026, 10, 26, 6, 0)
    book = tmp_path / "AFSA-Ingresos.xlsx"
    write_xlsx(book, {"AFSA": [["day"], ["2026-10-25"]]})
    stamp = at(2026, 10, 26, 5, 30).timestamp()
    import os

    os.utime(book, (stamp, stamp))
    status = {
        "night": "2026-10-26",
        "business_date": "2026-10-25",
        "status": "CONFIRMED",
        "confirmed_write": True,
        "outcome": "verified_match",
        "figures_final": True,
        "column_H_hidden": False,
        "checks": {"final": {"result": "PASS"}},
    }
    assert workbook_eval(status, book, now) == (True, "ok")
    status["confirmed_write"] = False
    assert workbook_eval(status, book, now)[1] == "workbook_missing"
    assert step_budget({"model_calls": 0, "duration_sec": 30}) == (True, "ok")
    assert step_budget({"model_calls": 15, "duration_sec": 30})[1] == "step_budget"
    assert step_budget({"model_calls": 2, "duration_sec": 20 * 60})[1] == "duration"
    assert step_budget(None)[1] == "no_run_record"
    fresh = (now - timedelta(hours=11)).isoformat()
    assert session_eval(fresh, True, now) == (True, "ok")
    stale = (now - timedelta(hours=13)).isoformat()
    assert session_eval(stale, True, now)[1] == "session_stale"
    assert session_eval(fresh, False, now)[1] == "login_page"


def test_skill_hash_eval_alerts_when_an_approved_file_changes(tmp_path):
    skill = tmp_path / "membr-card-reconciliation"
    skill.mkdir()
    body = skill / "SKILL.md"
    body.write_text("approved\n", encoding="utf-8")
    digest = hashlib.sha256(body.read_bytes()).hexdigest()
    recorded = {"files": {"SKILL.md": digest}}
    assert skill_hash_eval(recorded, skill) == (True, "ok")
    body.write_text("edited by a background review\n", encoding="utf-8")
    assert skill_hash_eval(recorded, skill) == (False, "skill_hash_drift")
    assert skill_hash_eval({"files": {}}, skill) == (False, "skill_hash_drift")
