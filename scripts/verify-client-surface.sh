#!/usr/bin/env bash
# Static checks for feina-stack client surface (run in CI or before release).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 -m py_compile build_template.py files/op-enable.py files/telegram-pair.py
python3 -c "import yaml; yaml.safe_load(open('files/config.yaml'))"
python3 build_template.py

if rg -n '^ORGO_API_KEY=|^ORGO_DEFAULT_COMPUTER_ID=' files/hermes.env 2>/dev/null; then
  echo "ORGO keys must not appear in baked hermes.env" >&2
  exit 1
fi
if rg -i 'nicks-stack|Nick.s Stack' files/config.yaml files/hermes.env files/SOUL.md 2>/dev/null; then
  echo "Forbidden Nick stack branding in client config" >&2
  exit 1
fi
python3 - <<'PY'
import yaml
c=yaml.safe_load(open('files/config.yaml'))
o=(c.get('mcp_servers') or {}).get('orgo') or {}
assert o.get('enabled') is False, 'orgo MCP must ship disabled'
assert 'env' not in o or not o.get('env'), 'orgo MCP must not wire ORGO_* env on clients'
PY

python3 -m py_compile files/feina-enable.py
shellcheck -e SC1091 -x files/bootstrap.sh files/gateway-run.sh files/feina-onboard.sh files/feina \
  files/scripts/latitude/install_local_telemetry_patch.sh ops/launch-client.sh ops/offboard-client.sh

echo "verify-client-surface: OK"
