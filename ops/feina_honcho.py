#!/usr/bin/env python3
"""Feina ops: per-client Honcho workspace isolation (Honcho v3 API).

Uses FEINA_HONCHO_ADMIN_KEY or HONCHO_ADMIN_API_KEY (admin / account key on ops only).
Workspace = hard isolation boundary (one workspace per client: feina-<slug>).
Mints workspace-scoped API keys via POST /v3/keys?workspace_id=... so client VMs
cannot read other clients' memory (Honcho docs: authentication at workspace level).

Refs: https://honcho.dev/docs/v3/documentation/core-concepts/architecture
      https://honcho.dev/docs/v3/api-reference/endpoint/keys/create-key
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE = os.environ.get("HONCHO_BASE_URL", "https://api.honcho.dev").rstrip("/")
STATE_DIR = Path(os.environ.get("FEINA_HONCHO_STATE_DIR", os.path.expanduser("~/.feina/honcho-clients")))


def admin_key() -> str:
    for name in ("FEINA_HONCHO_ADMIN_KEY", "HONCHO_ADMIN_API_KEY", "HONCHO_API_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    raise SystemExit(
        "Set FEINA_HONCHO_ADMIN_KEY (Honcho admin key) on the Feina ops machine."
    )


def slug_to_workspace(slug: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]", "-", slug.strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        raise SystemExit("invalid client slug")
    wid = f"feina-{s}"
    if len(wid) > 512:
        raise SystemExit("workspace id too long")
    return wid


def request(
    method: str,
    path: str,
    token: str,
    body: dict | None = None,
    query: dict | None = None,
) -> tuple[int, dict | list | str]:
    url = f"{DEFAULT_BASE}{path}"
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
    data = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            if not raw:
                return resp.status, {}
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": raw}
        return exc.code, payload


def get_or_create_workspace(token: str, workspace_id: str, slug: str) -> dict:
    status, data = request(
        "POST",
        "/v3/workspaces",
        token,
        body={
            "id": workspace_id,
            "metadata": {
                "feina_client_slug": slug,
                "feina_managed": "true",
            },
        },
    )
    if status not in (200, 201):
        raise SystemExit(f"Honcho workspace get-or-create failed ({status}): {data}")
    return data if isinstance(data, dict) else {"id": workspace_id}


def mint_workspace_key(token: str, workspace_id: str) -> str:
    status, data = request(
        "POST",
        "/v3/keys",
        token,
        query={"workspace_id": workspace_id},
    )
    if status != 200:
        raise SystemExit(f"Honcho create workspace key failed ({status}): {data}")
    if isinstance(data, dict):
        for field in ("key", "api_key", "token", "secret"):
            if data.get(field):
                return str(data[field])
    raise SystemExit(f"Honcho create key: unexpected response shape (store key manually): {data!r}")


def state_path(workspace_id: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"{workspace_id}.json"


def cmd_provision(args: argparse.Namespace) -> int:
    token = admin_key()
    workspace_id = slug_to_workspace(args.slug)
    sp = state_path(workspace_id)

    ws = get_or_create_workspace(token, workspace_id, args.slug)
    client_key = None
    if sp.is_file() and not args.remint_key:
        try:
            saved = json.loads(sp.read_text())
            client_key = saved.get("client_key", "").strip() or None
        except (OSError, json.JSONDecodeError):
            client_key = None
    if not client_key:
        client_key = mint_workspace_key(token, workspace_id)
        sp.write_text(
            json.dumps(
                {
                    "workspace_id": workspace_id,
                    "slug": args.slug,
                    "client_key": client_key,
                    "note": "Ops-only state; store client_key in client 1Password HONCHO_API_KEY",
                },
                indent=2,
            )
            + "\n"
        )
        try:
            os.chmod(sp, 0o600)
        except OSError:
            pass

    peer_name = args.peer_name or "client"
    out = {
        "workspace_id": workspace_id,
        "slug": args.slug,
        "peer_name": peer_name,
        "ai_peer": "feina-agent",
        "client_key": client_key,
        "state_file": str(sp),
    }
    if args.json:
        print(json.dumps(out))
    else:
        print(f"Honcho workspace: {workspace_id}")
        print(f"State file: {sp}")
        print("Store client_key in the client's 1Password item (Hermes Agent Secrets → HONCHO_API_KEY).")
        print("Never put FEINA_HONCHO_ADMIN_KEY on a client VM.")
    return 0


def list_sessions(token: str, workspace_id: str) -> list[str]:
    status, data = request(
        "POST",
        f"/v3/workspaces/{urllib.parse.quote(workspace_id, safe='')}/sessions/list",
        token,
        body={"filters": {}, "page": 1, "size": 100},
    )
    if status != 200 or not isinstance(data, dict):
        return []
    ids: list[str] = []
    for row in data.get("items") or data.get("sessions") or []:
        if isinstance(row, dict) and row.get("id"):
            ids.append(str(row["id"]))
    return ids


def cmd_teardown(args: argparse.Namespace) -> int:
    token = admin_key()
    workspace_id = slug_to_workspace(args.slug)
    sp = state_path(workspace_id)

    export = {
        "workspace_id": workspace_id,
        "slug": args.slug,
        "action": "teardown",
    }
    if sp.is_file():
        try:
            export["provision_state"] = json.loads(sp.read_text())
        except (OSError, json.JSONDecodeError):
            pass

    if args.export:
        Path(args.export).write_text(json.dumps(export, indent=2) + "\n")
        print(f"Wrote export metadata to {args.export} (no message bodies).")
        if args.dry_run:
            return 0

    if args.dry_run:
        print(f"dry-run: would delete sessions + workspace {workspace_id}")
        return 0

    for sid in list_sessions(token, workspace_id):
        request(
            "DELETE",
            f"/v3/workspaces/{urllib.parse.quote(workspace_id, safe='')}/sessions/{urllib.parse.quote(sid, safe='')}",
            token,
        )
    status, data = request(
        "DELETE",
        f"/v3/workspaces/{urllib.parse.quote(workspace_id, safe='')}",
        token,
    )
    if status not in (200, 202, 204, 404):
        print(f"workspace delete returned {status}: {data}", file=sys.stderr)
        return 1
    if sp.is_file() and not args.keep_state:
        sp.unlink(missing_ok=True)
    print(f"Honcho workspace {workspace_id} teardown requested (async cascade).")
    print("Revoke the client workspace key in Honcho dashboard if it still appears.")
    return 0


def cmd_push_config(args: argparse.Namespace) -> int:
    """Push Honcho client config to a client VM via Orgo bash API."""
    import base64
    import subprocess

    orgo_key = os.environ.get("ORGO_API_KEY", "").strip()
    if not orgo_key:
        raise SystemExit("ORGO_API_KEY required for push-config")
    api_base = os.environ.get("ORGO_API_BASE", "https://www.orgo.ai/api").rstrip("/")
    cid = args.computer_id

    workspace_id = slug_to_workspace(args.slug)
    sp = state_path(workspace_id)
    if not sp.is_file():
        raise SystemExit(f"No Honcho state for {workspace_id}; run provision first")
    saved = json.loads(sp.read_text())
    client_key = saved.get("client_key", "").strip()
    if not client_key:
        raise SystemExit("state file missing client_key")

    payload = {
        "workspace_id": workspace_id,
        "api_key": client_key,
        "peer_name": args.peer_name or "client",
        "ai_peer": "feina-agent",
    }
    b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    remote = f"echo {b64} | base64 -d | python3 /usr/local/bin/feina-honcho-apply.py"
    subprocess.run(
        [
            "curl",
            "-fsS",
            "-X",
            "POST",
            f"{api_base}/computers/{cid}/bash",
            "-H",
            f"Authorization: Bearer {orgo_key}",
            "-H",
            "Content-Type: application/json",
            "-d",
            json.dumps({"command": remote}),
        ],
        check=True,
    )
    print(f"Pushed Honcho config to computer {cid} (workspace {workspace_id}).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Feina Honcho per-client isolation (ops)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("provision", help="Get-or-create workspace + workspace-scoped client key")
    p.add_argument("--slug", required=True)
    p.add_argument("--peer-name", default="client")
    p.add_argument("--json", action="store_true")
    p.add_argument("--remint-key", action="store_true", help="Mint a new client key even if state exists")
    p.set_defaults(func=cmd_provision)

    t = sub.add_parser("teardown", help="Export metadata and delete Honcho workspace")
    t.add_argument("--slug", required=True)
    t.add_argument("--export", metavar="FILE", help="Write JSON export path")
    t.add_argument("--dry-run", action="store_true")
    t.add_argument("--keep-state", action="store_true")
    t.set_defaults(func=cmd_teardown)

    u = sub.add_parser("push-config", help="Apply Honcho config on client VM via Orgo bash")
    u.add_argument("--slug", required=True)
    u.add_argument("--computer-id", required=True)
    u.add_argument("--peer-name", default="client")
    u.set_defaults(func=cmd_push_config)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
