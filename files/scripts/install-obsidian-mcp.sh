#!/usr/bin/env bash
# =============================================================================
# install-obsidian-mcp.sh — give Hermes read/write access to an Obsidian vault
# via MCP (feina-stack template).
#
# Mirrors nicks-stack (MIT, github.com/nickvasilescu/nicks-stack): its Hermes
# config.yaml ships an `obsidian-vault` MCP server = the official
# @modelcontextprotocol/server-filesystem scoped to /root/Documents/HermesVault.
# It works directly on the Markdown files — no Obsidian app, no Local REST API
# plugin needed — and is sandboxed: it refuses any path outside the vault.
#
# Differences from nicks-stack: we install the package globally (pinned) and
# point Hermes at the absolute binary instead of `npx -y`, so gateway start
# never depends on the npm registry being reachable.
#
# Run AS ROOT ON THE ORGO COMPUTER, e.g. from the box:
#   ./obash.py -t 120 - < install-obsidian-mcp.sh
# Env overrides (must be set ON the VM, e.g. prepend `export VAULT=...` lines
# to the piped script): VAULT, PKG_VERSION, RESTART_GATEWAY=0 (skip restart).
# Idempotent: safe to re-run.
# =============================================================================
set -euo pipefail
export HOME=/root
export PATH=/usr/local/bin:/root/.hermes/bin:/root/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH

VAULT="${VAULT:-/root/Documents/HermesVault}"
PKG_VERSION="${PKG_VERSION:-2026.1.14}"
CFG=/root/.hermes/config.yaml
RESTART_GATEWAY="${RESTART_GATEWAY:-1}"

command -v npm >/dev/null || { echo "npm/node missing — install Node.js first"; exit 1; }
[ -f "$CFG" ] || { echo "$CFG not found — is Hermes installed?"; exit 1; }

# 1) MCP server (filesystem, pinned)
if ! npm ls -g --depth=0 2>/dev/null | grep -q "@modelcontextprotocol/server-filesystem@$PKG_VERSION"; then
  npm install -g "@modelcontextprotocol/server-filesystem@$PKG_VERSION"
fi
BIN="$(command -v mcp-server-filesystem)"
echo "MCP binary: $BIN"

# 2) Vault skeleton (never overwrites existing notes)
mkdir -p "$VAULT"/{Clients,Reports,Notes}
for d in Clients Reports Notes; do [ -e "$VAULT/$d/.gitkeep" ] || touch "$VAULT/$d/.gitkeep"; done
if [ ! -f "$VAULT/README.md" ]; then
cat > "$VAULT/README.md" <<'MD'
# Hermes Vault — Feina

This is the shared notes vault for Feina's Hermes agent.
Hermes can read and write these notes through the `obsidian-vault` MCP server,
and you can browse/edit the same files in the Obsidian app on this computer.

## Folders
- **Clients/** — one note per client: context, contacts, decisions, next steps.
- **Reports/** — reports and summaries Hermes produces (weekly updates, research, analyses).
- **Notes/** — everything else: meeting notes, ideas, scratch notes.

## Conventions
- Plain Markdown files (`.md`). Use `[[wikilinks]]` to link notes.
- File names: `YYYY-MM-DD-short-title.md` for dated notes, `Client Name.md` for client notes.
MD
fi

# 3) Hermes config: backup, insert `obsidian-vault` under mcp_servers, validate
BAK="$CFG.bak-pre-obsidian-$(date +%Y%m%d-%H%M%S)"
cp -p "$CFG" "$BAK"
echo "Backup: $BAK"
CHANGED=$(BIN="$BIN" VAULT="$VAULT" python3 - <<'P'
import os, yaml
C='/root/.hermes/config.yaml'
s=open(C).read()
cfg=yaml.safe_load(s) or {}
if (cfg.get('mcp_servers') or {}).get('obsidian-vault'):
    print('no'); raise SystemExit
block=("  obsidian-vault:\n"
       f"    command: {os.environ['BIN']}\n"
       "    args:\n"
       f"      - {os.environ['VAULT']}\n"
       "    connect_timeout: 60\n"
       "    enabled: true\n")
lines=s.splitlines(keepends=True)
if not s.endswith('\n'): lines[-1]+='\n'
idx=[n for n,l in enumerate(lines) if l.rstrip('\n').rstrip()=='mcp_servers:']
if idx:
    j=idx[0]+1
    while j<len(lines) and (lines[j].startswith(' ') or lines[j].strip()==''): j+=1
    lines.insert(j,block)
else:
    lines.append('mcp_servers:\n'+block)
new=''.join(lines)
c2=yaml.safe_load(new)
assert c2['mcp_servers']['obsidian-vault']['args']==[os.environ['VAULT']]
assert set(c2)-{'mcp_servers'}==set(cfg)-{'mcp_servers'}, 'top-level keys changed'
open(C,'w').write(new)
print('yes')
P
)
if [ "$CHANGED" = "no" ]; then
  echo "obsidian-vault already configured — config untouched"; rm -f "$BAK"
fi

# 4) Verify Hermes sees the server and its tools
hermes mcp test obsidian-vault || { echo "MCP test failed — restoring $BAK"; [ -f "$BAK" ] && cp -p "$BAK" "$CFG"; exit 1; }

# 5) Restart the gateway so Telegram etc. pick up the new tools
if [ "$RESTART_GATEWAY" = "1" ] && [ "$CHANGED" = "yes" ]; then
  if supervisorctl status hermes-gateway >/dev/null 2>&1; then
    supervisorctl restart hermes-gateway                       # Orgo template (supervisord)
  elif systemctl list-unit-files 2>/dev/null | grep -q hermes-gateway; then
    systemctl restart hermes-gateway
  else
    echo "No supervised gateway found — restart it manually (hermes gateway restart / re-run)."
  fi
  sleep 20
  if ! supervisorctl status hermes-gateway 2>/dev/null | grep -q RUNNING; then
    echo "Gateway not RUNNING after restart — restoring $BAK"; cp -p "$BAK" "$CFG"
    supervisorctl restart hermes-gateway || true; exit 1
  fi
  tail -n 40 /var/log/orgo/hermes-gateway.err 2>/dev/null | grep -i "telegram\|mcp" | tail -5 || true
fi
echo "Done. Vault: $VAULT  (MCP server name: obsidian-vault)"
