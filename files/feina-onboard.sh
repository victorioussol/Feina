#!/usr/bin/env bash
# feina-stack — v1.0 onboarding (Feina pre-setup + in-meeting client steps)
set -euo pipefail
export HOME=/root
export HERMES_HOME=/root/.hermes
export PATH=/usr/local/bin:/root/.hermes/bin:/root/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH
# shellcheck disable=SC1091
[ -f /usr/local/bin/feina-hermes-path.sh ] && . /usr/local/bin/feina-hermes-path.sh
feina_prepend_hermes_node_path 2>/dev/null || true

ENV_FILE="$HERMES_HOME/.env"
OP_ENV="$HERMES_HOME/.op.env"
VENV_PY=/usr/local/lib/hermes-agent/venv/bin/python
PAIR_PY=/usr/local/bin/feina-stack-telegram-pair.py
PENDING_PY=/usr/local/bin/feina-telegram-pending.py

strip_orgo_env() {
  local f="$1"
  [ -f "$f" ] || return 0
  grep -vE '^(ORGO_API_KEY|ORGO_DEFAULT_COMPUTER_ID)=' "$f" > "$f.norgo" 2>/dev/null || true
  mv "$f.norgo" "$f"
}

strip_openai_api_key() {
  local f="$1"
  [ -f "$f" ] || return 0
  if grep -qE '^OPENAI_API_KEY=' "$f" 2>/dev/null; then
    grep -vE '^OPENAI_API_KEY=' "$f" > "$f.noaik" 2>/dev/null || true
    mv "$f.noaik" "$f"
    echo "Removed OPENAI_API_KEY from $f (v1 uses openai-codex OAuth only)."
  fi
}

usage() {
  cat <<'EOF'
feina-onboard — v1.0 client onboarding (ChatGPT OAuth + Telegram; no OpenAI API key)

Phases:
  setup                 Print both pre-meeting and in-meeting checklists
  setup-pre             Feina pre-setup (before the client meeting)
  setup-meeting         In-meeting steps (client-facing)

Pre-setup (Feina):
  model-codex           ChatGPT sign-in via openai-codex device code (Feina completes OAuth)
  telegram <bot_token>  Install BotFather token (Feina creates the bot; client never sees token)
  telegram-qr [name]    Optional managed-bot QR instead of manual token
  honcho / agentmail / latitude / op-token
  gateway-test          Quick Telegram + gateway smoke test
  safety-check          Pre-meeting safety gate (run before the call)

In-meeting:
  composio <ck_...>     Install client's Composio key (Feina pastes; client created account in browser)
  pending-telegram      List Telegram user IDs from recent /start (after client taps Start)
  allow-telegram <id>   Allowlist client's Telegram user id (alias: allow-user)

  status                Health check

Integration toggles: feina enable|disable|list

No OpenAI API key in the default flow — only auth.json from model-codex.
EOF
}

append_env() {
  local key="$1" val="$2"
  touch "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  grep -vE "^${key}=" "$ENV_FILE" > "$ENV_FILE.tmp" 2>/dev/null || true
  mv "$ENV_FILE.tmp" "$ENV_FILE"
  printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  strip_orgo_env "$ENV_FILE"
  strip_openai_api_key "$ENV_FILE"
}

allow_telegram_user() {
  local TG_UID="$1"
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
}

PRE_SETUP_DOC=$(cat <<'EOF'

=== A) Feina pre-setup (before the client meeting) ===

1. Bootstrap complete on the client VM (see ops/launch-client.sh).
2. ChatGPT model — Feina signs in (no API key):
     feina-onboard model-codex
   Complete device-code OAuth at chatgpt.com (Feina-owned ChatGPT for the pilot).
   Poll: test -s /root/.hermes/auth.json && echo ready
3. Telegram bot — Feina creates the bot in BotFather, then on the VM:
     feina-onboard telegram <bot_token>
   Optional: feina-onboard telegram-qr "Client Name · Feina"
   Test: feina-onboard gateway-test
4. Honcho + Feina-only secrets (client vault / 1Password):
   Ops provisions isolated Honcho workspace feina-<slug> + workspace-scoped key at launch.
     feina-onboard op-token <ops_...>     # includes per-client HONCHO_API_KEY
   Or: feina-onboard honcho <workspace-scoped-key>
   Ops after bootstrap: python3 ops/feina_honcho.py push-config --slug <slug> --computer-id <id>
     feina-onboard agentmail <am_...> [inbox]
     feina-onboard latitude <key> <project>
5. Safety gate before the meeting:
     feina-onboard safety-check

