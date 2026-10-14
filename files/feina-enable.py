#!/usr/bin/env python3
"""Toggle optional Feina client integrations (MCP servers and plugins)."""
import argparse
import os
import subprocess
import sys

import yaml

CONFIG = "/root/.hermes/config.yaml"

# Never enable on client computers (full-account Orgo key risk).
BLOCKED = frozenset(
    {
        "orgo",
        "orgo-mcp",
        "orgo_desktop",
        "orgo-desktop",
        "orgo-desktop-local",
    }
)

# CLI name -> (kind, config key)
INTEGRATIONS = {
    "agentphone": ("mcp", "agentphone"),
    "agentcard": ("mcp", "agent-cards"),
    "agent-cards": ("mcp", "agent-cards"),
    "vidiq": ("mcp", "vidiq"),
    "x-docs": ("mcp", "x-docs"),
    "xdocs": ("mcp", "x-docs"),
    "xapi": ("mcp", "xapi"),
    "xapi-app-only": ("mcp", "xapi-app-only"),
    "linear": ("mcp", "linear"),
    "ideabrowser": ("mcp", "ideabrowser"),
    "latitude": ("mcp", "latitude"),
    "composio": ("mcp", "composio"),
    "agentmail": ("mcp", "agentmail"),
    "obsidian-vault": ("mcp", "obsidian-vault"),
    "vault": ("mcp", "obsidian-vault"),
    "spotify": ("plugin", "spotify"),
    "xai": ("plugin", "xai"),
    "honcho": ("memory", "honcho"),
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


def set_plugin(cfg, name: str, on: bool):
    plugins = cfg.setdefault("plugins", {})
    enabled = list(plugins.get("enabled") or [])
    disabled = list(plugins.get("disabled") or [])
    if on:
        if name not in enabled:
            enabled.append(name)
        if name in disabled:
            disabled.remove(name)
        # xai ships as a small family
        if name == "xai":
            for extra in ("xai-provider", "web-xai"):
                if extra not in enabled:
                    enabled.append(extra)
                if extra in disabled:
                    disabled.remove(extra)
    else:
        if name in enabled:
            enabled.remove(name)
        if name not in disabled:
            disabled.append(name)
        if name == "xai":
            for extra in ("xai-provider", "web-xai"):
                if extra in enabled:
                    enabled.remove(extra)
                if extra not in disabled:
                    disabled.append(extra)
    plugins["enabled"] = enabled
    plugins["disabled"] = disabled


def set_honcho(cfg, on: bool):
    mem = cfg.setdefault("memory", {})
    mem["provider"] = "honcho" if on else ""


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
    for name in ("spotify", "xai", "xai-provider", "web-xai", "orgo-desktop-local"):
        if name in en:
            print(f"  {name}: on")
        else:
            print(f"  {name}: off")
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
            f"Refusing to {args.action} {args.name}: Orgo control is not allowed on Feina client computers.",
            file=sys.stderr,
        )
        sys.exit(2)

    if key not in INTEGRATIONS:
        print(f"Unknown integration '{args.name}'. Known: {', '.join(sorted(INTEGRATIONS))}", file=sys.stderr)
        sys.exit(1)

    kind, target = INTEGRATIONS[key]
    cfg = load_cfg()
    on = args.action == "enable"
    if kind == "mcp":
        set_mcp(cfg, target, on)
    elif kind == "plugin":
        set_plugin(cfg, target, on)
    elif kind == "memory":
        set_honcho(cfg, on)
    save_cfg(cfg)
    print(f"{target}: {'enabled' if on else 'disabled'}")
    restart_gateway()


if __name__ == "__main__":
    main()
