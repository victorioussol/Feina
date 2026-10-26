"""Call the approved AFSA scripts. Do not reimplement them.

The copies under afsa-ingresos/approved/ are the production scripts and the
approved membr-card-reconciliation skill. Their sha256 values are in
hashes.json. A mismatch means the day is not checked.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .runtime import client_root, hermes_home, sha256_file


def approved_roots() -> list[Path]:
    env = os.environ.get("FEINA_AFSA_APPROVED", "")
    roots = []
    if env:
        roots.append(Path(env).expanduser())
    roots.append(client_root() / "approved")
    roots.append(hermes_home() / "skills" / "client-drop" / "afsa-ingresos" / "approved")
    roots.append(hermes_home() / "skills" / "afsa-ingresos" / "approved")
    roots.append(Path(__file__).resolve().parents[3] / "files" / "skills" / "client-drop" / "afsa-ingresos" / "approved")
    return roots


def find_approved() -> dict | None:
    """Return the script paths only when every recorded hash matches."""
    for root in approved_roots():
        manifest = root / "hashes.json"
        checks = root / "afsa_checks.py"
        update = root / "update_workbook.py"
        if not manifest.is_file() or not checks.is_file() or not update.is_file():
            continue
        recorded = json.loads(manifest.read_text(encoding="utf-8")).get("files") or {}
        mismatched = [name for name, digest in recorded.items() if sha256_file(root / name) != digest]
        if mismatched:
            return {"root": root, "ok": False, "mismatched": mismatched}
        skill = root / "skill"
        return {
            "root": root,
            "ok": True,
            "checks": checks,
            "update": update,
            "skill": skill if skill.is_dir() else None,
            "hashes": recorded,
            "mismatched": [],
        }
    return None


def _run(script: Path, args: list[str]) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        timeout=180,
    )
    line = ""
    for candidate in reversed(proc.stdout.splitlines()):
        if candidate.strip():
            line = candidate.strip()
            break
    try:
        data = json.loads(line) if line else {"result": "ERROR", "problems": ["checks_output"]}
    except json.JSONDecodeError:
        data = {"result": "ERROR", "problems": ["checks_output"]}
    if not isinstance(data, dict):
        data = {"result": "ERROR", "problems": ["checks_output"]}
    data["returncode"] = proc.returncode
    return data


def _slack_flag(enabled: bool) -> list[str]:
    return ["--slack-on-fail"] if enabled else []


def run_export(checks: Path, *, business_date: str, xlsx: Path, slack_on_fail: bool = True) -> dict:
    """`afsa_checks.py export --business-date D XLSX`."""
    return _run(
        checks,
        ["export", "--business-date", business_date, *_slack_flag(slack_on_fail), str(xlsx)],
    )


def run_dates(
    checks: Path,
    *,
    business_date: str,
    pdfs: list[Path],
    evidence: list[Path] | None = None,
    slack_on_fail: bool = True,
) -> dict:
    """`afsa_checks.py dates --business-date D [--evidence JSON]... PDF...`."""
    args = ["dates", "--business-date", business_date, *_slack_flag(slack_on_fail)]
    for path in evidence or []:
        args.extend(["--evidence", str(path)])
    args.extend(str(path) for path in pdfs)
    return _run(checks, args)


def run_update(script: Path, *, source: Path, payload: Path, output: Path) -> dict:
    """`update_workbook.py SOURCE.xlsx PAYLOAD.json OUTPUT.xlsx`."""
    return _run(script, [str(source), str(payload), str(output)])


def run_final(
    checks: Path,
    *,
    business_date: str,
    since: str | None = None,
    slack_on_fail: bool = True,
) -> dict:
    """`afsa_checks.py final --business-date D [--since ISO]`. This is the only verifying step."""
    args = ["final", "--business-date", business_date, *_slack_flag(slack_on_fail)]
    if since:
        args.extend(["--since", since])
    return _run(checks, args)


def run_gaps(checks: Path, *, business_date: str, slack_on_fail: bool = True) -> dict:
    """`afsa_checks.py gaps --business-date D`. The skill passes the day after the business date."""
    return _run(checks, ["gaps", "--business-date", business_date, *_slack_flag(slack_on_fail)])