Do NOT put OPENAI_API_KEY on the VM. Do NOT install Composio yet.

EOF
)

MEETING_DOC=$(cat <<'EOF'

=== B) In-meeting (client steps) ===

1. Client creates their own Composio account and connects Gmail/Calendar/Sheets in Composio UI.
2. Client copies their Composio API key to Feina (chat/screen) — Feina installs it:
     feina-onboard composio <ck_...>
   The client never SSHs to the VM or pastes keys into the agent.
3. Client opens Telegram, finds the bot, taps Start once.
4. Feina approves the client:
     feina-onboard pending-telegram
     feina-onboard allow-telegram <telegram_user_id>
5. Client sends a test message in Telegram.

Optional later: feina list  →  feina enable <integration>

EOF
)

cmd="${1:-}"
shift || true

case "$cmd" in
  setup)
    printf '%s\n%s\n' "$PRE_SETUP_DOC" "$MEETING_DOC"
    ;;
  setup-pre)
    printf '%s\n' "$PRE_SETUP_DOC"
    ;;
  setup-meeting)
    printf '%s\n' "$MEETING_DOC"
    ;;
  model-codex)
    LOG=/root/feina-codex-auth.log
    nohup hermes auth add openai-codex >"$LOG" 2>&1 &
    sleep 3
    echo "=== ChatGPT sign-in (openai-codex device code) ==="
    echo "Feina completes OAuth at chatgpt.com — no OpenAI API key on this VM."
    tail -n 40 "$LOG" || true
    echo "Poll: test -s $HERMES_HOME/auth.json && echo ready"
    ;;
  telegram)
    TOK="${1:?BotFather token}"
    append_env TELEGRAM_BOT_TOKEN "$TOK"
    # Client allowlist is added after they tap Start (allow-telegram).
    supervisorctl restart hermes-gateway 2>/dev/null || true
    echo "TELEGRAM_BOT_TOKEN set. Run: feina-onboard gateway-test"
    ;;
  telegram-qr)
    [ -n "${1:-}" ] && export FEINA_BOT_NAME="$1"
    exec "$VENV_PY" "$PAIR_PY" --headless --append-allowlist
    ;;
  allow-telegram|allow-user)
    TG_UID="${1:?telegram numeric user id}"
    allow_telegram_user "$TG_UID"
    ;;
  pending-telegram)
    exec python3 "$PENDING_PY"
    ;;
  gateway-test)
    set -a
    # shellcheck disable=SC1090
    [ -f "$ENV_FILE" ] && . "$ENV_FILE"
    set +a
    if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
      echo "FAIL: TELEGRAM_BOT_TOKEN not set (feina-onboard telegram <token>)"
      exit 1
    fi
    if ! supervisorctl status hermes-gateway 2>/dev/null | grep -q RUNNING; then
      echo "WARN: hermes-gateway not RUNNING under supervisor — starting…"
      supervisorctl start hermes-gateway 2>/dev/null || true
      sleep 3
    fi
    ME=$(curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result',{}).get('username','?') if d.get('ok') else 'ERR')" 2>/dev/null || echo ERR)
    if [ "$ME" = "ERR" ] || [ "$ME" = "?" ]; then
      echo "FAIL: Telegram getMe failed — check token"
      exit 1
    fi
    echo "Telegram bot: @$ME"
    if [ -s "$HERMES_HOME/auth.json" ]; then
      echo "Model auth: auth.json OK"
    else
      echo "WARN: auth.json missing — run feina-onboard model-codex"
    fi
    echo "Gateway test: OK (bot reachable; gateway supervised)"
    ;;
  safety-check)
    FAIL=0
    echo "=== feina-onboard safety-check (pre-meeting) ==="
    if [ ! -s "$HERMES_HOME/auth.json" ]; then
      echo "FAIL: auth.json missing — run model-codex"
      FAIL=1
    else
      echo "OK: openai-codex auth.json present"
    fi
    if ! grep -qE '^TELEGRAM_BOT_TOKEN=.' "$ENV_FILE" 2>/dev/null; then
      echo "FAIL: TELEGRAM_BOT_TOKEN missing — run telegram <token>"
      FAIL=1
    else
      echo "OK: TELEGRAM_BOT_TOKEN set"
    fi
    if grep -qE '^OPENAI_API_KEY=' "$ENV_FILE" /root/.env 2>/dev/null; then
      echo "FAIL: OPENAI_API_KEY must not be on client VMs (use model-codex OAuth)"
      FAIL=1
    else
      echo "OK: no OPENAI_API_KEY"
    fi
    strip_orgo_env "$ENV_FILE"
    strip_orgo_env /root/.env
    if grep -rE '^ORGO_API_KEY=|^ORGO_DEFAULT_COMPUTER_ID=' "$HERMES_HOME/.env" /root/.env 2>/dev/null | grep -q .; then
      echo "FAIL: ORGO_* keys on client VM"
      FAIL=1
    else
      echo "OK: no ORGO_* in .env"
    fi
    if ! feina-onboard gateway-test 2>/dev/null; then
      echo "FAIL: gateway-test"
      FAIL=1
    fi
    if [ "$FAIL" -ne 0 ]; then
      echo "safety-check: FAILED"
      exit 2
    fi
    echo "safety-check: PASSED"
    ;;
  composio)
    append_env COMPOSIO_CONSUMER_KEY "${1:?ck_ key}"
    supervisorctl restart hermes-gateway 2>/dev/null || true
    echo "Composio key installed (in-meeting step)."
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
    # shellcheck disable=SC1090
    set -a; [ -f "$OP_ENV" ] && . "$OP_ENV"; [ -f "$ENV_FILE" ] && . "$ENV_FILE"; set +a
    python3 /usr/local/bin/feina-honcho-sync.py 2>/dev/null || true
    supervisorctl restart hermes-gateway 2>/dev/null || true
    ;;
  honcho)
    append_env HONCHO_API_KEY "${1:?honcho workspace-scoped api key}"
    python3 /usr/local/bin/feina-honcho-sync.py 2>/dev/null || true
    supervisorctl restart hermes-gateway 2>/dev/null || true
    ;;
  honcho-apply)
    python3 /usr/local/bin/feina-honcho-apply.py
    python3 /usr/local/bin/feina-honcho-sync.py 2>/dev/null || true
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
      echo "Model auth: auth.json present (openai-codex OAuth)"
    else
      echo "Model auth: NOT READY — run: feina-onboard model-codex"
    fi
    if grep -qE '^OPENAI_API_KEY=' "$ENV_FILE" 2>/dev/null; then
      echo "WARN: OPENAI_API_KEY present — remove for v1 (OAuth only)"
    fi
    echo "MCP servers:"
    hermes mcp list 2>/dev/null || true
    python3 - <<'PY' || true
