#!/usr/bin/env python3
"""20:00 and 03:30 Madrid check. One Slack alert per day, never Telegram."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feina_client.browser import open_session  # noqa: E402
from feina_client.cliutil import enabled, host_ready, membr_config  # noqa: E402
from feina_client.download import NoProfile, assert_club_url  # noqa: E402
from feina_client.login_page import detect_login_wall  # noqa: E402
from feina_client.runtime import client_root, madrid_now, post_ops_alert, read_json, write_json  # noqa: E402
from feina_client.session import apply_login_check, earliest_expiry  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    del argv
    if not enabled("membr-login-guard"):
        return 0
    cfg = membr_config(None)
    if not host_ready(cfg):
        return 0
    state_path = client_root() / "state" / "login.json"
    state = read_json(state_path)
    now = madrid_now()
    page_status = "no_profile"
    expiry = None
    try:
        session = open_session(cfg)
    except NoProfile:
        session = None
    try:
        if session is not None:
            club = str(cfg["club_base_url"])
            assert_club_url(club, club)
            session.goto(club)
            wall = detect_login_wall(session.url(), session.content())
            page_status = wall or "ok"
            expiry = earliest_expiry(session.cookies(), tuple((cfg.get("browser") or {}).get("cookie_names") or ()))
    except Exception:
        post_ops_alert("session_check_failed", part="membr-login-guard", when=now)
        write_json(state_path, state)
        return 0
    finally:
        if session is not None:
            session.close()
    ok, reason = apply_login_check(state, now=now, page_status=page_status, token_expiry=expiry)
    write_json(state_path, state)
    if not ok:
        code = reason if reason in {"login_page", "captcha", "token_expiry", "unknown_expiry", "no_profile"} else "session_check_failed"
        post_ops_alert(code, part="membr-login-guard", when=now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
