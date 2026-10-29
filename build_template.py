#!/usr/bin/env python3
# ==========================================================================
# feina-stack — Orgo template builder / publisher
# ==========================================================================
#   python3 build_template.py                 # assemble + validate + dump JSON
#   python3 build_template.py --remote-validate
#   python3 build_template.py --publish
#   python3 build_template.py --build
#   VERSION=1.0.1 python3 build_template.py --build
import base64
import json
import os
import ssl
import sys
import urllib.request
import urllib.error

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL = ssl.create_default_context()
    try:
        _SSL.load_default_certs()
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "files")
NAMESPACE = "default"
NAME = "feina-stack"
VERSION = os.environ.get("VERSION", "1.1.1")
API_BASE = os.environ.get("ORGO_API_BASE", "https://www.orgo.ai/api")
API_KEY = os.environ.get("ORGO_API_KEY", "")


def rd(rel):
    with open(os.path.join(FILES, rel), "r", encoding="utf-8") as fh:
        return fh.read()


def rd_b64(rel):
    with open(os.path.join(FILES, rel), "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def F(to, body, mode="0644", when="build", owner=None, group=None):
    e = {"to": to, "inline": body, "mode": mode, "when": when}
    if owner:
        e["owner"] = owner
    if group:
        e["group"] = group
    return e


STAGE = "/opt/feina-stack/stage"


def payload_b64():
    import gzip
    import io
    import tarfile
    buf = io.BytesIO()
    entries = []
    for rel_root, prefix in (
        ("plugins", "hermes/plugins"),
        ("skills", "hermes/skills"),
        ("scripts", "hermes/scripts"),
        ("local-packages", "hermes/local-packages"),
    ):
        base = os.path.join(FILES, rel_root)
        if not os.path.isdir(base):
            continue
        for root, dirs, fs in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for f in sorted(fs):
                if f.endswith((".pyc", ".DS_Store")):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, base)
                posix = full.replace(os.sep, "/")
                mode = 0o755 if (f.endswith(".sh") or "/scripts/" in posix or rel_root == "scripts") else 0o644
                entries.append((f"{prefix}/{rel}", full, mode))
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for arcname, full, mode in sorted(entries):
                info = tarfile.TarInfo(arcname)
                data = open(full, "rb").read()
                info.size = len(data)
                info.mode = mode
                info.mtime = 0
                info.uid = info.gid = 0
                tar.addfile(info, io.BytesIO(data))
    print(f"payload.tgz: {len(entries)} files, {buf.tell()//1024}KB compressed")
    return base64.b64encode(buf.getvalue()).decode("ascii")


# INSTALL = shared bootstrap (also fetchable from GitHub for blank VMs)
INSTALL = rd("bootstrap.sh")

files = [
    F(f"{STAGE}/hermes/config.yaml", rd("config.yaml"), "0600"),
    F(f"{STAGE}/hermes/SOUL.md", rd("SOUL.md"), "0644"),
    F(f"{STAGE}/hermes/env", rd("hermes.env"), "0600"),
    F(f"{STAGE}/gateway-run.sh", rd("gateway-run.sh"), "0755"),
    F(f"{STAGE}/feina-onboard.sh", rd("feina-onboard.sh"), "0755"),
    F(f"{STAGE}/feina-hermes-path.sh", rd("feina-hermes-path.sh"), "0755"),
    F(f"{STAGE}/telegram-pair.py", rd("telegram-pair.py"), "0755"),
    F(f"{STAGE}/op-enable.py", rd("op-enable.py"), "0755"),
    F("/opt/feina-stack/payload.tgz.b64", payload_b64(), "0644"),
    F("/opt/feina-stack/bootstrap.sh", INSTALL, "0755"),
    F(f"{STAGE}/vault/Welcome.md", rd("vault/Welcome.md"), "0644"),
    F(f"{STAGE}/vault/.obsidian/app.json", rd("vault/.obsidian/app.json"), "0644"),
    F(f"{STAGE}/vault/.obsidian/appearance.json", rd("vault/.obsidian/appearance.json"), "0644"),
    F(f"{STAGE}/vault/.obsidian/core-plugins.json", rd("vault/.obsidian/core-plugins.json"), "0644"),
    F("/usr/local/bin/hermes-gateway-run.sh", rd("gateway-run.sh"), "0755"),
    F("/usr/local/bin/feina-onboard.sh", rd("feina-onboard.sh"), "0755"),
    F("/usr/local/bin/feina-hermes-path.sh", rd("feina-hermes-path.sh"), "0755"),
    F("/usr/local/bin/feina-stack-telegram-pair.py", rd("telegram-pair.py"), "0755"),
    F("/usr/local/bin/feina-stack-op-enable", rd("op-enable.py"), "0755"),
    F("/usr/local/bin/feina-enable.py", rd("feina-enable.py"), "0755"),
    F("/usr/local/bin/feina", rd("feina"), "0755"),
    F("/usr/local/bin/feina-stack-agentphone-bridge-run.sh", rd("agentphone-bridge-run.sh"), "0755"),
    F(f"{STAGE}/agentphone-bridge/agentphone_bridge.py",
      rd("agentphone-bridge/agentphone_bridge.py"), "0700"),
    F(f"{STAGE}/agentphone-bridge/env", rd("agentphone-bridge/env"), "0600"),
    F(f"{STAGE}/agentphone-bridge/test_event_ordering.py",
      rd("agentphone-bridge/test_event_ordering.py"), "0644"),
]

