#!/usr/bin/env bash
# Feina ops ONLY — offboard a client (destructive). Requires explicit approval.
set -euo pipefail

API_BASE="${ORGO_API_BASE:-https://www.orgo.ai/api}"
API_KEY="${ORGO_API_KEY:?Set ORGO_API_KEY on Feina ops machine}"
OPS_DIR="$(cd "$(dirname "$0")" && pwd)"

CID="${1:?Usage: offboard-client.sh <computer_id> [--slug <client_slug>] [--delete-computer] [--honcho-teardown] [--honcho-export FILE] [--honcho-force]}"

SLUG=""
DELETE=0
HONCHO_TEARDOWN=0
HONCHO_EXPORT=""
HONCHO_FORCE=0

shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --slug) SLUG="${2:?}"; shift 2 ;;
    --delete-computer) DELETE=1; shift ;;
    --honcho-teardown) HONCHO_TEARDOWN=1; shift ;;
    --honcho-export) HONCHO_EXPORT="${2:?}"; shift 2 ;;
    --honcho-force) HONCHO_FORCE=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

auth_hdr=(-H "Authorization: Bearer ${API_KEY}" -H "Content-Type: application/json")

echo "Export vault hint (run on computer before delete if client wants data):"
echo "  tar czf /tmp/hermes-vault.tgz -C /root/Documents HermesVault"
echo ""
echo "Revoke keys out of band: Composio, AgentMail, Latitude, 1Password vault, Telegram bot."
echo "Honcho: scoped workspace keys cannot be revoked via API — after export/teardown,"
echo "  revoke or rotate in the Honcho dashboard (app.honcho.dev -> API Keys) if available."
echo ""

if [ -n "$SLUG" ] && [ -n "${FEINA_HONCHO_ADMIN_KEY:-}" ]; then
  if [ -n "$HONCHO_EXPORT" ] && [ "$HONCHO_TEARDOWN" -eq 0 ]; then
    python3 "${OPS_DIR}/feina_honcho.py" export --slug "$SLUG" --out "$HONCHO_EXPORT"
  fi
  if [ "$HONCHO_TEARDOWN" -eq 1 ]; then
    TEARDOWN_ARGS=(teardown --slug "$SLUG")
    if [ "$HONCHO_FORCE" -eq 1 ]; then
      TEARDOWN_ARGS+=(--force)
      [ -n "$HONCHO_EXPORT" ] && TEARDOWN_ARGS+=(--export "$HONCHO_EXPORT")
    else
      if [ -z "$HONCHO_EXPORT" ]; then
        echo "ERROR: --honcho-export FILE is required for Honcho teardown (or pass --honcho-force)." >&2
        exit 1
      fi
      TEARDOWN_ARGS+=(--export "$HONCHO_EXPORT")
    fi
    python3 "${OPS_DIR}/feina_honcho.py" "${TEARDOWN_ARGS[@]}"
  fi
elif [ -n "$SLUG" ] && { [ "$HONCHO_TEARDOWN" -eq 1 ] || [ -n "$HONCHO_EXPORT" ]; }; then
  echo "WARN: FEINA_HONCHO_ADMIN_KEY not set — skip Honcho teardown/export"
fi

if [ "$DELETE" -eq 1 ]; then
  echo "Deleting Orgo computer ${CID}…"
  curl -fsS -X DELETE "${auth_hdr[@]}" "${API_BASE}/computers/${CID}"
  echo "Deleted."
else
  echo "Dry run — pass --delete-computer to remove the VM."
  echo "Honcho: --slug <slug> --honcho-export /path/archive.json [--honcho-teardown] (export required unless --honcho-force)"
fi
