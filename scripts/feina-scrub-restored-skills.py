#!/usr/bin/env python3
"""Scrub operator-specific names from restored skill content (keep how-to docs)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "files" / "skills"

OPS_HEADER = """\
> **Feina ops only.** Orgo fleet/desktop/template workflows belong on Feina's **operator** environment — **never** enable `orgo` MCP, `orgo_desktop`, or `computer_use` on a **client** computer. **Do not** write `ORGO_API_KEY` or `ORGO_DEFAULT_COMPUTER_ID` into a client VM's `~/.hermes/.env` or `/root/.env` (client bootstrap strips them).

"""

REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bDewey\b"), "Feina ops host"),
    (re.compile(r"\bdewey\b"), "feina-ops"),
    (re.compile(r"Dewey-", re.I), "FeinaOps-"),
    (re.compile(r"nickvasiles\b", re.I), "example-channel"),
    (re.compile(r"nickvasilescu/orgo-mcp", re.I), "orgo-ai/orgo-mcp"),
    (re.compile(r"nickvasilescu", re.I), "victorioussol"),
    (re.compile(r"nicks-stack", re.I), "feina-stack"),
    (re.compile(r"Nick Vasilescu", re.I), "Example Operator"),
    (re.compile(r"Nick preference", re.I), "Operator preference"),
    (re.compile(r"spencer@orgo\.ai", re.I), "support@orgo.ai"),
    (re.compile(r"tiger@orgo\.ai", re.I), "support@orgo.ai"),
    (re.compile(r"michael@momentumamp\.com", re.I), "client@example.com"),
    (re.compile(r"nickv@testkey\.com", re.I), "test@example.com"),
    (re.compile(r"granola_mcp", re.I), "meeting_notes_mcp"),
    (re.compile(r"opticalresourcesgroup@gmail\.com", re.I), "client@example.com"),
    (
        re.compile(r"hermes mcp add orgo[^\n]*", re.I),
        "Configure the orgo MCP via Hermes CLI (`mcp add` for server `orgo`) on a Feina ops machine only",
    ),
    (re.compile(r"ef2f6e29-3864-494b-a82c-15280c5d9f9e"), "<example-computer-id>"),
    (re.compile(r"unless Nick asks", re.I), "unless Feina ops directs"),
    (re.compile(r"\bNick-specific\b", re.I), "Operator-specific"),
    (re.compile(r"\bNick\b(?!\s+Vasilescu)"), "the operator"),
]

DROP_LINE_PATTERNS = [
    re.compile(r"CC Nick", re.I),
    re.compile(r"always CC", re.I),
    re.compile(r"OWNER_EMAIL.*Mark approval", re.I),
]


def scrub_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if any(p.search(line) for p in DROP_LINE_PATTERNS):
            continue
        lines.append(line)
    text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    for pat, repl in REPLACEMENTS:
        text = pat.sub(repl, text)
    return text


def prepend_ops_header(skill_md: Path) -> None:
    text = skill_md.read_text(encoding="utf-8")
    if "Feina ops only" in text[:800]:
        return
    # After YAML front matter if present
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            end = text.find("\n", end + 4)
            text = text[: end + 1] + "\n" + OPS_HEADER + text[end + 1 :]
        else:
            text = OPS_HEADER + text
    else:
        text = OPS_HEADER + text
    skill_md.write_text(text, encoding="utf-8")


def rewrite_dewey_session(path: Path) -> None:
    path.write_text(
        """# Example Orgo ops session (Feina operators)

Session notes pattern for configuring Orgo from a **Feina ops machine** — not from a client agent VM.

## Target computer (example)

```text
name: example-ops-box
workspace: <feina-workspace>
computer_id: <example-computer-id>
os: linux
cpu: 8
ram_gb: 32
expected status: running
```

## CLI setup

```bash
curl -fsSL https://orgo.ai/install.sh | bash
export PATH="$HOME/.local/bin:$HOME/.orgo/node/bin:$PATH"
orgo --version
orgo computers list
```

## API key handling

- Keep `ORGO_API_KEY` on the **ops workstation** or in Feina's launch vault only.
- **Never** export `ORGO_API_KEY` into a client computer's `~/.hermes/.env` — `feina-stack` bootstrap strips it.

## Orgo MCP (ops only)

Configure stdio MCP from an ops environment when fleet control is required. Client agents must keep `orgo` MCP disabled (`feina enable orgo` is refused).

See the parent skill `orgo-cloud-computers` for REST/MCP patterns without pasting live secrets into chat.
""",
        encoding="utf-8",
    )


def main() -> None:
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in (".md", ".py", ".sh", ".yaml", ".yml"):
            continue
        if path.name == "dewey-orgo-session.md":
            rewrite_dewey_session(path)
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        new = scrub_text(raw)
        if new != raw:
            path.write_text(new, encoding="utf-8")

    for skill in ("orgo-cloud-computers", "orgo-desktop-local", "orgo-template-creation"):
        prepend_ops_header(ROOT / "computer-use" / skill / "SKILL.md")

    print("scrub-restored-skills: done")


if __name__ == "__main__":
    main()
