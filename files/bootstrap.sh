#!/usr/bin/env bash
# =============================================================================
# feina-stack bootstrap — idempotent install for Hermes client agents
# =============================================================================
# Used by:
#   • Orgo template build (apps[].install in build_template.py)
#   • Fresh Orgo computer: curl -fsSL …/files/bootstrap.sh | bash
# Run as root. Logs to /var/log/feina-bootstrap.log when invoked detached.
# =============================================================================
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export HOME=/root
export HERMES_HOME=/root/.hermes
export PATH=/usr/local/bin:/root/.hermes/bin:/root/.hermes/node/bin:/root/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH

HERMES_INSTALL_COMMIT="71d34bad1045610252eda02ee79549436896e784"
STAGE="/opt/feina-stack/stage"
PKG_FS_VERSION="2026.1.14"
OP_VERSION="2.34.1"
LOG="${FEINA_BOOTSTRAP_LOG:-/var/log/feina-bootstrap.log}"
exec > >(tee -a "$LOG") 2>&1

echo "=== feina-stack bootstrap $(date -Iseconds) ==="

# 1) Hermes Agent — pinned v0.21.7 (commit above = tag v0.21.7)
if ! command -v hermes >/dev/null 2>&1; then
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- \
    --non-interactive --skip-setup --skip-browser \
    --commit "$HERMES_INSTALL_COMMIT"
  hash -r || true
else
  echo "Hermes already installed: $(hermes --version 2>/dev/null || true)"
fi

# 2) 1Password CLI (secret plane)
if ! command -v op >/dev/null 2>&1; then
  curl -fsSL "https://cache.agilebits.com/dist/1P/op2/pkg/v${OP_VERSION}/op_linux_amd64_v${OP_VERSION}.zip" -o /tmp/op.zip
  python3 -c "import zipfile; zipfile.ZipFile('/tmp/op.zip').extract('op', '/tmp/opx')"
  install -m 0755 /tmp/opx/op /usr/bin/op
  rm -rf /tmp/op.zip /tmp/opx
fi
op --version

# 3) Obsidian vault MCP — global pinned binary (no npx at runtime)
if ! npm ls -g --depth=0 2>/dev/null | grep -q "@modelcontextprotocol/server-filesystem@${PKG_FS_VERSION}"; then
  npm install -g "@modelcontextprotocol/server-filesystem@${PKG_FS_VERSION}" \
    || npm install -g @modelcontextprotocol/server-filesystem
fi
MCP_FS_BIN="$(command -v mcp-server-filesystem)"
echo "mcp-server-filesystem: $MCP_FS_BIN"

npm install -g agent-cards@0.5.59 @xdevplatform/xurl \
  || npm install -g agent-cards @xdevplatform/xurl

if ! command -v cloudflared >/dev/null 2>&1; then
  curl -fsSL -o /usr/local/bin/cloudflared \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  chmod +x /usr/local/bin/cloudflared
fi
cloudflared --version 2>/dev/null || true

timeout 60 npx -y agentphone-mcp </dev/null >/dev/null 2>&1 || true

# 4) qrcode into the Hermes venv (Telegram pairing PNG)
VENV_PY=/usr/local/lib/hermes-agent/venv/bin/python
if [ -x "$VENV_PY" ]; then
  uv pip install --python "$VENV_PY" "qrcode[pil]" 2>/dev/null \
    || /root/.hermes/bin/uv pip install --python "$VENV_PY" "qrcode[pil]" 2>/dev/null \
    || "$VENV_PY" -m pip install "qrcode[pil]" 2>/dev/null || true
fi

# 5) Stage payload — from template bake (/opt/feina-stack/payload.tgz.b64) or git checkout
mkdir -p "$STAGE" /root/.hermes/plugins /root/.hermes/skills /root/.hermes/scripts \
         /root/.hermes/local-packages /root/.hermes/memories /root/.hermes/state \
         /root/Documents/HermesVault /root/.hermes/skills/client-drop \
         /root/.hermes_agentphone_bridge /var/log/orgo /var/lib/orgo

if [ -f /opt/feina-stack/payload.tgz.b64 ]; then
  base64 -d /opt/feina-stack/payload.tgz.b64 | tar xzf - -C "$STAGE"
elif [ -f /opt/feina-stack/src/files/config.yaml ]; then
  SRC=/opt/feina-stack/src/files
  mkdir -p "$STAGE/hermes"
  cp -f "$SRC/config.yaml" "$SRC/SOUL.md" "$SRC/hermes.env" "$STAGE/hermes/"
  cp -rf "$SRC/plugins/." "$STAGE/hermes/plugins/" 2>/dev/null || true
  cp -rf "$SRC/skills/." "$STAGE/hermes/skills/" 2>/dev/null || true
  cp -rf "$SRC/scripts/." "$STAGE/hermes/scripts/" 2>/dev/null || true
  cp -rf "$SRC/local-packages/." "$STAGE/hermes/local-packages/" 2>/dev/null || true
  cp -rf "$SRC/vault/." "$STAGE/vault/" 2>/dev/null || true
else
  echo "WARN: no staged payload — expecting pre-copied stage at $STAGE"
fi