import yaml
c=yaml.safe_load(open("/root/.hermes/config.yaml"))
o=(c.get("mcp_servers") or {}).get("orgo") or {}
print("orgo MCP enabled:", o.get("enabled", False), "(must be False on clients)")
PY
    strip_orgo_env "$ENV_FILE"
    strip_orgo_env /root/.env
    strip_openai_api_key "$ENV_FILE"
    # shellcheck disable=SC1090
    set -a; [ -f "$OP_ENV" ] && . "$OP_ENV"; [ -f "$ENV_FILE" ] && . "$ENV_FILE"; set +a
    if [ -f /var/lib/orgo/feina-honcho-disabled ]; then
      echo "Honcho memory: disabled via feina disable honcho"
    elif [ -n "${HONCHO_API_KEY:-}" ]; then
      echo "Honcho memory: key present (workspace ${HONCHO_WORKSPACE_ID:-from honcho.json})"
    else
      echo "Honcho memory: no HONCHO_API_KEY (gateway runs without Honcho until key is set)"
    fi
    python3 /usr/local/bin/feina-honcho-sync.py 2>/dev/null || true
    python3 - <<'PY' || true
import yaml
c=yaml.safe_load(open("/root/.hermes/config.yaml"))
print("memory.provider:", (c.get("memory") or {}).get("provider") or "(empty)")
lin=(c.get("mcp_servers") or {}).get("linear") or {}
print("linear MCP enabled:", lin.get("enabled", False), "(must be False on clients)")
PY
    STATUS_FAIL=0
    if grep -qE '^ORGO_API_KEY=|^ORGO_DEFAULT_COMPUTER_ID=' "$ENV_FILE" /root/.env 2>/dev/null; then
      echo "Orgo keys in .env: FOUND (BAD)"
      STATUS_FAIL=1
    else
      echo "Orgo keys in .env: none (good)"
    fi
    if grep -qE '^COMPOSIO_CONSUMER_KEY=.' "$ENV_FILE" 2>/dev/null; then
      echo "Composio: COMPOSIO_CONSUMER_KEY set"
    else
      echo "Composio: not configured (in-meeting step)"
    fi
    if [ "$STATUS_FAIL" -ne 0 ]; then
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
