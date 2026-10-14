#!/bin/bash
# ==========================================================================
# feina-stack — Hermes gateway wrapper (supervised, reboot-safe)
# ==========================================================================
set +e
export HOME=/root
export HERMES_HOME=/root/.hermes
export PATH=/usr/local/bin:/root/.local/bin:/root/.hermes/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH

model_ready() {
  [ -s "$HERMES_HOME/auth.json" ] && return 0
  # OpenRouter-only clients: no OAuth file required
  if [ -f /root/.hermes/.env ]; then
    set -a
    # shellcheck source=/dev/null
    . /root/.hermes/.env
    set +a
    [ -n "${OPENROUTER_API_KEY:-}" ] && return 0
  fi
  return 1
}

until [ -f "$HERMES_HOME/config.yaml" ] && model_ready; do sleep 5; done

set -a
[ -f /root/.env ] && . /root/.env
[ -f "$HERMES_HOME/.env" ] && . "$HERMES_HOME/.env"
set +a

mkdir -p /var/lib/orgo
exec flock /var/lib/orgo/hermes-gateway.lock hermes gateway run --replace --accept-hooks