if [ -f "$STAGE/hermes/config.yaml" ]; then
  cp -f "$STAGE/hermes/config.yaml" /root/.hermes/config.yaml
  cp -f "$STAGE/hermes/SOUL.md"     /root/.hermes/SOUL.md
  cp -f "$STAGE/hermes/env"         /root/.hermes/.env
  cp -rf "$STAGE/hermes/plugins/."   /root/.hermes/plugins/ 2>/dev/null || true
  cp -rf "$STAGE/hermes/skills/."    /root/.hermes/skills/ 2>/dev/null || true
  cp -rf "$STAGE/hermes/scripts/."   /root/.hermes/scripts/ 2>/dev/null || true
  cp -rf "$STAGE/hermes/local-packages/." /root/.hermes/local-packages/ 2>/dev/null || true
  [ -d "$STAGE/vault" ] && cp -rf "$STAGE/vault/." /root/Documents/HermesVault/
  grep -vE '^(ORGO_API_KEY|ORGO_DEFAULT_COMPUTER_ID)=' /root/.hermes/.env > /root/.hermes/.env.norgo 2>/dev/null || true
  mv /root/.hermes/.env.norgo /root/.hermes/.env
  chmod 600 /root/.hermes/config.yaml /root/.hermes/.env
fi

if [ -f "$STAGE/agentphone-bridge/agentphone_bridge.py" ]; then
  cp -f "$STAGE/agentphone-bridge/agentphone_bridge.py" /root/.hermes_agentphone_bridge/
  cp -f "$STAGE/agentphone-bridge/env" /root/.hermes_agentphone_bridge/
  cp -f "$STAGE/agentphone-bridge/test_event_ordering.py" /root/.hermes_agentphone_bridge/ 2>/dev/null || true
  chmod 700 /root/.hermes_agentphone_bridge/agentphone_bridge.py
  chmod 600 /root/.hermes_agentphone_bridge/env 2>/dev/null || true
elif [ -f /opt/feina-stack/src/files/agentphone-bridge/agentphone_bridge.py ]; then
  cp -rf /opt/feina-stack/src/files/agentphone-bridge/. /root/.hermes_agentphone_bridge/
fi

# Vault skeleton (never overwrites notes)
VAULT=/root/Documents/HermesVault
mkdir -p "$VAULT"/{Clients,Reports,Notes}
for d in Clients Reports Notes; do touch "$VAULT/$d/.gitkeep" 2>/dev/null || true; done

# 6) Ensure obsidian-vault MCP uses absolute binary path
python3 - "$MCP_FS_BIN" <<'PY'
import os, sys, yaml
cfg_path = "/root/.hermes/config.yaml"
if not os.path.isfile(cfg_path):
    raise SystemExit(0)
bin_path = sys.argv[1]
with open(cfg_path) as f:
    cfg = yaml.safe_load(f) or {}
mcp = cfg.setdefault("mcp_servers", {})
obs = mcp.setdefault("obsidian-vault", {})
obs["command"] = bin_path
obs["args"] = ["/root/Documents/HermesVault"]
obs["enabled"] = True
obs.pop("url", None)
with open(cfg_path, "w") as f:
    yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=1000)
os.chmod(cfg_path, 0o600)
print("obsidian-vault MCP →", bin_path)
PY

# 7) Latitude telemetry plugin (core patch is best-effort on v0.21.7+)
if [ -f /root/.hermes/scripts/latitude/install_local_telemetry_patch.sh ]; then
  bash /root/.hermes/scripts/latitude/install_local_telemetry_patch.sh || \
    echo "WARN: latitude core patch skipped (plugin still works)"
fi

# 8) Supervisord gateway unit if missing (blank VMs may lack template services)
if command -v supervisorctl >/dev/null 2>&1 && [ ! -f /etc/supervisor/conf.d/hermes-gateway.conf ]; then
  cat > /etc/supervisor/conf.d/hermes-gateway.conf <<'SUP'
[program:hermes-gateway]
command=/usr/local/bin/hermes-gateway-run.sh
user=root
autostart=true
autorestart=true
stdout_logfile=/var/log/orgo/hermes-gateway.log
stderr_logfile=/var/log/orgo/hermes-gateway.err
SUP
  supervisorctl reread 2>/dev/null || true
  supervisorctl update 2>/dev/null || true
fi

# 9) Install helper binaries from stage if present
for pair in \
  "gateway-run.sh:/usr/local/bin/hermes-gateway-run.sh" \
  "agentphone-bridge-run.sh:/usr/local/bin/feina-stack-agentphone-bridge-run.sh" \
  "feina-onboard.sh:/usr/local/bin/feina-onboard.sh" \
  "feina-enable.py:/usr/local/bin/feina-enable.py" \
  "feina:/usr/local/bin/feina" \
  "telegram-pair.py:/usr/local/bin/feina-stack-telegram-pair.py" \
  "op-enable.py:/usr/local/bin/feina-stack-op-enable"; do
  src="${pair%%:*}"; dst="${pair##*:}"
  for base in "$STAGE/$src" /opt/feina-stack/src/files/"$src"; do
    if [ -f "$base" ]; then install -m 0755 "$base" "$dst"; break; fi
  done
done

supervisorctl restart hermes-gateway 2>/dev/null || true

echo "feina-stack install complete"
