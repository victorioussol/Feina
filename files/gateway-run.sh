#!/bin/bash
# ==========================================================================
# feina-stack — Hermes gateway wrapper (supervised, reboot-safe)
# ==========================================================================
set -e
export HOME=/root
export HERMES_HOME=/root/.hermes
export PATH=/usr/local/bin:/root/.local/bin:/root/.hermes/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH

# MVP: ChatGPT / openai-codex OAuth only (see feina-onboard model-codex).
until [ -f "$HERMES_HOME/config.yaml" ] && [ -s "$HERMES_HOME/auth.json" ]; do sleep 5; done

set -a
# shellcheck disable=SC1091
[ -f /root/.env ] && . /root/.env
# shellcheck disable=SC1091
[ -f "$HERMES_HOME/.env" ] && . "$HERMES_HOME/.env"
# shellcheck disable=SC1091
[ -f "$HERMES_HOME/.op.env" ] && . "$HERMES_HOME/.op.env"
set +a

mkdir -p /var/lib/orgo
# Inherit the lock in Hermes itself: supervisord must signal Hermes, not flock.
exec 9>/var/lib/orgo/hermes-gateway.lock
flock -n 9 || { echo "gateway already running" >&2; exit 1; }
python3 /usr/local/bin/feina-honcho-sync.py 2>/dev/null || true
exec hermes gateway run --replace --accept-hooks
