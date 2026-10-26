#!/usr/bin/env python3
"""Immediate Telegram acknowledgement, then a single long job per chat."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feina_client.cliutil import enabled  # noqa: E402
from feina_client.jobs import finish_long_job, is_long_request, start_long_job  # noqa: E402
from feina_client.proactive import text  # noqa: E402
from feina_client.runtime import JobLock, hermes_home, language, madrid_now  # noqa: E402


def _env_value(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name].strip()
    path = hermes_home() / ".env"
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def send_telegram(chat: str, body: str) -> bool:
    token = _env_value("TELEGRAM_BOT_TOKEN")
    if not token or not chat or not body:
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": body}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            resp.read()
    except Exception:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ack or finish one long Telegram job")
    sub = parser.add_subparsers(dest="cmd", required=True)
    start = sub.add_parser("start")
    start.add_argument("--chat", required=True)
    start.add_argument("--label", required=True)
    start.add_argument("--text", default="")
    finish = sub.add_parser("finish")
    finish.add_argument("--chat", required=True)
    finish.add_argument("--text", default="")
    classify = sub.add_parser("classify")
    classify.add_argument("--text", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "classify":
        sys.stdout.write(json.dumps({"long": is_long_request(args.text)}) + "\n")
        return 0
    if not enabled("telegram-background"):
        sys.stdout.write(json.dumps({"action": "disabled"}) + "\n")
        return 0
    lang = language()
    if args.cmd == "start":
        busy = JobLock().held_by_other()
        action = start_long_job(args.chat, args.label, lock_busy=busy, now=madrid_now())
        if action == "queued":
            body = text(lang, "nightly_busy" if busy else "queued")
        else:
            body = text(lang, "ack")
        sent = send_telegram(args.chat, body)
        sys.stdout.write(json.dumps({"action": action, "sent": sent, "say": None if sent else body}) + "\n")
        return 0
    nxt = finish_long_job(args.chat, lock_busy=JobLock().held_by_other())
    sent = send_telegram(args.chat, args.text) if args.text else False
    sys.stdout.write(
        json.dumps({"action": "finished", "sent": sent, "queued_next": None if not nxt else nxt.get("label")})
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
