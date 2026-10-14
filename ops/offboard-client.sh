#!/usr/bin/env bash
# Feina ops ONLY — offboard a client (destructive). Requires explicit approval.
set -euo pipefail

API_BASE="${ORGO_API_BASE:-https://www.orgo.ai/api}"
API_KEY="${ORGO_API_KEY:?Set ORGO_API_KEY on Feina ops machine}"
CID="${1:?Usage: offboard-client.sh <computer_id> [--delete-computer]}"

auth_hdr=(-H "Authorization: Bearer ${API_KEY}" -H "Content-Type: application/json")

echo "Export vault hint (run on computer before delete if client wants data):"
echo "  tar czf /tmp/hermes-vault.tgz -C /root/Documents HermesVault"
echo ""
echo "Revoke keys out of band: OpenRouter, Composio, AgentMail, Latitude, 1Password vault, Telegram bot."
echo ""

if [ "${2:-}" = "--delete-computer" ]; then
  echo "Deleting Orgo computer ${CID}…"
  curl -fsS -X DELETE "${auth_hdr[@]}" "${API_BASE}/computers/${CID}"
  echo "Deleted."
else
  echo "Dry run — pass --delete-computer to remove the VM."
fi
