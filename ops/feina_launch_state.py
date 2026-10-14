#!/usr/bin/env python3
"""Feina ops: per-client launch state under ~/.feina/clients/<slug>/"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLIENTS_ROOT = Path(
    os.environ.get("FEINA_CLIENTS_DIR", os.path.expanduser("~/.feina/clients"))
)


def safe_slug(slug: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]", "-", slug.strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        raise ValueError("invalid client slug")
    return s


def client_dir(slug: str) -> Path:
    d = CLIENTS_ROOT / safe_slug(slug)
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def launch_path(slug: str) -> Path:
    return client_dir(slug) / "launch.json"


def honcho_path(slug: str) -> Path:
    return client_dir(slug) / "honcho.json"


def load_launch(slug: str) -> dict[str, Any]:
    p = launch_path(slug)
    if not p.is_file():
        return {"slug": safe_slug(slug), "phases": {}}
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {"slug": safe_slug(slug), "phases": {}}
    if not isinstance(data, dict):
        return {"slug": safe_slug(slug), "phases": {}}
    data.setdefault("slug", safe_slug(slug))
    data.setdefault("phases", {})
    return data


def save_launch(slug: str, data: dict[str, Any]) -> None:
    p = launch_path(slug)
    p.write_text(json.dumps(data, indent=2) + "\n")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def phase_done(data: dict[str, Any], key: str) -> bool:
    phases = data.get("phases") or {}
    ph = phases.get(key) or {}
    return bool(ph.get("completed_at"))


def mark_phase(data: dict[str, Any], key: str, **fields: Any) -> dict[str, Any]:
    phases = data.setdefault("phases", {})
    entry = dict(phases.get(key) or {})
    entry["completed_at"] = utc_now()
    for k, v in fields.items():
        entry[k] = v
    phases[key] = entry
    return data
