#!/bin/bash
# feina-stack — AgentPhone webhook bridge (supervised; gated by feina enable agentphone)
set +e
export HOME=/root
export PATH=/usr/local/bin:/root/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH

FLAG=/var/lib/orgo/feina-agentphone-enabled
E=/root/.hermes/.env

until [ -f "$FLAG" ] && \
      grep -q '^AGENTPHONE_API_KEY=..' "$E" 2>/dev/null && \
      grep -q '^AGENTPHONE_AGENT_ID=..' "$E" 2>/dev/null; do
  sleep 15
done

mkdir -p /var/lib/orgo
exec flock /var/lib/orgo/agentphone-bridge.lock \
  /usr/bin/python3 /root/.hermes_agentphone_bridge/agentphone_bridge.py