_BRIDGE_KEYS = (
    "COMPOSIO_CONSUMER_KEY AGENTMAIL_API_KEY AGENTMAIL_INBOX "
    "LATITUDE_API_KEY LATITUDE_PROJECT "
    "TELEGRAM_BOT_TOKEN TELEGRAM_ALLOWED_USERS TELEGRAM_HOME_CHANNEL "
    "TELEGRAM_BOT_USERNAME OPENROUTER_API_KEY OWNER_EMAIL "
    "AGENTPHONE_API_KEY AGENTPHONE_AGENT_ID AGENTPHONE_NUMBER_ID AGENTPHONE_NUMBER "
    "VIDIQ_MCP_API_KEY IDEABROWSER_KEY X_APP_ONLY_BEARER_TOKEN "
    "XAI_API_KEY AI_GATEWAY_API_KEY MODEL_API_KEY HONCHO_API_KEY HONCHO_WORKSPACE_ID "
    "GITHUB_TOKEN GH_TOKEN EXA_API_KEY FIRECRAWL_API_KEY HERMES_SPOTIFY_CLIENT_ID"
)

ON_FIRST_BOOT = """
mkdir -p /var/lib/orgo /var/log/orgo /root/.hermes/memories /root/.hermes/state /root/.hermes/skills/client-drop
[ -f /var/lib/orgo/feina-stack.stamp ] || echo "feina-stack first boot $(date -Iseconds)" > /var/lib/orgo/feina-stack.stamp
""".strip()

ON_RESUME = f"""
date -s "$(curl -sI http://www.google.com | awk 'tolower($1)=="date:"{{sub($1 FS,"");print}}')" 2>/dev/null || true
set -a; [ -f /root/.env ] && . /root/.env; [ -f /root/.hermes/.env ] && . /root/.hermes/.env; set +a
mkdir -p /root/.hermes /root/.hermes/state
E=/root/.hermes/.env; touch "$E"
for K in {_BRIDGE_KEYS}; do
  V="$(printenv "$K" 2>/dev/null || true)"
  [ -z "$V" ] && continue
  grep -vE "^${{K}}=" "$E" > "$E.tmp" 2>/dev/null || true
  mv "$E.tmp" "$E"
  echo "${{K}}=${{V}}" >> "$E"
done
chmod 600 "$E"
# Strip Orgo control keys — must never land on client computers.
grep -vE '^(ORGO_API_KEY|ORGO_DEFAULT_COMPUTER_ID)=' "$E" > "$E.norgo" 2>/dev/null || true
mv "$E.norgo" "$E"
chmod 600 "$E"
if [ -f /root/.env ]; then
  grep -vE '^(ORGO_API_KEY|ORGO_DEFAULT_COMPUTER_ID)=' /root/.env > /root/.env.norgo 2>/dev/null || true
  mv /root/.env.norgo /root/.env
  chmod 600 /root/.env 2>/dev/null || true
fi
OPTOK="$(printenv OP_SERVICE_ACCOUNT_TOKEN 2>/dev/null || true)"
if [ -n "$OPTOK" ]; then
  umask 077
  printf 'OP_SERVICE_ACCOUNT_TOKEN=%s\\n' "$OPTOK" > /root/.hermes/.op.env
fi
python3 /usr/local/bin/feina-stack-op-enable 2>/dev/null || true
supervisorctl restart hermes-gateway 2>/dev/null || true
""".strip()

