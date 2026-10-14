#!/usr/bin/env bash
# Static checks for feina-stack client surface (run in CI or before release).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
FILES_DIR="$ROOT/files"

python3 -m py_compile build_template.py files/op-enable.py files/telegram-pair.py files/feina-enable.py
python3 -c "import yaml; yaml.safe_load(open('files/config.yaml'))"
python3 build_template.py

# Allowlisted paths: ORGO strip helpers, blocked upstream plugin trees, MIT author credit.
VERIFY_ALLOW_GLOBS=(
  '!files/bootstrap.sh'
  '!files/feina-onboard.sh'
  '!files/hermes.env'
  '!files/scripts/orgo_desktop/**'
  '!files/plugins/orgo-desktop-local/plugin.yaml'
  '!files/skills/computer-use/**'
)

# Operator / legacy stack tokens (substring scan).
if rg -i -n "${VERIFY_ALLOW_GLOBS[@]}" \
  'dewey|opticalresources|nickv|tiger@orgo|momentumamp|spencer@orgo|nickv@testkey|granola_mcp|hermes mcp add orgo' \
  "$FILES_DIR" 2>/dev/null; then
  echo "Banned operator/Orgo pattern under files/" >&2
  exit 1
fi
if rg -n "${VERIFY_ALLOW_GLOBS[@]}" 'ORGO_API_KEY|ORGO_DEFAULT_COMPUTER_ID' "$FILES_DIR" 2>/dev/null; then
  echo "ORGO key literal under files/ (outside allowlist)" >&2
  exit 1
fi
# Personal-name scan (substring; MIT author line allowlisted above).
if rg -i -n "${VERIFY_ALLOW_GLOBS[@]}" 'nick' "$FILES_DIR" 2>/dev/null; then
  echo "Banned personal-name pattern 'nick' under files/ (outside allowlist)" >&2
  exit 1
fi

if rg -n '^ORGO_API_KEY=|^ORGO_DEFAULT_COMPUTER_ID=' "$FILES_DIR/hermes.env" 2>/dev/null; then
  echo "ORGO keys must not appear in baked hermes.env" >&2
  exit 1
fi
if rg -i 'nicks-stack|Nick.s Stack' "$FILES_DIR/config.yaml" "$FILES_DIR/hermes.env" "$FILES_DIR/SOUL.md" 2>/dev/null; then
  echo "Forbidden Nick stack branding in client config" >&2
  exit 1
fi

python3 - <<'PY'
import yaml
c = yaml.safe_load(open("files/config.yaml"))
o = (c.get("mcp_servers") or {}).get("orgo") or {}
assert o.get("enabled") is False, "orgo MCP must ship disabled"
assert not o.get("env"), "orgo MCP must not wire ORGO_* env on clients"
pe = c.get("plugins") or {}
en = set(pe.get("enabled") or [])
dis = set(pe.get("disabled") or [])
for plug in ("openrouter", "openrouter-provider", "anthropic-provider"):
    assert plug not in en, f"{plug} must be disabled for MVP"
    assert plug in dis, f"{plug} must be in plugins.disabled"
assert c.get("model", {}).get("provider") == "openai-codex"
assert c.get("fallback_model") is None
prov = c.get("providers") or {}
for pname in ("vercel-ai-gateway", "meta-model-api"):
    p = prov.get(pname) or {}
    assert p.get("enabled") is False, f"provider {pname} must ship disabled for MVP"
drop = {"computer_use", "orgo_desktop", "spotify"}
for ch, tools in (c.get("platform_toolsets") or {}).items():
    if not isinstance(tools, list):
        continue
    bad = drop & set(tools)
    assert not bad, f"platform_toolsets.{ch} must not include {bad}"
PY

test ! -f "$FILES_DIR/wallpaper.jpg" || { echo "wallpaper.jpg must be removed" >&2; exit 1; }

shellcheck -e SC1091 -x files/bootstrap.sh files/gateway-run.sh files/feina-onboard.sh files/feina \
  files/agentphone-bridge-run.sh \
  files/scripts/latitude/install_local_telemetry_patch.sh ops/launch-client.sh ops/offboard-client.sh

echo "verify-client-surface: OK"
