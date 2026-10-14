#!/usr/bin/env bash
# Feina ops ONLY — never run on a client computer.
# Creates an Orgo computer and starts feina-stack bootstrap over the bash API.
set -euo pipefail

API_BASE="${ORGO_API_BASE:-https://www.orgo.ai/api}"
API_KEY="${ORGO_API_KEY:?Set ORGO_API_KEY on Feina ops machine}"
WORKSPACE_ID="${1:?Usage: launch-client.sh <workspace_id> <client_slug> [ram_gb] [cpu]}"
SLUG="${2:?client slug e.g. vince}"
RAM="${3:-8}"
CPU="${4:-2}"
NAME="feina-${SLUG}"
REF="${FEINA_STACK_REF:-feina}"

auth_hdr=(-H "Authorization: Bearer ${API_KEY}" -H "Content-Type: application/json")

echo "Creating computer ${NAME}…"
BODY=$(python3 -c "import json; print(json.dumps({'workspace_id':'$WORKSPACE_ID','name':'$NAME','ram':$RAM,'cpu':$CPU,'disk_size_gb':40}))")
RESP=$(curl -fsS "${auth_hdr[@]}" -d "$BODY" "${API_BASE}/computers")
CID=$(python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" <<<"$RESP")
echo "Computer id: $CID"

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
echo "Done. Poll on the computer:"
echo "  tail -f /var/log/feina-bootstrap.log"
echo "  feina-onboard status"
echo "Computer id: $CID"
