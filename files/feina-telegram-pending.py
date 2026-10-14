#!/usr/bin/env python3
"""List Telegram user IDs from recent bot updates that are not yet allowlisted."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

ENV = "/root/.hermes/.env"


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in (ENV, "/root/.env"):
        try:
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    out.setdefault(k.strip(), v.strip())
        except OSError:
            pass
    return out


def allowed_ids(env: dict[str, str]) -> set[str]:
    raw = env.get("TELEGRAM_ALLOWED_USERS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


def fetch_pending(token: str) -> list[dict]:
    url = f"https://api.telegram.org/bot{token}/getUpdates?limit=50"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "getUpdates failed"))
    pending: list[dict] = []
    seen: set[int] = set()
    for upd in data.get("result") or []:
        msg = upd.get("message") or upd.get("edited_message") or {}
        user = msg.get("from") or {}
        uid = user.get("id")
        if uid is None or uid in seen:
            continue
        seen.add(uid)
        pending.append(
            {
                "user_id": str(uid),
                "username": user.get("username") or "",
                "first_name": user.get("first_name") or "",
                "text": (msg.get("text") or "")[:80],
            }
        )
    return pending


def main() -> int:
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN not set — run: feina-onboard telegram <token>")
        return 1
    allow = allowed_ids(env)
    try:
        users = fetch_pending(token)
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"Could not fetch Telegram updates: {exc}")
        return 1
    newcomers = [u for u in users if u["user_id"] not in allow]
    if not newcomers:
        print("No pending Telegram users in recent updates (or all are already allowlisted).")
        print("Ask the client to tap Start on the bot, then run this again.")
        return 0
    print("Pending Telegram users (approve with feina-onboard allow-telegram <user_id>):")
    for u in newcomers:
        label = u["username"] or u["first_name"] or "user"
        print(f"  {u['user_id']}  @{u['username'] or '-'}  {label!r}  last: {u['text']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
