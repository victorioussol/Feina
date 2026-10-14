#!/usr/bin/env bash
# Static checks for feina-stack client surface (run in CI or before release).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
FILES_DIR="$ROOT/files"

python3 -m py_compile build_template.py files/op-enable.py files/telegram-pair.py files/feina-enable.py files/feina-honcho-sync.py files/feina-honcho-apply.py files/feina-honcho-push-receive.py files/feina-telegram-pending.py ops/feina_honcho.py ops/feina_launch_state.py ops/feina_launch.py ops/ready_check.py ops/orgo_bash.py ops/test_feina_honcho_unit.py ops/test_orgo_bash_unit.py
PYTHONPATH="$ROOT/ops" python3 -m unittest test_feina_honcho_unit test_orgo_bash_unit -q
python3 "$ROOT/scripts/test_feina_regressions.py" -q
if ! grep -q 'FEINA_STACK_REF.*main' "$ROOT/ops/feina_launch.py"; then
  echo "feina_launch.py must default FEINA_STACK_REF to main" >&2
  exit 1
fi
if [ ! -f "$FILES_DIR/feina-hermes-path.sh" ]; then
  echo "feina-hermes-path.sh required" >&2
  exit 1
fi
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
mem = c.get("memory") or {}
assert mem.get("provider") == "honcho", "memory.provider must default to honcho for client launches"
lin = (c.get("mcp_servers") or {}).get("linear") or {}
assert lin.get("enabled") is False, "linear MCP must stay off on clients"
op_map = ((c.get("secrets") or {}).get("onepassword") or {}).get("env") or {}
assert "HONCHO_API_KEY" in op_map, "1Password map must include HONCHO_API_KEY"
drop = {"computer_use", "orgo_desktop", "spotify"}
for ch, tools in (c.get("platform_toolsets") or {}).items():
    if not isinstance(tools, list):
        continue
    bad = drop & set(tools)
    assert not bad, f"platform_toolsets.{ch} must not include {bad}"
PY

test ! -f "$FILES_DIR/wallpaper.jpg" || { echo "wallpaper.jpg must be removed" >&2; exit 1; }

if ! grep -q 'setup-pre' "$FILES_DIR/feina-onboard.sh" && ! grep -q 'allow-telegram' "$FILES_DIR/feina-onboard.sh"; then
  echo "feina-onboard must document v1.0 pre/meeting flow and allow-telegram" >&2
  exit 1
fi
if ! grep -q 'feina_launch.py' "$ROOT/ops/launch-client.sh"; then
  echo "launch-client.sh must delegate to phased feina_launch.py" >&2
  exit 1
fi
if ! grep -q 'account/capacity' "$ROOT/ops/feina_launch.py"; then
  echo "feina_launch.py must preflight Orgo capacity (no auto-purchase)" >&2
  exit 1
fi
if ! grep -q 'feina_honcho.py' "$ROOT/ops/feina_launch.py"; then
  echo "feina_launch.py must provision per-client Honcho workspaces (phase A)" >&2
  exit 1
fi
if [ ! -x "$ROOT/ops/ready-check.sh" ] && [ ! -f "$ROOT/ops/ready-check.sh" ]; then
  echo "ops/ready-check.sh must exist" >&2
  exit 1
fi
if rg -n '^OPENAI_API_KEY=' "$FILES_DIR/hermes.env" 2>/dev/null; then
  echo "OPENAI_API_KEY must not be baked into hermes.env" >&2
  exit 1
fi

shellcheck -e SC1090,SC1091 -x files/bootstrap.sh files/gateway-run.sh files/feina-onboard.sh files/feina \
  files/agentphone-bridge-run.sh \
  files/scripts/latitude/install_local_telemetry_patch.sh ops/launch-client.sh ops/offboard-client.sh \
  ops/ready-check.sh

echo "verify-client-surface: OK"
