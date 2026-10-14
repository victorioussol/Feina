#!/usr/bin/env python3
"""Toggle optional Feina client integrations (MCP servers and plugins)."""
import argparse
import os
import subprocess
import sys

import yaml

CONFIG = "/root/.hermes/config.yaml"
AGENTPHONE_FLAG = "/var/lib/orgo/feina-agentphone-enabled"

BLOCKED = frozenset(
    {
        "orgo",
        "orgo-mcp",
        "orgo_desktop",
        "orgo-desktop",
        "orgo-desktop-local",
        "computer-use",
        "computer_use",
    }
)

INTEGRATIONS = {
    "agentphone": ("mcp", "agentphone", "agentphone_bridge"),
    "agentcard": ("mcp", "agent-cards", None),
    "agent-cards": ("mcp", "agent-cards", None),
    "vidiq": ("mcp", "vidiq", None),
    "x-docs": ("mcp", "x-docs", None),
    "xdocs": ("mcp", "x-docs", None),
    "xapi": ("mcp", "xapi", None),
    "xapi-app-only": ("mcp", "xapi-app-only", None),
    "linear": ("mcp", "linear", None),
    "ideabrowser": ("mcp", "ideabrowser", None),
    "latitude": ("mcp", "latitude", None),
    "composio": ("mcp", "composio", None),
    "agentmail": ("mcp", "agentmail", None),
    "obsidian-vault": ("mcp", "obsidian-vault", None),
    "vault": ("mcp", "obsidian-vault", None),
    "spotify": ("plugin", "spotify", "spotify_toolset"),
    "xai": ("plugin", "xai", None),
    "openrouter": ("plugin", "openrouter", "openrouter_family"),
    "anthropic": ("plugin", "anthropic-provider", None),
    "honcho": ("memory", "honcho", None),
}


def load_cfg():
    with open(CONFIG) as fh:
        return yaml.safe_load(fh) or {}


def save_cfg(cfg):
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as fh:
        yaml.safe_dump(cfg, fh, default_flow_style=False, sort_keys=False, allow_unicode=True, width=1000)
    os.replace(tmp, CONFIG)
    os.chmod(CONFIG, 0o600)


def set_mcp(cfg, name: str, on: bool):
    mcp = cfg.setdefault("mcp_servers", {})
    if name not in mcp:
        raise SystemExit(f"Unknown MCP server in config: {name}")
    mcp[name]["enabled"] = on


def set_plugin(cfg, name: str, on: bool, family: str | None = None):
    plugins = cfg.setdefault("plugins", {})
    enabled = list(plugins.get("enabled") or [])
    disabled = list(plugins.get("disabled") or [])

    def add(p):
        if p not in enabled:
            enabled.append(p)
        if p in disabled:
            disabled.remove(p)

    def rem(p):
        if p in enabled:
            enabled.remove(p)
        if p not in disabled:
            disabled.append(p)

    targets = [name]
    if family == "openrouter_family":
        targets = ["openrouter", "openrouter-provider"]
    if name == "xai" or family == "xai":
        targets = ["xai", "xai-provider", "web-xai"]

    for p in targets:
        (add if on else rem)(p)
    plugins["enabled"] = enabled
    plugins["disabled"] = disabled


def set_spotify_toolset(cfg, on: bool):
    for ch in ("cli", "telegram"):
        tools = cfg.setdefault("platform_toolsets", {}).setdefault(ch, [])
        if on and "spotify" not in tools:
            tools.append("spotify")
        if not on and "spotify" in tools:
            tools[:] = [t for t in tools if t != "spotify"]


def set_honcho(cfg, on: bool):
    mem = cfg.setdefault("memory", {})
    mem["provider"] = "honcho" if on else ""


def agentphone_bridge(on: bool):
    os.makedirs("/var/lib/orgo", exist_ok=True)
    if on:
        open(AGENTPHONE_FLAG, "w").close()
        subprocess.run(["supervisorctl", "start", "agentphone-bridge"], check=False)
    else:
        try:
            os.remove(AGENTPHONE_FLAG)
        except OSError:
            pass
        subprocess.run(["supervisorctl", "stop", "agentphone-bridge"], check=False)


def restart_gateway():
    subprocess.run(["supervisorctl", "restart", "hermes-gateway"], check=False)


def cmd_list(cfg):
    print("MCP servers:")
    for name, spec in sorted((cfg.get("mcp_servers") or {}).items()):
        en = spec.get("enabled", False)
        flag = "on" if en else "off"
        block = " (BLOCKED on Feina clients)" if name == "orgo" else ""
        print(f"  {name}: {flag}{block}")
    print("Plugins (selected):")
    en = set(cfg.get("plugins", {}).get("enabled") or [])
    for name in (
        "spotify",
        "xai",
        "openrouter",
        "openrouter-provider",
        "anthropic-provider",
        "orgo-desktop-local",
    ):
        print(f"  {name}: {'on' if name in en else 'off'}")
    ap = "on" if os.path.isfile(AGENTPHONE_FLAG) else "off"
    print(f"agentphone-bridge service flag: {ap}")
    print(f"memory.provider: {cfg.get('memory', {}).get('provider') or '(empty)'}")


def main():
    parser = argparse.ArgumentParser(description="Enable/disable optional Feina integrations")
    parser.add_argument("action", choices=["enable", "disable", "list"])
    parser.add_argument("name", nargs="?", help="Integration name (see feina list)")
    args = parser.parse_args()

    if args.action == "list":
        cmd_list(load_cfg())
        return

    if not args.name:
        parser.error("name required")
    key = args.name.lower().replace("_", "-")
    if key in BLOCKED:
        print(
            f"Refusing to {args.action} {args.name}: not allowed on Feina client computers.",
            file=sys.stderr,
        )
        sys.exit(2)

    if key not in INTEGRATIONS:
        print(f"Unknown integration '{args.name}'. Known: {', '.join(sorted(INTEGRATIONS))}", file=sys.stderr)
        sys.exit(1)

    kind, target, extra = INTEGRATIONS[key]
    cfg = load_cfg()
    on = args.action == "enable"
    if kind == "mcp":
        set_mcp(cfg, target, on)
        if extra == "agentphone_bridge":
            agentphone_bridge(on)
    elif kind == "plugin":
        set_plugin(cfg, target, on, extra)
    elif kind == "memory":
        set_honcho(cfg, on)
    if extra == "spotify_toolset":
        set_spotify_toolset(cfg, on)
    elif kind == "plugin" and target == "spotify":
        set_spotify_toolset(cfg, on)
    save_cfg(cfg)
    print(f"{target}: {'enabled' if on else 'disabled'}")
    restart_gateway()


if __name__ == "__main__":
    main()
