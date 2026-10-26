#!/usr/bin/env python3
"""Notice a fresh login from the local cookie file and re-run the night job once.

This does not poll Membr. A page opens only when a re-run actually starts,
and that re-run is the normal download, which stops if the login wall is up.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feina_client.browser import open_session  # noqa: E402
from feina_client.cliutil import enabled, host_ready, membr_config  # noqa: E402
from feina_client.download import NoProfile  # noqa: E402
from feina_client.jobs import decide_rerun, mark_rerun, run_nightly  # noqa: E402
from feina_client.runtime import (  # noqa: E402
    JobLock,
    client_root,
    madrid_now,
    night_id,
    post_ops_alert,
    read_json,
    write_json,
)
from feina_client.session import cookie_fingerprint, read_cookie_metadata  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    del argv
    if not enabled("membr-login-guard") or not enabled("afsa-ingresos"):
        return 0
    cfg = membr_config(None)
    if not host_ready(cfg):
        return 0
    state_path = client_root() / "state" / "login.json"
    state = read_json(state_path)
    profile = Path(str((cfg.get("browser") or {}).get("user_data_dir") or "")).expanduser()
    db = profile / "Default" / "Cookies"
    rows = read_cookie_metadata(db)
    fingerprint = cookie_fingerprint(rows) if rows else state.get("cookie_fingerprint")
    previous_fp = state.get("cookie_fingerprint")
    lock = JobLock()
    decision = decide_rerun(state, now=madrid_now(), fingerprint=fingerprint, lock_busy=lock.held_by_other())
    if decision != "rerun":
        write_json(state_path, state)
        return 0
    try:
        session = open_session(cfg)
        try:
            result = run_nightly(cfg, session=session, lock=lock)
        finally:
            session.close()
    except NoProfile:
        post_ops_alert("rerun_failed", part="membr-login-guard", when=madrid_now())
        mark_rerun(state, night_id(madrid_now()))
        write_json(state_path, state)
        return 0
    except Exception:
        post_ops_alert("rerun_failed", part="membr-login-guard", when=madrid_now())
        mark_rerun(state, night_id(madrid_now()))
        write_json(state_path, state)
        return 0
    if result.get("status") == "SKIPPED_BUSY":
        state["cookie_fingerprint"] = previous_fp
        write_json(state_path, state)
        return 0
    mark_rerun(state, result.get("night") or night_id(madrid_now()))
    write_json(state_path, state)
    if not result.get("confirmed_write"):
        post_ops_alert("rerun_failed", part="membr-login-guard", when=madrid_now())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
