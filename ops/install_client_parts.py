#!/usr/bin/env python3
"""Copy Feina client parts onto a Hermes home. Does not register cron and does not deploy.

Run it on the client computer only after a person has approved that step.
Default is a dry run. ``--apply`` writes files under ``--dest`` (a Hermes home
directory). Cron commands are written to a shell file and are not executed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC_SCRIPTS = REPO / "files" / "scripts"
SRC_SKILLS = REPO / "files" / "skills" / "client-drop"
sys.path.insert(0, str(SRC_SCRIPTS))

from feina_client.runtime import backup_file, load_yaml  # noqa: E402

PARTS = (
    "membr-download",
    "membr-login-guard",
    "telegram-background",
    "proactive-starters",
    "afsa-ingresos",
    "afsa-evals",
)

SCRIPT_NAMES = (
    "membr_download.py",
    "membr_login_check.py",
    "membr_login_watch.py",
    "afsa_nightly.py",
    "afsa_reconcile.py",
    "feina_telegram_turn.py",
    "feina_with_lock.py",
    "feina_proactive.py",
    "feina_reminders.py",
    "feina_eval_workbook.py",
    "feina_eval_steps.py",
    "feina_eval_session.py",
    "feina_eval_skill_hash.py",
)

BANNED_SNIPPETS = ("ORGO_API_KEY=", "hooks.slack.com/", "BEGIN OPENSSH PRIVATE KEY")


def _scan(path: Path) -> None:
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_file() and not child.name.endswith((".pyc",)):
                _scan(child)
        return
    if path.suffix not in {".py", ".md", ".yaml", ".yml", ".example"} and path.name != "AGENTS.md":
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    for snippet in BANNED_SNIPPETS:
        if snippet in text:
            raise SystemExit(f"refusing to copy {path}: contains {snippet}")


def cron_lines(enabled: list[str]) -> str:
    jobs = load_yaml(SRC_SKILLS / "cron" / "jobs.yaml").get("jobs") or []
    lines = [
        "#!/bin/sh",
        "# Review and run these yourself. This installer does not execute them.",
        "# The computer timezone must be Europe/Madrid.",
        "set -e",
    ]
    for job in jobs:
        if not job.get("register"):
            continue
        if job["part"] not in enabled:
            continue
        args = list(job.get("args") or [])
        # Hermes v0.21.7 --script is a file with no argv. Jobs that need
        # arguments register the wrapper written next to the scripts.
        script = f"{job['id'].replace('-', '_')}.py" if args else job["script"]
        lines.append(
            f"hermes cron create \"{job['schedule']}\" --no-agent --script {script} "
            f"--deliver {job['deliver']} --name \"{job['id']}\""
        )
    lines.append("")
    return "\n".join(lines)


def wrapper_body(script: str, args: list[str]) -> str:
    return (
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "here = Path(__file__).resolve().parent\n"
        f"os.execv(sys.executable, [sys.executable, str(here / '{script}'), {', '.join(repr(a) for a in args)}])\n"
    )


def apply(dest: Path, enabled: list[str], backup_root: Path) -> None:
    _scan(SRC_SCRIPTS / "feina_client")
    for name in SCRIPT_NAMES:
        _scan(SRC_SCRIPTS / name)
    scripts = dest / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    package = scripts / "feina_client"
    if package.exists():
        backup_file(package / "__init__.py", backup_root) if (package / "__init__.py").is_file() else None
    shutil.copytree(SRC_SCRIPTS / "feina_client", package, dirs_exist_ok=True)
    for name in SCRIPT_NAMES:
        target = scripts / name
        if target.exists():
            backup_file(target, backup_root)
        shutil.copy2(SRC_SCRIPTS / name, target)
        os.chmod(target, 0o755)
    jobs = load_yaml(SRC_SKILLS / "cron" / "jobs.yaml").get("jobs") or []
    for job in jobs:
        if job["part"] not in enabled or not job.get("args"):
            continue
        wrap = scripts / f"{job['id'].replace('-', '_')}.py"
        if wrap.exists():
            backup_file(wrap, backup_root)
        wrap.write_text(wrapper_body(job["script"], job["args"]), encoding="utf-8")
        os.chmod(wrap, 0o755)
    skills = dest / "skills" / "client-drop"
    skills.mkdir(parents=True, exist_ok=True)
    for part in PARTS:
        src = SRC_SKILLS / part
        if not src.is_dir():
            continue
        target = skills / part
        if target.exists():
            for child in target.rglob("*"):
                if child.is_file():
                    backup_file(child, backup_root)
        shutil.copytree(src, target, dirs_exist_ok=True)
    client = dest / "feina-client"
    client.mkdir(parents=True, exist_ok=True)
    for name, src in (
        ("client.yaml", SRC_SKILLS / "client.yaml.example"),
        ("membr.reports.yaml", SRC_SKILLS / "membr-download" / "membr.reports.yaml"),
        ("proactive.yaml", SRC_SKILLS / "proactive-starters" / "proactive.yaml"),
    ):
        target = client / name
        if target.exists():
            continue
        shutil.copy2(src, target)
        os.chmod(target, 0o600)
    flag_dir = client / "enabled"
    flag_dir.mkdir(parents=True, exist_ok=True)
    for part in enabled:
        (flag_dir / part).write_text("enabled\n", encoding="utf-8")
    if "telegram-background" in enabled:
        agents = dest.parent / "AGENTS.md" if dest.name == ".hermes" else dest / "AGENTS.md"
        # Prefer the Hermes home's sibling only when dest is ~/.hermes. Callers
        # who pass a scratch directory get AGENTS.md inside that directory.
        if dest.name == ".hermes":
            agents = dest.parent / "AGENTS.md"
        else:
            agents = dest / "AGENTS.md"
        snippet = (SRC_SKILLS / "telegram-background" / "AGENTS.md").read_text(encoding="utf-8")
        if agents.is_file():
            backup_file(agents, backup_root)
            current = agents.read_text(encoding="utf-8")
            if "feina-telegram-background" not in current and snippet not in current:
                agents.write_text(current.rstrip() + "\n\n" + snippet + "\n", encoding="utf-8")
        else:
            agents.write_text(snippet + "\n", encoding="utf-8")
    _install_approved_skill(dest, backup_root)
    commands = dest / "feina-client" / "CRON-COMMANDS.sh"
    if commands.exists():
        backup_file(commands, backup_root)
    commands.write_text(cron_lines(enabled), encoding="utf-8")
    os.chmod(commands, 0o600)


def _install_approved_skill(dest: Path, backup_root: Path) -> None:
    """Copy the approved skill and record its hashes. Do not edit a client's config."""
    src = SRC_SKILLS / "afsa-ingresos" / "approved" / "skill"
    recorded = json.loads((SRC_SKILLS / "afsa-ingresos" / "approved" / "hashes.json").read_text(encoding="utf-8"))
    skill_files = {
        name.split("/", 1)[1]: digest
        for name, digest in (recorded.get("files") or {}).items()
        if name.startswith("skill/")
    }
    target = dest / "skills" / "membr-card-reconciliation"
    if target.exists():
        for child in target.rglob("*"):
            if child.is_file():
                backup_file(child, backup_root)
    shutil.copytree(src, target, dirs_exist_ok=True)
    manifest = dest / "feina-client" / "skill-hashes.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"skill": "membr-card-reconciliation", "files": skill_files}, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(manifest, 0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Feina client parts into a Hermes home")
    parser.add_argument("--dest", required=True, help="Hermes home directory, not a live machine unless you mean it")
    parser.add_argument("--enable", action="append", default=[], choices=PARTS)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", default="")
    args = parser.parse_args(argv)
    enabled = list(dict.fromkeys(args.enable))
    print("parts:", ", ".join(enabled) or "(none)")
    print("cron will NOT be registered. Review CRON-COMMANDS.sh and run it yourself.")
    print(cron_lines(enabled))
    if not args.apply:
        print("dry run: no files written")
        return 0
    dest = Path(args.dest).expanduser()
    backup = Path(args.backup).expanduser() if args.backup else dest / "feina-client" / "backups"
    apply(dest, enabled, backup)
    print(f"applied to {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
