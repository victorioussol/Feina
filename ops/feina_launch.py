#!/usr/bin/env python3
"""Feina ops: phased, resumable client launch (A → B → C)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OPS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(OPS_DIR))

from feina_launch_state import (  # noqa: E402
    load_launch,
    mark_phase,
    phase_done,
    safe_slug,
    save_launch,
)

NO_SLOT_TEMPLATE = (
    "Unable to create the new Orgo computer for {slug}: no free slot. "
    "Buy or free a computer in Orgo, then re-run."
)


def orgo_request(api_base: str, api_key: str, method: str, path: str, body: dict | None = None) -> dict:
    url = f"{api_base.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}


def orgo_get(api_base: str, api_key: str, path: str) -> dict:
    return orgo_request(api_base, api_key, "GET", path)


def size_for_ram(ram_gb: int) -> str:
    if ram_gb <= 4:
        return "small"
    if ram_gb <= 8:
        return "medium"
    if ram_gb <= 16:
        return "large"
    if ram_gb <= 32:
        return "xl"
    return "2xl"


def capacity_ok(api_base: str, api_key: str, workspace_id: str, slug: str, ram: int) -> bool:
    try:
        capacity = orgo_get(api_base, api_key, "/account/capacity")
        workspace = orgo_get(api_base, api_key, f"/workspaces/{workspace_id}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"Orgo API error ({exc.code}): {body}", file=sys.stderr)
        sys.exit(2)

    desktops = workspace.get("desktops") or []
    print("=== Orgo workspace computers ===")
    print(f"workspace: {workspace.get('name', workspace_id)}  owner_tier={workspace.get('owner_tier', '?')}")
    for d in desktops:
        print(f"  - {d.get('name', '?')}  id={d.get('id', '?')}  status={d.get('status', '?')}")

    comp = capacity.get("computers") or {}
    ram_pool = capacity.get("ram_gb") or {}
    print("")
    print(f"Account plan: {capacity.get('plan', '?')}")
    print(f"Computers: {comp.get('in_use')}/{comp.get('limit')} in use")
    print(f"RAM pool: {ram_pool.get('in_use')}/{ram_pool.get('limit')} GB in use")

    size = size_for_ram(ram)
    can_add = (capacity.get("can_add") or {}).get(size, 0)
    print(f"can_add.{size} (for {ram} GB RAM): {can_add}")

    limit = comp.get("limit")
    in_use = comp.get("in_use")
    no_slot = False
    if limit is not None and in_use is not None and in_use >= limit:
        no_slot = True
    if can_add is not None and can_add <= 0:
        no_slot = True
    ram_limit = ram_pool.get("limit")
    ram_in_use = ram_pool.get("in_use") or 0
    if ram_limit is not None and ram_in_use + ram > ram_limit:
        no_slot = True

    if no_slot:
        print(NO_SLOT_TEMPLATE.format(slug=slug), file=sys.stderr)
        return False
    print("")
    print(f"Preflight OK — may create computer feina-{slug!r} ({ram} GB RAM).")
    return True


def find_computer_id(
    api_base: str, api_key: str, workspace_id: str, name: str, saved_id: str | None
) -> str | None:
    if saved_id:
        try:
            comp = orgo_get(api_base, api_key, f"/computers/{saved_id}")
            if comp.get("id"):
                return str(comp["id"])
        except urllib.error.HTTPError:
            pass
    workspace = orgo_get(api_base, api_key, f"/workspaces/{workspace_id}")
    for d in workspace.get("desktops") or []:
        if d.get("name") == name and d.get("id"):
            return str(d["id"])
    return None


def wait_running(api_base: str, api_key: str, computer_id: str) -> None:
    print("Waiting for running state…")
    for _ in range(60):
        comp = orgo_get(api_base, api_key, f"/computers/{computer_id}")
        if comp.get("status") == "running":
            return
        time.sleep(5)
    print("WARN: computer not running yet — re-run launch to continue", file=sys.stderr)


def orgo_bash(api_base: str, api_key: str, computer_id: str, command: str) -> str:
    out = orgo_request(
        api_base,
        api_key,
        "POST",
        f"/computers/{computer_id}/bash",
        {"command": command},
    )
    if isinstance(out, dict):
        return str(out.get("output") or out.get("stdout") or "")
    return str(out)


def remote_test(api_base: str, api_key: str, computer_id: str, shell_cmd: str) -> bool:
    wrapped = f"bash -lc \"{shell_cmd} && echo FEINA_CHECK_OK\""
    try:
        raw = orgo_bash(api_base, api_key, computer_id, wrapped)
    except urllib.error.HTTPError:
        return False
    return "FEINA_CHECK_OK" in raw


def start_bootstrap(api_base: str, api_key: str, computer_id: str, ref: str) -> None:
    remote = (
        "mkdir -p /opt/feina-stack && "
        f"(test -d /opt/feina-stack/src/.git || git clone --depth 1 -b {ref} "
        "https://github.com/victorioussol/Feina /opt/feina-stack/src) && "
        "nohup bash /opt/feina-stack/src/files/bootstrap.sh >> /var/log/feina-bootstrap.log 2>&1 &"
    )
    orgo_bash(api_base, api_key, computer_id, remote)


def cmd_run(args: argparse.Namespace) -> int:
    api_base = os.environ.get("ORGO_API_BASE", "https://www.orgo.ai/api")
    api_key = os.environ.get("ORGO_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Set ORGO_API_KEY on Feina ops machine")

    slug = safe_slug(args.slug)
    name = f"feina-{slug}"
    ref = os.environ.get("FEINA_STACK_REF", "feina")
    state = load_launch(slug)
    state["slug"] = slug
    state["orgo_workspace_id"] = args.workspace_id
    state["ram"] = args.ram
    state["cpu"] = args.cpu
    state["computer_name"] = name

    # --- Phase A (no computer) ---
    if not phase_done(state, "a"):
        print("=== Phase A: Honcho workspace + prep ===")
        if os.environ.get("FEINA_HONCHO_ADMIN_KEY", "").strip():
            subprocess.run(
                [sys.executable, str(OPS_DIR / "feina_honcho.py"), "provision", "--slug", slug],
                check=True,
            )
            state = mark_phase(state, "a", honcho=True)
        else:
            print("WARN: FEINA_HONCHO_ADMIN_KEY not set — skipping Honcho workspace provision.")
            state = mark_phase(state, "a", honcho=False)
        save_launch(slug, state)
    else:
        print("Phase A: already complete (skip)")

    computer_id = state.get("computer_id") or find_computer_id(
        api_base, api_key, args.workspace_id, name, state.get("computer_id")
    )

    # --- Phase B: capacity (only when we still need a computer) ---
    if not computer_id:
        print("=== Phase B: Orgo capacity ===")
        if not capacity_ok(api_base, api_key, args.workspace_id, slug, args.ram):
            save_launch(slug, state)
            return 2
        state = mark_phase(state, "b")
        save_launch(slug, state)

        print("=== Phase C: create computer ===")
        body = {
            "workspace_id": args.workspace_id,
            "name": name,
            "ram": args.ram,
            "cpu": args.cpu,
            "disk_size_gb": 40,
        }
        created = orgo_request(api_base, api_key, "POST", "/computers", body)
        computer_id = str(created["id"])
        print(f"Computer id: {computer_id}")
        state["computer_id"] = computer_id
        phases = state.setdefault("phases", {})
        phases["c"] = {
            "started_at": phases.get("c", {}).get("started_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "computer_id": computer_id,
            "bootstrap_started": False,
            "bootstrap_done": False,
            "honcho_pushed": False,
        }
        save_launch(slug, state)
    else:
        print(f"Phase B/C: reusing computer {computer_id}")
        state["computer_id"] = computer_id
        save_launch(slug, state)

    wait_running(api_base, api_key, computer_id)

    phases_c = (state.get("phases") or {}).setdefault("c", {})
    if not phases_c.get("bootstrap_started"):
        print("Starting bootstrap (detached)…")
        start_bootstrap(api_base, api_key, computer_id, ref)
        phases_c["bootstrap_started"] = True
        save_launch(slug, state)

    boot_cmd = (
        "command -v hermes >/dev/null && test -f /usr/local/bin/feina-onboard.sh && "
        "grep -q 'feina-stack install complete' /var/log/feina-bootstrap.log"
    )
    if not phases_c.get("bootstrap_done"):
        if remote_test(api_base, api_key, computer_id, boot_cmd):
            phases_c["bootstrap_done"] = True
            save_launch(slug, state)
            print("Bootstrap: complete")
        else:
            print("Bootstrap: in progress — tail /var/log/feina-bootstrap.log on VM; re-run launch to continue.")
            print(f"Computer id: {computer_id}")
            return 0

    if os.environ.get("FEINA_HONCHO_ADMIN_KEY", "").strip() and not phases_c.get("honcho_pushed"):
        print("Pushing Honcho config to VM…")
        subprocess.run(
            [
                sys.executable,
                str(OPS_DIR / "feina_honcho.py"),
                "push-config",
                "--slug",
                slug,
                "--computer-id",
                computer_id,
            ],
            check=True,
        )
        phases_c["honcho_pushed"] = True
        phases_c["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state.setdefault("phases", {})["c"] = phases_c
        save_launch(slug, state)
    elif phases_c.get("honcho_pushed"):
        print("Honcho push: already done (skip)")

    print("")
    print("Launch complete. Next on the VM:")
    print("  tail -f /var/log/feina-bootstrap.log")
    print("  feina-onboard setup-pre")
    print(f"Computer id: {computer_id}")
    print(f"Ops state: ~/.feina/clients/{slug}/launch.json")
    print(f"Day-before check: ops/ready-check.sh {slug}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Feina phased client launch")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="Run phases A→B→C (idempotent)")
    run.add_argument("workspace_id")
    run.add_argument("slug")
    run.add_argument("--ram", type=int, default=8)
    run.add_argument("--cpu", type=float, default=2.0)
    run.set_defaults(func=cmd_run)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