template = {
    "api_version": "orgo.ai/v1",
    "template": {
        "name": NAME,
        "version": VERSION,
        "description": (
            "Feina Stack — headless Hermes client agent (Telegram interface). "
            "Advanced integrations (AgentPhone, X, Linear, …) ship installed but disabled; "
            "enable per client with `feina enable`. Orgo control never enabled on clients."
        ),
        "publisher": "orgo",
        "license": "MIT",
        "homepage": "https://github.com/victorioussol/Feina",
        "source": "https://github.com/victorioussol/Feina",
    },
    "hardware": {
        "cpu": 2,
        "ram_gb": 4,
        "disk_gb": 20,
        "resolution": "1280x720x24",
    },
    "secrets": [
        {"name": "op_service_account_token", "optional": True,
         "description": "1Password service-account token (ops_…) for vault Feina - <Client>.",
         "example": "ops_...", "docs_url": "https://developer.1password.com/docs/service-accounts/"},
        {"name": "composio_consumer_key", "optional": True,
         "description": "Composio consumer key (ck_…).", "example": "ck_...", "docs_url": "https://app.composio.dev"},
        {"name": "agentmail_api_key", "optional": True,
         "description": "AgentMail key (am_…).", "example": "am_...", "docs_url": "https://agentmail.to"},
        {"name": "agentmail_inbox", "optional": True,
         "description": "Agent inbox address.", "example": "client@agentmail.to"},
        {"name": "latitude_api_key", "optional": True,
         "description": "Latitude API key (optional until Feina enables tracing).",
         "docs_url": "https://latitude.so"},
        {"name": "latitude_project", "optional": True,
         "description": "Latitude project slug, e.g. feina-vince.", "example": "feina-vince"},
        {"name": "telegram_bot_token", "optional": True,
         "description": "Usually minted by feina-onboard telegram-qr.", "example": "123456789:AA..."},
        {"name": "telegram_allowed_users", "optional": True,
         "description": "Comma-separated Telegram user ids.", "example": "123456789"},
        {"name": "openrouter_api_key", "optional": True,
         "description": "OpenRouter key when not using ChatGPT OAuth.", "example": "sk-or-..."},
        {"name": "owner_email", "optional": True,
         "description": "Optional notify address.", "example": "owner@example.com"},
        {"name": "agentphone_api_key", "optional": True,
         "description": "AgentPhone (off until feina enable agentphone + keys).", "example": "sk_live_..."},
        {"name": "agentphone_agent_id", "optional": True, "description": "AgentPhone agent id.", "example": "cm..."},
        {"name": "vidiq_mcp_api_key", "optional": True, "description": "vidIQ MCP (off by default)."},
        {"name": "ideabrowser_key", "optional": True, "description": "IdeaBrowser MCP (off by default)."},
        {"name": "x_app_only_bearer_token", "optional": True, "description": "X API app-only MCP (off by default)."},
    ],
    "build": {
        "apt": ["git", "xz-utils", "python3-yaml", "ripgrep", "ffmpeg"],
    },
    "files": files,
    "apps": [
        {
            "name": "hermes-gateway",
            "title": "Hermes Gateway",
            "description": "Feina client Hermes gateway (Telegram, Composio, AgentMail, vault MCP).",
            "install": INSTALL,
            "services": [
                {
                    "name": "hermes-gateway",
                    "title": "Hermes gateway",
                    "run": "/usr/local/bin/hermes-gateway-run.sh",
                    "user": "root",
                    "restart": "always",
                },
                {
                    "name": "agentphone-bridge",
                    "title": "AgentPhone webhook bridge",
                    "run": "/usr/local/bin/feina-stack-agentphone-bridge-run.sh",
                    "user": "root",
                    "restart": "always",
                },
            ],
            "autostart": [],
        }
    ],
    "hooks": {
        "on_first_boot": ON_FIRST_BOOT,
        "on_resume": ON_RESUME,
    },
    "terminal": [
        {
            "name": "hermes",
            "title": "Hermes",
            "description": "Host shell (feina-onboard, logs).",
            "cwd": "/root",
        }
    ],
}


