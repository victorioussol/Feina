#!/usr/bin/env bash
# Static checks for feina-stack client surface (run in CI or before release).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 -m py_compile build_template.py files/op-enable.py files/telegram-pair.py
python3 -c "import yaml; yaml.safe_load(open('files/config.yaml'))"
python3 build_template.py

FORBIDDEN='ORGO_API_KEY|orgo-mcp|agentphone-mcp|nicks-stack|Nick.s Stack'
if rg -i "$FORBIDDEN" files/config.yaml files/hermes.env files/bootstrap.sh files/gateway-run.sh files/SOUL.md 2>/dev/null; then
  echo "Forbidden pattern in core client config" >&2
  exit 1
fi

shellcheck -e SC1091 -x files/bootstrap.sh files/gateway-run.sh files/feina-onboard.sh \
  files/scripts/latitude/install_local_telemetry_patch.sh ops/launch-client.sh ops/offboard-client.sh

echo "verify-client-surface: OK"
