#!/usr/bin/env python3
"""Store a client 'remind me' without sending anything yet."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feina_client.cliutil import enabled  # noqa: E402
from feina_client.proactive import add_reminder, mark_inbound, unpause  # noqa: E402
from feina_client.runtime import MADRID, client_root, read_json, write_json  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Client reminders and proactive replies")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("--when", required=True, help="ISO time, Europe/Madrid if no offset")
    add.add_argument("--text", required=True)
    add.add_argument("--allow-quiet", action="store_true")
    sub.add_parser("inbound")
    pause = sub.add_parser("unpause")
    pause.add_argument("--kind", required=True)
    args = parser.parse_args(argv)
    if not enabled("proactive-starters"):
        sys.stdout.write(json.dumps({"ok": False, "reason": "disabled"}) + "\n")
        return 0
    path = client_root() / "state" / "proactive.json"
    state = read_json(path)
    if args.cmd == "add":
        when = datetime.fromisoformat(args.when)
        if when.tzinfo is None:
            when = when.replace(tzinfo=MADRID)
        item = add_reminder(state, when, args.text, allow_quiet=args.allow_quiet)
        write_json(path, state)
        sys.stdout.write(json.dumps({"ok": True, "id": item["id"]}) + "\n")
        return 0
    if args.cmd == "inbound":
        mark_inbound(state)
        write_json(path, state)
        sys.stdout.write(json.dumps({"ok": True}) + "\n")
        return 0
    unpause(state, args.kind)
    write_json(path, state)
    sys.stdout.write(json.dumps({"ok": True}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
