#!/bin/bash
# ==========================================================================
# feina-stack — Hermes gateway wrapper (supervised, reboot-safe)
# ==========================================================================
set +e
export HOME=/root
export HERMES_HOME=/root/.hermes
export PATH=/usr/local/bin:/root/.local/bin:/root/.hermes/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH

# MVP: ChatGPT / openai-codex OAuth only (see feina-onboard model-codex).
until [ -f "$HERMES_HOME/config.yaml" ] && [ -s "$HERMES_HOME/auth.json" ]; do sleep 5; done

set -a
[ -f /root/.env ] && . /root/.env
[ -f "$HERMES_HOME/.env" ] && . "$HERMES_HOME/.env"
set +a

mkdir -p /var/lib/orgo
exec flock /var/lib/orgo/hermes-gateway.lock hermes gateway run --replace --accept-hooks
