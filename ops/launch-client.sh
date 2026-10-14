#!/usr/bin/env bash
# Feina ops ONLY — never run on a client computer.
# Phased, resumable launch: A (Honcho/prep) → B (capacity) → C (VM + bootstrap + Honcho push).
# State: ~/.feina/clients/<slug>/launch.json
set -euo pipefail

OPS_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_ID="${1:?Usage: launch-client.sh <workspace_id> <client_slug> [ram_gb] [cpu]}"
SLUG="${2:?client slug e.g. vince}"
RAM="${3:-8}"
CPU="${4:-2}"

exec python3 "${OPS_DIR}/feina_launch.py" run "$WORKSPACE_ID" "$SLUG" --ram "$RAM" --cpu "$CPU"
