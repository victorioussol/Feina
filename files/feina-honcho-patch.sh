#!/usr/bin/env bash
# FEINA PATCH 20261116 re-apply (Victor approved 16 Nov 2026 17:36 Madrid).
# Makes the Honcho memory plugin skip runs started with `hermes chat --source cron`
# (automation launchers), so overnight/morning jobs do not trigger paid Honcho
# dialectic calls or get filed as if the client said them.
# Safe + idempotent: does nothing if the marker is present; backs up before editing;
# validates Python syntax and restores the backup on failure.
# Run it after any `hermes update` / plugin update / reinstall of the honcho plugin.
# Usage: reapply_feina_honcho_patch.sh [--check] [path/to/plugins/honcho/__init__.py]
# Exit: 0 patched or already patched; 1 anchor not found (plugin changed, patch by hand);
#       2 --check and NOT patched.
set -euo pipefail
CHECK=0; [ "${1:-}" = "--check" ] && { CHECK=1; shift; }
HH="${HERMES_HOME:-/root/.hermes}"
F="${1:-$HH/plugins/honcho/__init__.py}"
MARK="# FEINA PATCH 20261116: skip Honcho for --source cron runs; re-apply after plugin updates"
[ -f "$F" ] || { echo "honcho plugin not found: $F"; exit 1; }
if grep -qF "$MARK" "$F"; then echo "OK already patched: $F"; exit 0; fi
if [ "$CHECK" = 1 ]; then echo "NOT PATCHED: $F (run without --check to apply)"; exit 2; fi
python3 - "$F" "$MARK" <<'PYEOF'
import re, sys, shutil, time, py_compile
f, mark = sys.argv[1], sys.argv[2]
src = open(f, encoding="utf-8").read()
old = 'if agent_context in {"cron", "flush"} or platform == "cron":'
if src.count(old) != 1:
    print("ANCHOR NOT FOUND (plugin changed): patch by hand so initialize() also skips when "
          "os.environ['HERMES_SESSION_SOURCE'] == 'cron'")
    sys.exit(1)
ind = re.search(r'^([ \t]*)' + re.escape(old), src, re.M).group(1)
new = (f'{mark}\n'
       f'{ind}# `hermes chat --source cron` runs are marked interactive by the CLI, so the old check never fired for them.\n'
       f'{ind}if (agent_context in {{"cron", "flush"}} or platform == "cron"\n'
       f'{ind}        or os.environ.get("HERMES_SESSION_SOURCE", "").strip().lower() == "cron"):')
src2 = src.replace(old, new, 1)
if not re.search(r'^import os$', src2, re.M):
    src2 = src2.replace("\nimport json\n", "\nimport json\nimport os\n", 1)
bak = f + ".pre-feina-" + time.strftime("%Y%m%dT%H%M%S")
shutil.copy2(f, bak)
open(f, "w", encoding="utf-8").write(src2)
try:
    py_compile.compile(f, doraise=True)
except Exception as e:
    shutil.copy2(bak, f)
    print("SYNTAX FAIL, original restored:", e)
    sys.exit(1)
print("PATCHED", f, "| backup", bak)
PYEOF
