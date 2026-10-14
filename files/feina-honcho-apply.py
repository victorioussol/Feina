#!/usr/bin/env python3
"""Apply per-client Honcho workspace config on a Feina client VM (stdin JSON)."""
from __future__ import annotations

import json
import os
import sys

HERMES_HOME = os.environ.get("HERMES_HOME", "/root/.hermes")
ENV_FILE = f"{HERMES_HOME}/.env"
HONCHO_JSON = f"{HERMES_HOME}/honcho.json"


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        print("Expected JSON on stdin: workspace_id, api_key, peer_name, ai_peer", file=sys.stderr)
        return 1
    data = json.loads(raw)
    workspace_id = str(data["workspace_id"]).strip()
    api_key = str(data["api_key"]).strip()
    peer_name = str(data.get("peer_name") or "client").strip()
    ai_peer = str(data.get("ai_peer") or "feina-agent").strip()

    os.makedirs(HERMES_HOME, mode=0o700, exist_ok=True)
    cfg = {
        "hosts": {
            "hermes": {
                "enabled": True,
                "workspace": workspace_id,
                "aiPeer": ai_peer,
                "peerName": peer_name,
            }
        }
    }
    with open(HONCHO_JSON, "w") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    os.chmod(HONCHO_JSON, 0o600)

    lines: list[str] = []
    try:
        with open(ENV_FILE) as fh:
            for line in fh:
                if line.startswith(("HONCHO_API_KEY=", "HONCHO_WORKSPACE_ID=")):
                    continue
                lines.append(line.rstrip("\n"))
    except OSError:
        pass
    lines.append(f"HONCHO_WORKSPACE_ID={workspace_id}")
    lines.append(f"HONCHO_API_KEY={api_key}")
    with open(ENV_FILE, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(ENV_FILE, 0o600)

    print(f"Honcho configured: workspace={workspace_id} peerName={peer_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
