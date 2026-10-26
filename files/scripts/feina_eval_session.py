#!/usr/bin/env python3
"""Session freshness from the last login check. Does not open Membr."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feina_client.cliutil import enabled  # noqa: E402
from feina_client.evals import session_eval  # noqa: E402
from feina_client.runtime import client_root, madrid_now, post_ops_alert, read_json  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    del argv
    if not enabled("afsa-evals"):
        return 0
    now = madrid_now()
    state = read_json(client_root() / "state" / "login.json")
    ok, reason = session_eval(state.get("last_check_at"), bool(state.get("last_ok")), now)
    if not ok:
        code = reason if reason in {"session_stale", "session_check_failed", "login_page"} else "session_stale"
        post_ops_alert(code, part="afsa-evals", when=now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