def local_validate():
    try:
        import jsonschema
    except ImportError:
        print("! jsonschema not installed — skipping local schema check")
        return
    schema = None
    for p in (os.path.join(HERE, "template-schema.json"),
              os.path.join(HERE, "..", "..", "docs", "orgo", "template-schema.json")):
        if os.path.exists(p):
            with open(p) as fh:
                schema = json.load(fh)
            break
    if schema is None:
        try:
            req = urllib.request.Request(f"{API_BASE}/template-schema")
            with urllib.request.urlopen(req, context=_SSL, timeout=20) as r:
                schema = json.loads(r.read().decode())
        except Exception as e:
            print(f"! could not load schema ({e}); skipping local check")
            return
    jsonschema.validate(template, schema)
    print("✓ local jsonschema validation PASSED")


def _req(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, context=_SSL) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def remote_validate():
    st, body = _req("POST", f"{API_BASE}/templates/validate", template)
    print(f"POST /templates/validate → {st}: {body[:400]}")
    return st < 300


def publish():
    envelope = {"namespace": NAMESPACE, "name": NAME, "version": VERSION, "template": template}
    st, body = _req("POST", f"{API_BASE}/templates", envelope)
    print(f"POST /templates → {st}: {body[:400]}")
    return st < 300 or st == 409


def build_and_stream():
    st, body = _req("POST", f"{API_BASE}/templates/{NAMESPACE}/{NAME}/{VERSION}/build")
    print(f"POST …/build → {st}: {body[:200]}")
    url = f"{API_BASE}/templates/{NAMESPACE}/{NAME}/{VERSION}/build/events"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}"})
    print("streaming build events (SSE):")
    ok = False
    with urllib.request.urlopen(req, timeout=600, context=_SSL) as r:
        for line in r:
            s = line.decode(errors="replace").rstrip()
            if s:
                print("  " + s)
            if s.startswith("data: "):
                try:
                    event = json.loads(s.removeprefix("data: "))
                except json.JSONDecodeError:
                    event = {}
                if event.get("phase") == "ready" and event.get("level") == "success":
                    ok = True
                if event.get("phase") == "failed" or event.get("level") == "error":
                    ok = False
    return ok


def launch(ws_id):
    body = {
        "workspace_id": ws_id,
        "name": "feina-stack-test",
        "template_ref": f"{NAMESPACE}/{NAME}@{VERSION}",
        "ram": 4,
        "cpu": 2,
    }
    st, resp = _req("POST", f"{API_BASE}/computers", body)
    print(f"POST /computers → {st}: {resp[:400]}")


def main():
    args = sys.argv[1:]
    out = os.path.join(HERE, "feina-stack.resolved.json")
    with open(out, "w") as fh:
        json.dump(template, fh, indent=2)
    n_files = len(template["files"])
    approx = sum(len(f.get("inline", "")) for f in template["files"])
    print(f"assembled template v{VERSION}: {n_files} files, ~{approx//1024}KB inline → {out}")
    local_validate()
    if "--remote-validate" in args:
        remote_validate()
    if "--publish" in args or "--build" in args:
        if not API_KEY:
            sys.exit("ORGO_API_KEY not set")
        if not publish():
            sys.exit("publish failed")
    if "--build" in args:
        if not build_and_stream():
            sys.exit("build did not reach ready")
        print("✓ build ready")
    if "--launch" in args:
        i = args.index("--launch")
        launch(args[i + 1])


if __name__ == "__main__":
    main()
