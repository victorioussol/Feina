#!/usr/bin/env bash
# feina-stack — headless onboarding (drive over Orgo bash API)
set -euo pipefail
export HOME=/root
export HERMES_HOME=/root/.hermes
export PATH=/usr/local/bin:/root/.hermes/bin:/root/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH

ENV_FILE="$HERMES_HOME/.env"
OP_ENV="$HERMES_HOME/.op.env"
VENV_PY=/usr/local/lib/hermes-agent/venv/bin/python
PAIR_PY=/usr/local/bin/feina-stack-telegram-pair.py

usage() {
  cat <<'EOF'
feina-onboard — non-interactive client setup

Integration toggles:  feina enable|disable|list  (e.g. feina enable agentphone)

  model-codex              Start ChatGPT (openai-codex) device login; prints URL + code
  model-openrouter <key>   Set OPENROUTER_API_KEY and switch default provider
  telegram-qr [bot name]   Mint Telegram QR (headless); prints deep link + PNG path
  allow-user <telegram_id> Append a Telegram user id to TELEGRAM_ALLOWED_USERS
  composio <ck_...>        Set COMPOSIO_CONSUMER_KEY
  agentmail <am_...> [inbox@agentmail.to]
  latitude <key> <project> Set Latitude tracing (optional)
  op-token <ops_...>       Write 1Password service account token and enable map
  status                   Health check (gateway, Hermes version, MCPs, no ORGO keys)

Environment: FEINA_BOT_NAME overrides default bot display name for telegram-qr.
EOF
}

append_env() {
  local key="$1" val="$2"
  touch "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  grep -vE "^${key}=" "$ENV_FILE" > "$ENV_FILE.tmp" 2>/dev/null || true
  mv "$ENV_FILE.tmp" "$ENV_FILE"
  printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
}

cmd="${1:-}"
shift || true

case "$cmd" in
  model-codex)
    LOG=/root/feina-codex-auth.log
    nohup hermes auth add openai-codex >"$LOG" 2>&1 &
    sleep 3
    echo "=== openai-codex sign-in (use the client's ChatGPT account) ==="
    tail -n 40 "$LOG" || true
    echo "Poll: test -s $HERMES_HOME/auth.json && echo ready"
    ;;
  model-openrouter)
    KEY="${1:?OPENROUTER_API_KEY required}"
    append_env OPENROUTER_API_KEY "$KEY"
    python3 - <<'PY'
import yaml, os
p="/root/.hermes/config.yaml"
with open(p) as f: c=yaml.safe_load(f)
c.setdefault("model",{})["provider"]="openrouter"
c["model"]["default"]="anthropic/claude-sonnet-4"
with open(p,"w") as f: yaml.safe_dump(c,f,default_flow_style=False,sort_keys=False)
os.chmod(p,0o600)
print("model.provider=openrouter")
PY
    supervisorctl restart hermes-gateway 2>/dev/null || true
    ;;
  telegram-qr)
    [ -n "${1:-}" ] && export FEINA_BOT_NAME="$1"
    exec "$VENV_PY" "$PAIR_PY" --headless
    ;;
  allow-user)
    TG_UID="${1:?telegram numeric user id}"
    "$VENV_PY" - "$TG_UID" <<'PY'
import sys
from hermes_cli.config import save_env_value
uid=sys.argv[1]
cur=""
try:
    with open("/root/.hermes/.env") as f:
        for line in f:
            if line.startswith("TELEGRAM_ALLOWED_USERS="):
                cur=line.split("=",1)[1].strip()
except OSError:
    pass
ids=[x.strip() for x in cur.split(",") if x.strip()]
if uid not in ids: ids.append(uid)
save_env_value("TELEGRAM_ALLOWED_USERS", ",".join(ids))
print("TELEGRAM_ALLOWED_USERS=", ",".join(ids))
PY
    supervisorctl restart hermes-gateway 2>/dev/null || true
    ;;
  composio)
    append_env COMPOSIO_CONSUMER_KEY "${1:?ck_ key}"
    supervisorctl restart hermes-gateway 2>/dev/null || true
    ;;
  agentmail)
    append_env AGENTMAIL_API_KEY "${1:?am_ key}"
    [ -n "${2:-}" ] && append_env AGENTMAIL_INBOX "$2"
    supervisorctl restart hermes-gateway 2>/dev/null || true
    ;;
  latitude)
    append_env LATITUDE_API_KEY "${1:?key}"
    append_env LATITUDE_PROJECT "${2:?project slug}"
    supervisorctl restart hermes-gateway 2>/dev/null || true
    ;;
  op-token)
    TOK="${1:?ops_ token}"
    umask 077
    printf 'OP_SERVICE_ACCOUNT_TOKEN=%s\n' "$TOK" >"$OP_ENV"
    chmod 600 "$OP_ENV"
    python3 /usr/local/bin/feina-stack-op-enable
    supervisorctl restart hermes-gateway 2>/dev/null || true
    ;;
  status)
    echo "=== feina-onboard status ==="
    echo -n "Hermes version: "; hermes --version 2>/dev/null || echo "missing"
    if supervisorctl status hermes-gateway 2>/dev/null | grep -q RUNNING; then
      echo "Gateway: RUNNING (supervisor)"
    else
      echo "Gateway: not RUNNING under supervisor (may still be starting)"
    fi
    if [ -s "$HERMES_HOME/auth.json" ]; then
      echo "Model auth: auth.json present (codex/oauth)"
    elif grep -q '^OPENROUTER_API_KEY=' "$ENV_FILE" 2>/dev/null; then
      echo "Model auth: OPENROUTER_API_KEY set"
    else
      echo "Model auth: NOT READY (run model-codex or model-openrouter)"
    fi
    echo "MCP servers:"
    hermes mcp list 2>/dev/null || true
    python3 - <<'PY' || true
import yaml
c=yaml.safe_load(open("/root/.hermes/config.yaml"))
o=(c.get("mcp_servers") or {}).get("orgo") or {}
print("orgo MCP enabled:", o.get("enabled", False), "(must be False on clients)")
PY
    ORGO_HITS=$(grep -rE '^ORGO_API_KEY=|^ORGO_DEFAULT_COMPUTER_ID=' "$HERMES_HOME/.env" /root/.env 2>/dev/null | wc -l || echo 0)
    if [ "$ORGO_HITS" -eq 0 ]; then
      echo "ORGO_API_KEY: none found (good)"
    else
      echo "ORGO_API_KEY: FOUND $ORGO_HITS references (BAD — remove immediately)"
      exit 2
    fi
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
