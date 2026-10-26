#!/usr/bin/env python3
"""04:00 AFSA run with no model calls. A missing confirmed write is a failure."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feina_client.browser import open_session  # noqa: E402
from feina_client.cliutil import enabled, host_ready, membr_config  # noqa: E402
from feina_client.download import NoProfile  # noqa: E402
from feina_client.jobs import run_nightly  # noqa: E402
from feina_client.runtime import JobLock, post_ops_alert, madrid_now  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    del argv
    if not enabled("afsa-ingresos"):
        return 0
    cfg = membr_config(None)
    if not host_ready(cfg):
        return 0
    lock = JobLock()
    try:
        session = open_session(cfg)
    except NoProfile:
        result = run_nightly(cfg, session=None, lock=lock)
        if result.get("status") == "SKIPPED_BUSY":
            return 0
        post_ops_alert("no_profile", part="afsa-ingresos", when=madrid_now())
        return 0
    try:
        result = run_nightly(cfg, session=session, lock=lock)
    finally:
        session.close()
    if result.get("status") == "SKIPPED_BUSY":
        return 0
    if not result.get("confirmed_write"):
        reason = str(result.get("reason") or "")
        status = str(result.get("status") or "")
        code = {
            "login": "login_page",
            "login_page": "login_page",
            "captcha": "captcha",
            "no_profile": "no_profile",
            "no_session": "no_profile",
            "SOURCE_FORMAT_CHANGED": "source_format_changed",
            "PARSE_FAILED": "parse_failed",
            "NEEDS_CONFIRMATION": "needs_confirmation",
            "SCREEN_MISMATCH": "screen_mismatch",
            "CHECKS_UNAVAILABLE": "checks_unavailable",
            "FAILED": "readback_mismatch",
        }.get(status, {
            "login": "login_page",
            "login_page": "login_page",
            "captcha": "captcha",
            "no_profile": "no_profile",
            "no_session": "no_profile",
        }.get(reason, "workbook_missing"))
        post_ops_alert(code, part="afsa-ingresos", when=madrid_now())
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
