#!/usr/bin/env bash
# Latitude telemetry — install plugin; core reasoning_config patch is best-effort.
set -euo pipefail

VENV_PY="/usr/local/lib/hermes-agent/venv/bin/python"
PKG_DIR="/root/.hermes/local-packages/latitude-telemetry-hermes"
VALIDATE="/root/.hermes/scripts/latitude/dewey_observability_validate.py"
CORE_LOOP="/usr/local/lib/hermes-agent/agent/conversation_loop.py"
API_HOOKS="/usr/local/lib/hermes-agent/agent/api_request_hooks.py"

if [[ ! -x "$VENV_PY" ]]; then
  echo "Hermes venv Python not found: $VENV_PY" >&2
  exit 1
fi
if [[ ! -f "$PKG_DIR/pyproject.toml" ]]; then
  echo "Local telemetry package not found: $PKG_DIR" >&2
  exit 1
fi

patch_file() {
  local path="$1"
  [[ -f "$path" ]] || return 1
  "$VENV_PY" - "$path" <<'PY' || return 1
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
needle = "                            reasoning_config=agent.reasoning_config,\n"
if needle in text:
    print(f"reasoning_config hook already present in {path}")
    raise SystemExit(0)
anchor = (
    "                            max_tokens=agent.max_tokens,\n"
    "                            started_at=api_start_time,\n"
)
replacement = (
    "                            max_tokens=agent.max_tokens,\n"
    "                            reasoning_config=agent.reasoning_config,\n"
    "                            started_at=api_start_time,\n"
)
if anchor not in text:
    raise SystemExit(f"anchor not found in {path}")
path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
print(f"Patched reasoning_config hook in {path}")
PY
}

if ! patch_file "$CORE_LOOP"; then
  if ! patch_file "$API_HOOKS"; then
    echo "WARN: core reasoning_config patch skipped (telemetry plugin still loads)"
  fi
fi

"$VENV_PY" -m pip install -e "$PKG_DIR" \
  || uv pip install --python "$VENV_PY" -e "$PKG_DIR" \
  || /root/.hermes/bin/uv pip install --python "$VENV_PY" -e "$PKG_DIR"

"$VENV_PY" - <<'PY'
import importlib.metadata as md
import pathlib
import latitude_telemetry_hermes
print('latitude-telemetry-hermes', md.version('latitude-telemetry-hermes'))
print('module_file', pathlib.Path(latitude_telemetry_hermes.__file__).resolve())
PY

if [[ -f "$VALIDATE" ]]; then
  python3 "$VALIDATE" || echo "WARN: latitude validate script reported issues"
fi
