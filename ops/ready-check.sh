#!/usr/bin/env bash
# Feina ops — day-before-meeting readiness checklist for a client VM.
set -euo pipefail
OPS_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "${OPS_DIR}/ready_check.py" "${1:?Usage: ready-check.sh <client_slug>}"
