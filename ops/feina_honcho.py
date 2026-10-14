#!/usr/bin/env python3
"""Feina ops: per-client Honcho workspace isolation (Honcho v3 API).

Uses FEINA_HONCHO_ADMIN_KEY (admin / account key on ops only).
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
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_BASE = os.environ.get("HONCHO_BASE_URL", "https://api.honcho.dev").rstrip("/")
LEGACY_STATE_DIR = Path(
    os.environ.get("FEINA_HONCHO_STATE_DIR", os.path.expanduser("~/.feina/honcho-clients"))
)
SECRET_FIELD_RE = re.compile(
    r"(api[_-]?key|client[_-]?key|secret|token|password|authorization|bearer)$",
    re.I,
)
EXPORT_VERSION = 2
WORKSPACE_DELETE_TIMEOUT_S = int(os.environ.get("FEINA_HONCHO_WORKSPACE_DELETE_TIMEOUT", "120"))
WORKSPACE_DELETE_POLL_S = 5
SCOPED_KEY_REVOKE_NOTICE = (
    "Scoped key cannot be revoked via API; revoke/rotate in the Honcho dashboard "
    "(app.honcho.dev -> API Keys) if available."
)


class HonchoError(Exception):
    """Honcho API or export/teardown failure."""


def admin_key() -> str:
    v = os.environ.get("FEINA_HONCHO_ADMIN_KEY", "").strip()
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


def ws_path(workspace_id: str, suffix: str) -> str:
    base = f"/v3/workspaces/{urllib.parse.quote(workspace_id, safe='')}"
    return f"{base}{suffix}"


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


def require_http(status: int, data: Any, context: str, ok: tuple[int, ...] = (200,)) -> Any:
    if status not in ok:
        raise HonchoError(f"{context}: HTTP {status}: {data!r}")
    return data


def redact_secrets(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if SECRET_FIELD_RE.search(str(k)) or k in ("client_key", "provision_state"):
                out[k] = "[REDACTED]"
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(obj, list):
        return [redact_secrets(x) for x in obj]
    return obj


def list_items(
    token: str,
    path: str,
    context: str,
    page_size: int = 100,
    body_extra: dict | None = None,
) -> list[dict]:
    """Paginate Honcho v3 POST .../list endpoints; fail on any non-200."""
    items: list[dict] = []
    page = 1
    while True:
        body: dict[str, Any] = {"filters": {}, "page": page, "size": page_size}
        if body_extra:
            body.update(body_extra)
        status, data = request("POST", path, token, body=body)
        data = require_http(status, data, f"{context} page {page}")
        if not isinstance(data, dict):
            raise HonchoError(f"{context} page {page}: expected object, got {type(data)}")
        batch = data.get("items") or []
        for key in ("peers", "sessions", "messages", "conclusions", "keys"):
            if not batch:
                batch = data.get(key) or []
        if not isinstance(batch, list):
            raise HonchoError(f"{context} page {page}: invalid items list")
        for row in batch:
            if isinstance(row, dict):
                items.append(row)
        total_pages = data.get("pages") or data.get("total_pages")
        if total_pages is not None and page >= int(total_pages):
            break
        if len(batch) < page_size:
            break
        page += 1
        if page > 500:
            raise HonchoError(f"{context}: pagination exceeded 500 pages")
    return items


def list_workspace_items(token: str, workspace_id: str, resource: str) -> list[dict]:
    return list_items(
        token,
        ws_path(workspace_id, f"/{resource}/list"),
        f"workspace {workspace_id} {resource}/list",
    )


def list_session_messages(token: str, workspace_id: str, session_id: str) -> list[dict]:
    sid_q = urllib.parse.quote(str(session_id), safe="")
    return list_items(
        token,
        ws_path(workspace_id, f"/sessions/{sid_q}/messages/list"),
        f"session {session_id} messages/list",
    )


def optional_get(token: str, path: str, context: str) -> Any | None:
    status, data = request("GET", path, token)
    if status == 404:
        return None
    return require_http(status, data, context)


def build_memory_export(token: str, workspace_id: str, slug: str) -> dict:
    peers = list_workspace_items(token, workspace_id, "peers")
    sessions = list_workspace_items(token, workspace_id, "sessions")
    conclusions = list_workspace_items(token, workspace_id, "conclusions")

    messages_by_session: list[dict] = []
    for sess in sessions:
        sid = sess.get("id")
        if not sid:
            raise HonchoError(f"session row missing id: {sess!r}")
        messages_by_session.append(
            {
                "session_id": sid,
                "messages": list_session_messages(token, workspace_id, str(sid)),
            }
        )

    peer_context: list[dict] = []
    peer_representations: list[dict] = []
    for peer in peers:
        pid = peer.get("id")
        if not pid:
            raise HonchoError(f"peer row missing id: {peer!r}")
        pid_q = urllib.parse.quote(str(pid), safe="")
        ctx = optional_get(token, ws_path(workspace_id, f"/peers/{pid_q}/context"), f"peer {pid} context")
        if ctx is not None:
            peer_context.append({"peer_id": pid, "context": ctx})
        st, rep = request(
            "POST",
            ws_path(workspace_id, f"/peers/{pid_q}/representation"),
            token,
            body={},
        )
        if st == 200:
            peer_representations.append({"peer_id": pid, "representation": rep})
        elif st != 404:
            raise HonchoError(f"peer {pid} representation: HTTP {st}: {rep!r}")

    session_context: list[dict] = []
    for sess in sessions:
        sid = sess.get("id")
        if not sid:
            continue
        sid_q = urllib.parse.quote(str(sid), safe="")
        ctx = optional_get(
            token,
            ws_path(workspace_id, f"/sessions/{sid_q}/context"),
            f"session {sid} context",
        )
        if ctx is not None:
            session_context.append({"session_id": sid, "context": ctx})

    archive = {
        "feina_export_version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "workspace_id": workspace_id,
        "slug": slug,
        "honcho_base_url": DEFAULT_BASE,
        "peers": peers,
        "sessions": sessions,
        "messages_by_session": messages_by_session,
        "conclusions": conclusions,
        "peer_context": peer_context,
        "peer_representations": peer_representations,
        "session_context": session_context,
    }
    return redact_secrets(archive)


def write_export(path: str, archive: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(archive, indent=2, ensure_ascii=False) + "\n"
    out.write_text(text, encoding="utf-8")
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass


def run_export(token: str, workspace_id: str, slug: str, export_path: str) -> None:
    archive = build_memory_export(token, workspace_id, slug)
    write_export(export_path, archive)


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


def parse_mint_key_response(data: dict) -> str:
    for field in ("key", "api_key", "token", "secret"):
        if data.get(field):
            return str(data[field])
    raise SystemExit(f"Honcho create key: unexpected response shape (store key manually): {data!r}")


def mint_workspace_key(token: str, workspace_id: str) -> str:
    status, data = request(
        "POST",
        "/v3/keys",
        token,
        query={"workspace_id": workspace_id},
    )
    if status != 200:
        raise SystemExit(f"Honcho create workspace key failed ({status}): {data}")
    if not isinstance(data, dict):
        raise SystemExit(f"Honcho create key: expected object, got {data!r}")
    return parse_mint_key_response(data)


def _import_launch_state():
    ops = Path(__file__).resolve().parent
    if str(ops) not in sys.path:
        sys.path.insert(0, str(ops))
    from feina_launch_state import client_dir, honcho_path

    return client_dir, honcho_path


def state_path_for_slug(slug: str) -> Path:
    client_dir, honcho_path = _import_launch_state()
    new_path = honcho_path(slug)
    workspace_id = slug_to_workspace(slug)
    legacy = LEGACY_STATE_DIR / f"{workspace_id}.json"
    if new_path.is_file():
        return new_path
    if legacy.is_file():
        client_dir(slug)
        try:
            new_path.write_text(legacy.read_text())
            os.chmod(new_path, 0o600)
        except OSError:
            return legacy
        return new_path
    client_dir(slug)
    return new_path


def list_all_workspaces(token: str) -> list[dict]:
    return list_items(token, "/v3/workspaces/list", "workspaces/list")


def workspace_exists(token: str, workspace_id: str) -> bool:
    target = workspace_id.strip()
    for row in list_all_workspaces(token):
        wid = row.get("id") or row.get("workspace_id") or row.get("name")
        if wid is not None and str(wid) == target:
            return True
    return False


def wait_workspace_deleted(token: str, workspace_id: str) -> None:
    deadline = time.time() + WORKSPACE_DELETE_TIMEOUT_S
    while time.time() < deadline:
        if not workspace_exists(token, workspace_id):
            return
        time.sleep(WORKSPACE_DELETE_POLL_S)
    raise HonchoError(
        f"workspace {workspace_id} still present after {WORKSPACE_DELETE_TIMEOUT_S}s "
        "(async delete did not finish)"
    )


def delete_all_sessions(token: str, workspace_id: str) -> None:
    for row in list_workspace_items(token, workspace_id, "sessions"):
        sid = row.get("id")
        if not sid:
            raise HonchoError(f"session row missing id during teardown: {row!r}")
        status, data = request(
            "DELETE",
            ws_path(workspace_id, f"/sessions/{urllib.parse.quote(str(sid), safe='')}"),
            token,
        )
        require_http(status, data, f"delete session {sid}", ok=(200, 202, 204, 404))


def cmd_provision(args: argparse.Namespace) -> int:
    token = admin_key()
    workspace_id = slug_to_workspace(args.slug)
    sp = state_path_for_slug(args.slug)

    get_or_create_workspace(token, workspace_id, args.slug)
    client_key = None
    if sp.is_file() and not args.remint_key:
        try:
            saved = json.loads(sp.read_text())
            client_key = (saved.get("client_key") or "").strip() or None
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
        print(json.dumps(redact_secrets(out)))
    else:
        print(f"Honcho workspace: {workspace_id}")
        print(f"State file: {sp}")
        print("Store client_key in the client's 1Password item (Hermes Agent Secrets → HONCHO_API_KEY).")
        print("Never put FEINA_HONCHO_ADMIN_KEY on a client VM.")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    token = admin_key()
    workspace_id = slug_to_workspace(args.slug)
    try:
        run_export(token, workspace_id, args.slug, args.out)
    except HonchoError as exc:
        print(f"Honcho export failed: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote Honcho memory export to {args.out} (no secrets).")
    return 0


def cmd_teardown(args: argparse.Namespace) -> int:
    token = admin_key()
    workspace_id = slug_to_workspace(args.slug)
    sp = state_path_for_slug(args.slug)

    if args.dry_run:
        print(f"dry-run: would export (if --export) and delete workspace {workspace_id}")
        return 0

    export_path = (args.export or "").strip()
    export_succeeded = False
    if not args.force:
        if not export_path:
            print(
                "Refusing teardown: pass --export FILE (full memory archive) or --force to skip export.",
                file=sys.stderr,
            )
            return 1
        try:
            run_export(token, workspace_id, args.slug, export_path)
            export_succeeded = True
            print(f"Honcho memory export OK → {export_path}")
        except HonchoError as exc:
            print(f"Honcho export failed: {exc}", file=sys.stderr)
            return 1
    elif export_path:
        try:
            run_export(token, workspace_id, args.slug, export_path)
            export_succeeded = True
            print(f"Honcho memory export OK → {export_path}")
        except HonchoError as exc:
            print(f"WARN: export failed ({exc}); continuing due to --force", file=sys.stderr)

    if not args.force and not export_succeeded:
        print("Teardown aborted: export did not complete.", file=sys.stderr)
        return 1

    try:
        if workspace_exists(token, workspace_id):
            delete_all_sessions(token, workspace_id)
            status, data = request("DELETE", ws_path(workspace_id, ""), token)
            require_http(status, data, "delete workspace", ok=(200, 202, 204))
            wait_workspace_deleted(token, workspace_id)
        else:
            print(f"Honcho workspace {workspace_id} not in workspaces/list (already absent).")
    except HonchoError as exc:
        print(f"Honcho teardown failed: {exc}", file=sys.stderr)
        print(SCOPED_KEY_REVOKE_NOTICE)
        print("Keeping local ops state (honcho.json) until workspace is confirmed gone.", file=sys.stderr)
        return 1

    if workspace_exists(token, workspace_id):
        print(f"Honcho workspace {workspace_id} still appears in workspaces/list.", file=sys.stderr)
        print(SCOPED_KEY_REVOKE_NOTICE)
        print("Keeping local ops state (honcho.json) until workspace is confirmed gone.", file=sys.stderr)
        return 1

    print(SCOPED_KEY_REVOKE_NOTICE)
    if sp.is_file() and not args.keep_state:
        sp.unlink(missing_ok=True)
    print(f"Honcho workspace {workspace_id} confirmed removed from workspaces/list.")
    return 0


def orgo_computer_bash(
    api_base: str,
    orgo_key: str,
    computer_id: str,
    command: str,
    stdin_payload: str | None = None,
) -> None:
    url = f"{api_base.rstrip('/')}/computers/{computer_id}/bash"
    body: dict[str, Any] = {"command": command}
    if stdin_payload is not None:
        body["stdin"] = stdin_payload
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {orgo_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180):
        return


def cmd_push_config(args: argparse.Namespace) -> int:
    """Push Honcho client config to a client VM via Orgo bash API."""
    orgo_key = os.environ.get("ORGO_API_KEY", "").strip()
    if not orgo_key:
        raise SystemExit("ORGO_API_KEY required for push-config")
    api_base = os.environ.get("ORGO_API_BASE", "https://www.orgo.ai/api").rstrip("/")
    cid = args.computer_id

    workspace_id = slug_to_workspace(args.slug)
    sp = state_path_for_slug(args.slug)
    if not sp.is_file():
        raise SystemExit(f"No Honcho state for {workspace_id}; run provision first")
    saved = json.loads(sp.read_text())
    client_key = (saved.get("client_key") or "").strip()
    if not client_key:
        raise SystemExit("state file missing client_key")

    payload = {
        "workspace_id": workspace_id,
        "api_key": client_key,
        "peer_name": args.peer_name or "client",
        "ai_peer": "feina-agent",
    }
    payload_json = json.dumps(payload)
    receiver = "python3 /usr/local/bin/feina-honcho-push-receive.py"
    heredoc_cmd = (
        "set -euo pipefail\n"
        f"{receiver} <<'FEINA_HONCHO_EOF'\n"
        f"{payload_json}\n"
        "FEINA_HONCHO_EOF\n"
    )
    if "base64" in heredoc_cmd.lower():
        raise SystemExit("internal error: push-config must not use base64 on the VM")

    try:
        orgo_computer_bash(api_base, orgo_key, cid, receiver, stdin_payload=payload_json)
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 404, 422, 501):
            orgo_computer_bash(api_base, orgo_key, cid, heredoc_cmd)
        else:
            raise
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

    e = sub.add_parser("export", help="Export client Honcho memory to JSON (no secrets)")
    e.add_argument("--slug", required=True)
    e.add_argument("--out", required=True, metavar="FILE")
    e.set_defaults(func=cmd_export)

    t = sub.add_parser("teardown", help="Export memory (unless --force) and delete Honcho workspace")
    t.add_argument("--slug", required=True)
    t.add_argument("--export", metavar="FILE", help="Write JSON memory archive before delete")
    t.add_argument("--force", action="store_true", help="Delete workspace without exporting")
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
