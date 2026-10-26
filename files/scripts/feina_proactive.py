#!/usr/bin/env python3
"""Print a proactive Telegram note, or print nothing.

Cron deliver is Telegram. Empty stdout stays silent. Errors go to Slack,
not to the client's chat.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feina_client.cliutil import enabled  # noqa: E402
from feina_client.jobs import load_night  # noqa: E402
from feina_client.proactive import (  # noqa: E402
    in_send_window,
    morning_bundle,
    notable_changes,
    reminder_lines,
)
from feina_client.runtime import (  # noqa: E402
    client_config,
    client_root,
    language,
    load_yaml,
    madrid_now,
    night_id,
    post_ops_alert,
    read_json,
    write_json,
)


def _flags() -> dict:
    path = client_root() / "proactive.yaml"
    if not path.is_file():
        return {}
    data = load_yaml(path)
    return data.get("enabled") or {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Proactive notes, off unless configured")
    parser.add_argument("--slot", choices=("morning", "reminders"), required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if not enabled("proactive-starters"):
        return 0
    try:
        return _run(args.slot, args.force)
    except Exception:
        post_ops_alert("script_error", part="proactive-starters", when=madrid_now())
        return 0


def _run(slot: str, force: bool) -> int:
    now = madrid_now()
    state = read_json(client_root() / "state" / "proactive.json")
    lang = language()
    if slot == "reminders":
        body = reminder_lines(state, lang=lang, now=now)
        write_json(client_root() / "state" / "proactive.json", state)
        if body:
            sys.stdout.write(body.strip() + "\n")
        return 0
    flags = _flags()
    if not any(flags.get(name) for name in ("daily", "monday", "tax", "month_end")):
        return 0
    if not force and not in_send_window(now, 9):
        post_ops_alert("timezone_window", part="proactive-starters", when=now)
        return 0
    night = load_night(night_id(now))
    metrics = read_json(client_root() / "state" / "metrics.json")
    changes = metrics.get("changes")
    if changes is None and ("current" in metrics or "previous" in metrics):
        changes = notable_changes(metrics.get("current") or {}, metrics.get("previous") or {})
    cfg = client_config()
    body = morning_bundle(
        state,
        lang=lang,
        now=now,
        enabled=flags,
        night=night,
        changes=changes or [],
        debits=(night or {}).get("failed_debits") or [],
        gestor_to=str(cfg.get("gestor_to") or ""),
        gestor_subject=str(cfg.get("gestor_subject") or "AFSA mensual"),
        gestor_body=str(cfg.get("gestor_body") or ""),
        when_clean=bool(cfg.get("daily_when_clean", True)),
    )
    write_json(client_root() / "state" / "proactive.json", state)
    if body:
        sys.stdout.write(body.strip() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
