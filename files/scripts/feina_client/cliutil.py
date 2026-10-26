"""Shared argv helpers for the Hermes script entrypoints."""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

from .runtime import client_root, load_yaml, madrid_now, part_enabled


def boot() -> None:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def enabled(name: str) -> bool:
    if os.environ.get("FEINA_FORCE") == "1":
        return True
    return part_enabled(name)


def resolve_business_date(token: str | None) -> str:
    if not token or token == "yesterday":
        return (madrid_now().date() - timedelta(days=1)).isoformat()
    return token


def membr_config(path: str | None = None) -> dict:
    if path:
        return load_yaml(Path(path))
    env = os.environ.get("FEINA_MEMBR_CONFIG")
    if env:
        return load_yaml(Path(env))
    candidate = client_root() / "membr.reports.yaml"
    if candidate.is_file():
        return load_yaml(candidate)
    raise SystemExit(2)


def host_ready(cfg: dict) -> bool:
    host = str(cfg.get("club_base_url") or "")
    return "REPLACE" not in host.upper() and "example.membr.com" not in host
