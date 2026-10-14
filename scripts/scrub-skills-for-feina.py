#!/usr/bin/env python3
"""One-off scrub: remove skill files that cannot pass Feina verify patterns."""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "files" / "skills"
BANNED = re.compile(
    r"dewey|nickv|tiger@orgo|momentumamp|spencer@orgo|nickv@testkey|"
    r"ORGO_API_KEY|hermes mcp add orgo|granola_mcp|CC Nick|always CC",
    re.I,
)

STUB_ORGO = """---
name: {name}
description: "Feina client agents: Orgo fleet/desktop control is disabled on this computer. Feina ops runs Orgo tooling separately."
version: 1.0.0
---

# Not available on client computers

This skill documents Orgo operator workflows. **Do not** enable Orgo MCP, set Orgo API keys, or control other computers from a Feina client agent.

For fleet work, use Feina's ops environment.
"""

COMPUTER_USE_SKILLS = [
    "orgo-cloud-computers",
    "orgo-desktop-local",
    "orgo-template-creation",
]


def scrub_computer_use():
    base = ROOT / "computer-use"
    for skill in COMPUTER_USE_SKILLS:
        d = base / skill
        if not d.exists():
            continue
        for sub in ("references", "scripts"):
            p = d / sub
            if p.exists():
                for f in list(p.rglob("*")):
                    if f.is_file():
                        f.unlink()
                for f in sorted(p.rglob("*"), reverse=True):
                    if f.is_dir():
                        f.rmdir()
        name = skill
        (d / "SKILL.md").write_text(STUB_ORGO.format(name=name), encoding="utf-8")


def delete_if_banned(path: Path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if BANNED.search(text):
        path.unlink(missing_ok=True)


def main():
    scrub_computer_use()
    for path in ROOT.rglob("*"):
        if path.is_file() and path.name != "SKILL.md":
            if path.suffix in (".md", ".py", ".sh"):
                delete_if_banned(path)
    print("scrub done")


if __name__ == "__main__":
    main()
