#!/usr/bin/env python3
"""Apply Feina Honcho memory policy before each gateway start (fail-open)."""
from __future__ import annotations

import os

import yaml

CONFIG = "/root/.hermes/config.yaml"
DISABLED_FLAG = "/var/lib/orgo/feina-honcho-disabled"


def load_cfg():
    with open(CONFIG) as fh:
        return yaml.safe_load(fh) or {}


def save_cfg(cfg):
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as fh:
        yaml.safe_dump(cfg, fh, default_flow_style=False, sort_keys=False, allow_unicode=True, width=1000)
    os.replace(tmp, CONFIG)
    os.chmod(CONFIG, 0o600)


def effective_provider() -> str:
    if os.path.isfile(DISABLED_FLAG):
        return ""
    key = os.environ.get("HONCHO_API_KEY", "").strip()
    if not key:
        return ""
    return "honcho"


def main() -> int:
    if not os.path.isfile(CONFIG):
        return 0
    cfg = load_cfg()
    mem = cfg.setdefault("memory", {})
    mem.setdefault("memory_enabled", True)
    want = effective_provider()
    cur = (mem.get("provider") or "").strip()
    if cur != want:
        mem["provider"] = want
        save_cfg(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
