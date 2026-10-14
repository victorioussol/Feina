#!/usr/bin/env python3
"""Feina ops: day-before-meeting readiness checklist."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

OPS = Path(__file__).resolve().parent
sys.path.insert(0, str(OPS))

from feina_launch_state import load_launch, safe_slug  # noqa: E402
from orgo_bash import OrgoBashError, orgo_bash  # noqa: E402


def orgo_get(api_base: str, key: str, path: str) -> dict:
    req = urllib.request.Request(
        f"{api_base.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def expected_workspace(slug: str) -> str:
    s = safe_slug(slug)
    return f"feina-{s}"


def honcho_deriver_warning() -> tuple[str, str] | None:
    """Return (level, message) when deriver queue may block representation/chat."""
    admin = os.environ.get("FEINA_HONCHO_ADMIN_KEY", "").strip()
    if not admin:
        return (
            "WARN",
            "Honcho deriver queue not checked (set FEINA_HONCHO_ADMIN_KEY on ops to verify processing)",
        )
    base = os.environ.get("HONCHO_BASE_URL", "https://api.honcho.dev").rstrip("/")
    try:
        req = urllib.request.Request(
            f"{base}/deriver/metrics",
            headers={"Authorization": f"Bearer {admin}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            metrics = json.loads(resp.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        return (
            "WARN",
            f"Honcho deriver metrics unavailable ({exc}) — representation/chat may lag; storage/isolation still OK",
        )

    pending = metrics.get("deriver_queue_items_pending")
    oldest = metrics.get("deriver_queue_oldest_pending_age_seconds")
    if pending is not None and int(pending) > 0:
        extra = f", oldest pending {int(oldest)}s" if oldest is not None else ""
        return (
            "WARN",
            f"Honcho deriver queue not draining ({int(pending)} pending{extra}) — "
            "enable credits/instance setup for representation & chat memory; raw storage/isolation still work",
        )
    return None


def vm_check_script(expected_ws: str) -> str:
    import base64

    script = f"""#!/bin/bash
set +e
FAIL=0
ok() {{ echo "VM_PASS:$1"; }}
bad() {{ echo "VM_FAIL:$1"; FAIL=1; }}
EXPECTED={expected_ws!r}

if [ -x /root/.hermes/bin/hermes ] && test -f /usr/local/bin/feina-onboard && grep -q 'feina-stack install complete' /var/log/feina-bootstrap.log 2>/dev/null; then
  ok bootstrap
else
  bad bootstrap
fi

if test -s /root/.hermes/auth.json && python3 -c 'import json; json.load(open("/root/.hermes/auth.json"))' 2>/dev/null; then
  ok codex_auth
else
  bad codex_auth
fi

if grep -qE '^TELEGRAM_BOT_TOKEN=.' /root/.hermes/.env 2>/dev/null; then ok telegram_token; else bad telegram_token; fi
if supervisorctl status hermes-gateway 2>/dev/null | grep -q RUNNING; then ok gateway_running; else bad gateway_running; fi

WS=$(grep -E '^HONCHO_WORKSPACE_ID=' /root/.hermes/.env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"')
PYWS=$(python3 -c 'import json; print(json.load(open("/root/.hermes/honcho.json"))["hosts"]["hermes"]["workspace"])' 2>/dev/null || true)
if [ "$WS" = "$EXPECTED" ] || [ "$PYWS" = "$EXPECTED" ]; then ok honcho_workspace; else bad honcho_workspace; fi

if grep -qE '^AGENTMAIL_API_KEY=.' /root/.hermes/.env 2>/dev/null; then ok agentmail; else bad agentmail; fi
if grep -qE '^LATITUDE_API_KEY=.' /root/.hermes/.env 2>/dev/null; then ok latitude; else bad latitude; fi
if grep -qE '^COMPOSIO_CONSUMER_KEY=.' /root/.hermes/.env 2>/dev/null; then ok composio; else bad composio; fi
if grep -qE '^OPENAI_API_KEY=' /root/.hermes/.env /root/.env 2>/dev/null; then bad openai_api_key; else ok openai_api_key; fi
if grep -rE '^ORGO_API_KEY=|^ORGO_DEFAULT_COMPUTER_ID=' /root/.hermes/.env /root/.env 2>/dev/null | grep -q .; then bad orgo_keys; else ok orgo_keys; fi
if /usr/local/bin/feina-onboard safety-check >/dev/null 2>&1; then ok safety_check; else bad safety_check; fi
exit $FAIL
"""
    b64 = base64.b64encode(script.encode()).decode()
    return f"echo {b64} | base64 -d | bash"


def main() -> int:
    slug = sys.argv[1] if len(sys.argv) > 1 else ""
    if not slug:
        print("Usage: ready_check.py <client_slug>", file=sys.stderr)
        return 1

    api_key = os.environ.get("ORGO_API_KEY", "").strip()
    if not api_key:
        print("Set ORGO_API_KEY on Feina ops machine", file=sys.stderr)
        return 1
    api_base = os.environ.get("ORGO_API_BASE", "https://www.orgo.ai/api")

    state = load_launch(slug)
    computer_id = (state.get("computer_id") or "").strip()
    if not computer_id:
        print(f"FAIL: no computer_id in launch state for {slug} — finish launch-client.sh", file=sys.stderr)
        return 1

    expected = expected_workspace(slug)
    results: list[tuple[bool, str]] = []

    print(f"=== Feina ready-check: {safe_slug(slug)} (computer {computer_id}) ===\n")

    try:
        comp = orgo_get(api_base, api_key, f"/computers/{computer_id}")
        running = comp.get("status") == "running"
    except urllib.error.HTTPError as exc:
        running = False
        comp = {"status": f"error {exc.code}"}
    results.append((running, f"Orgo computer is running (status={comp.get('status', '?')})"))

    try:
        out = orgo_bash(api_base, api_key, computer_id, vm_check_script(expected))
    except (urllib.error.HTTPError, OrgoBashError) as exc:
        out = ""
        results.append((False, f"VM remote checks (Orgo bash failed: {exc})"))
    else:
        if not out.strip():
            results.append((False, "VM remote checks (empty output)"))
        for line in out.splitlines():
            if line.startswith("VM_PASS:"):
                results.append((True, line.removeprefix("VM_PASS:").replace("_", " ")))
            elif line.startswith("VM_FAIL:"):
                results.append((False, line.removeprefix("VM_FAIL:").replace("_", " ")))

    fail = 0
    for ok, label in results:
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {label}")
        if not ok:
            fail = 1

    deriver = honcho_deriver_warning()
    if deriver:
        level, msg = deriver
        print(f"[{level}] {msg}")
    else:
        print("[PASS] Honcho deriver queue processing (no backlog)")

    print()
    if fail:
        print("ready-check: FAILED — fix items above before the meeting")
        return 1
    print("ready-check: ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
