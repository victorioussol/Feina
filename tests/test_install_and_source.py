"""Installer dry-run, backups, and the rules the scripts are not allowed to break."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ops.install_client_parts import SCRIPT_NAMES, _scan, apply, cron_lines

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "files" / "scripts" / "feina_client"
SCRIPTS = ROOT / "files" / "scripts"


def test_dry_run_writes_nothing(tmp_path, capsys):
    from ops.install_client_parts import main

    code = main(["--dest", str(tmp_path / "home"), "--enable", "proactive-starters"])
    assert code == 0
    assert not (tmp_path / "home").exists()
    out = capsys.readouterr().out
    assert "dry run" in out
    assert "--script proactive_morning.py" in out
    assert "--script proactive_reminders.py" in out
    assert "--script feina_proactive.py" not in out


def test_apply_backs_up_with_sha256_and_registers_wrappers(tmp_path):
    dest = tmp_path / "hermes"
    scripts = dest / "scripts"
    scripts.mkdir(parents=True)
    original = scripts / "membr_download.py"
    original.write_text("print('old')\n", encoding="utf-8")
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    backup_root = tmp_path / "backups"
    apply(dest, ["membr-download", "proactive-starters", "afsa-ingresos"], backup_root)
    copies = list(backup_root.glob("membr_download.py.*"))
    bodies = [path for path in copies if path.suffix != ".sha256" and not path.name.endswith(".sha256")]
    # backup names are name.stamp.digestprefix, and a sibling .sha256 file.
    hash_files = list(backup_root.glob("*.sha256"))
    assert hash_files
    assert digest in hash_files[0].read_text(encoding="utf-8")
    assert (dest / "feina-client" / "enabled" / "membr-download").is_file()
    assert not (dest / "feina-client" / "enabled" / "afsa-evals").exists()
    commands = (dest / "feina-client" / "CRON-COMMANDS.sh").read_text(encoding="utf-8")
    assert "--script proactive_morning.py" in commands
    assert "--script afsa_nightly.py" in commands
    wrapper = (dest / "scripts" / "proactive_morning.py").read_text(encoding="utf-8")
    assert "feina_proactive.py" in wrapper
    assert "--slot" in wrapper
    assert bodies
    skill = dest / "skills" / "membr-card-reconciliation" / "SKILL.md"
    assert skill.is_file()
    recorded = json.loads((dest / "feina-client" / "skill-hashes.json").read_text(encoding="utf-8"))
    assert recorded["skill"] == "membr-card-reconciliation"
    assert recorded["files"]["SKILL.md"] == hashlib.sha256(skill.read_bytes()).hexdigest()


def test_scan_refuses_orgo_keys_and_slack_hooks(tmp_path):
    banned = tmp_path / "leak.py"
    banned.write_text("ORGO_API_KEY=sk_live_example\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        _scan(banned)
    hook = tmp_path / "hook.md"
    hook.write_text("see hooks.slack.com/services/T/B/x\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        _scan(hook)


def test_client_scripts_do_not_log_in_or_call_hidden_membr_apis():
    banned_tokens = (
        "browser_vault_save_login",
        "ORGO_API_KEY=",
        "hooks.slack.com/",
        "BEGIN OPENSSH PRIVATE KEY",
    )
    paths = [PACKAGE] + [SCRIPTS / name for name in SCRIPT_NAMES]
    for path in paths:
        files = [path] if path.is_file() else [item for item in path.rglob("*") if item.is_file()]
        for item in files:
            if item.suffix not in {".py", ".md", ".yaml", ".yml"}:
                continue
            text = item.read_text(encoding="utf-8")
            for token in banned_tokens:
                assert token not in text, f"{item} contains {token}"
    download = (PACKAGE / "download.py").read_text(encoding="utf-8")
    browser = (PACKAGE / "browser.py").read_text(encoding="utf-8")
    session = (PACKAGE / "session.py").read_text(encoding="utf-8")
    assert "urllib.request" not in download
    assert "import requests" not in download
    assert "/api/" not in download
    assert "keepalive" not in download.lower()
    assert "keep-alive" not in browser.lower()
    assert "SELECT host_key, name, creation_utc, expires_utc FROM cookies" in session
    assert "encrypted_value" not in session.split("SELECT", 1)[-1].split("FROM", 1)[0]


def test_cron_lines_match_jobs_that_need_arguments():
    text = cron_lines(["proactive-starters", "afsa-evals", "membr-login-guard"])
    assert "every day at 9:00" in text
    assert "--deliver telegram" in text
    assert "--deliver local" in text
    assert "feina_eval_workbook.py" in text
    assert "feina_eval_skill_hash.py" in text
