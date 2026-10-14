#!/usr/bin/env bash
# Feina ops ONLY — never run on a client computer.
# Lists capacity and workspace computers, then creates a VM (no auto-purchase).
set -euo pipefail

API_BASE="${ORGO_API_BASE:-https://www.orgo.ai/api}"
API_KEY="${ORGO_API_KEY:?Set ORGO_API_KEY on Feina ops machine (account-wide key)}"
WORKSPACE_ID="${1:?Usage: launch-client.sh <workspace_id> <client_slug> [ram_gb] [cpu]}"
SLUG="${2:?client slug e.g. vince}"
RAM="${3:-8}"
CPU="${4:-2}"
NAME="feina-${SLUG}"
REF="${FEINA_STACK_REF:-feina}"
OPS_DIR="$(cd "$(dirname "$0")" && pwd)"

auth_hdr=(-H "Authorization: Bearer ${API_KEY}" -H "Content-Type: application/json")

python3 - "$API_BASE" "$API_KEY" "$WORKSPACE_ID" "$RAM" "$CPU" "$NAME" <<'PY'
import json, sys, urllib.error, urllib.request

api_base, api_key, workspace_id, ram_s, cpu_s, new_name = sys.argv[1:7]
ram = int(ram_s)
cpu = float(cpu_s)

def get(path: str):
    req = urllib.request.Request(
        f"{api_base.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())

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

try:
    capacity = get("/account/capacity")
except urllib.error.HTTPError as exc:
    body = exc.read().decode(errors="replace")
    print(f"needs human approval: could not read account capacity ({exc.code}): {body}", file=sys.stderr)
    sys.exit(2)

try:
    workspace = get(f"/workspaces/{workspace_id}")
except urllib.error.HTTPError as exc:
    body = exc.read().decode(errors="replace")
    print(f"needs human approval: could not read workspace ({exc.code}): {body}", file=sys.stderr)
    sys.exit(2)

desktops = workspace.get("desktops") or []
print("=== Orgo workspace computers ===")
print(f"workspace: {workspace.get('name', workspace_id)}  owner_tier={workspace.get('owner_tier', '?')}")
for d in desktops:
    print(f"  - {d.get('name', '?')}  id={d.get('id', '?')}  status={d.get('status', '?')}")

comp = capacity.get("computers") or {}
ram_pool = capacity.get("ram_gb") or {}
plan = capacity.get("plan", "?")
in_use = comp.get("in_use")
limit = comp.get("limit")
print("")
print(f"Account plan: {plan}")
print(f"Computers: {in_use}/{limit} in use")
print(f"RAM pool: {ram_pool.get('in_use')}/{ram_pool.get('limit')} GB in use")

size = size_for_ram(ram)
can_add = (capacity.get("can_add") or {}).get(size, 0)
print(f"can_add.{size} (for {ram} GB RAM request): {can_add}")

if limit is not None and in_use is not None and in_use >= limit:
    print("", file=sys.stderr)
    print("needs human approval: no free slot (computer limit reached).", file=sys.stderr)
    print("Do not auto-purchase or upgrade. Free a computer or ask Orgo to raise capacity.", file=sys.stderr)
    sys.exit(2)

if can_add is not None and can_add <= 0:
    print("", file=sys.stderr)
    print("needs human approval: no free slot (can_add is 0 for this size).", file=sys.stderr)
    print("Do not auto-purchase or upgrade. Review /account/capacity or retire an existing computer.", file=sys.stderr)
    sys.exit(2)

ram_limit = ram_pool.get("limit")
ram_in_use = ram_pool.get("in_use") or 0
if ram_limit is not None and ram_in_use + ram > ram_limit:
    print("", file=sys.stderr)
    print("needs human approval: no free slot (RAM pool would be exceeded).", file=sys.stderr)
    sys.exit(2)

print("")
print(f"Preflight OK — may create computer {new_name!r} ({ram} GB RAM, {cpu} vCPU).")
PY

echo "Creating computer ${NAME}…"
BODY=$(python3 -c "import json; print(json.dumps({'workspace_id':'$WORKSPACE_ID','name':'$NAME','ram':$RAM,'cpu':$CPU,'disk_size_gb':40}))")
RESP=$(curl -fsS "${auth_hdr[@]}" -d "$BODY" "${API_BASE}/computers")
CID=$(python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" <<<"$RESP")
echo "Computer id: $CID"

if [ -n "${FEINA_HONCHO_ADMIN_KEY:-}" ]; then
  echo "=== Honcho per-client workspace (provision) ==="
  python3 "${OPS_DIR}/feina_honcho.py" provision --slug "${SLUG}"
else
  echo "WARN: FEINA_HONCHO_ADMIN_KEY not set — skipping Honcho workspace provision."
fi

echo "Waiting for running state…"
for _ in $(seq 1 60); do
  ST=$(curl -fsS "${auth_hdr[@]}" "${API_BASE}/computers/${CID}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
  [ "$ST" = "running" ] && break
  sleep 5
done

REMOTE="mkdir -p /opt/feina-stack && (test -d /opt/feina-stack/src/.git || git clone --depth 1 -b ${REF} https://github.com/victorioussol/Feina /opt/feina-stack/src) && nohup bash /opt/feina-stack/src/files/bootstrap.sh >> /var/log/feina-bootstrap.log 2>&1 &"
echo "Starting bootstrap (detached)…"
curl -fsS "${auth_hdr[@]}" -d "$(python3 -c "import json; print(json.dumps({'command':'''$REMOTE'''}))")" \
  "${API_BASE}/computers/${CID}/bash" || true

echo ""
echo "Done. Next (Feina pre-setup on the VM):"
echo "  tail -f /var/log/feina-bootstrap.log"
echo "  feina-onboard setup-pre"
if [ -n "${FEINA_HONCHO_ADMIN_KEY:-}" ]; then
  echo "After bootstrap, push isolated Honcho config to the VM:"
  echo "  python3 ${OPS_DIR}/feina_honcho.py push-config --slug ${SLUG} --computer-id ${CID}"
  echo "Copy the workspace-scoped HONCHO_API_KEY into the client's 1Password vault (never the admin key)."
fi
echo "Computer id: $CID"
