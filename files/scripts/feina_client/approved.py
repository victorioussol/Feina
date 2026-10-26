"""Call the approved AFSA scripts. This module does not reimplement them.

Those scripts are not in this template. When they are on the client computer,
the night job feeds them the downloaded files and uses their row unchanged.
No gap and no tolerance is read or applied here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .runtime import client_root, hermes_home, sha256_file


def _candidates() -> list[Path]:
    env_checks = os.environ.get("FEINA_AFSA_CHECKS", "")
    env_update = os.environ.get("FEINA_UPDATE_WORKBOOK", "")
    roots = [
        client_root() / "approved",
        hermes_home() / "scripts",
        hermes_home() / "skills",
        Path(__file__).resolve().parents[1],
        Path(__file__).resolve().parents[3] / "files" / "scripts",
        Path(__file__).resolve().parents[3] / "files" / "skills",
    ]
    return roots, env_checks, env_update


def find_approved() -> dict | None:
    """Return paths only when both approved scripts exist. Otherwise None."""
    roots, env_checks, env_update = _candidates()
    checks = Path(env_checks).expanduser() if env_checks else None
    update = Path(env_update).expanduser() if env_update else None
    if checks is None or update is None:
        for root in roots:
            if checks is None and (root / "afsa_checks.py").is_file():
                checks = root / "afsa_checks.py"
            if update is None and (root / "update_workbook.py").is_file():
                update = root / "update_workbook.py"
    if checks is None or update is None or not checks.is_file() or not update.is_file():
        return None
    spec = _find_spec(roots)
    skill = _find_skill(roots)
    return {
        "checks": checks,
        "update": update,
        "spec": spec,
        "skill": skill,
        "spec_sha256": sha256_file(spec) if spec else "",
    }


def _find_spec(roots: list[Path]) -> Path | None:
    for root in roots:
        direct = root / "references" / "af-ingresos-daily.md"
        if direct.is_file():
            return direct
        if not root.is_dir():
            continue
        for path in root.rglob("af-ingresos-daily.md"):
            return path
    return None


def _find_skill(roots: list[Path]) -> Path | None:
    for root in roots:
        direct = root / "membr-card-reconciliation"
        if direct.is_dir():
            return direct
        nested = root / "skills" / "membr-card-reconciliation"
        if nested.is_dir():
            return nested
    return None


def run_export(
    checks: Path,
    *,
    business_date: str,
    membr: Path,
    paycomet: Path | None,
    harlands: Path | None,
) -> dict:
    """`afsa_checks.py export`. Stdout must be JSON. Figures are not edited."""
    cmd = [
        sys.executable,
        str(checks),
        "export",
        "--date",
        business_date,
        "--membr",
        str(membr),
    ]
    if paycomet is not None:
        cmd.extend(["--paycomet", str(paycomet)])
    if harlands is not None:
        cmd.extend(["--harlands", str(harlands)])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        return {"status": "unverified", "reason": "checks_failed"}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "unverified", "reason": "checks_output"}
    if not isinstance(data, dict):
        return {"status": "unverified", "reason": "checks_output"}
    return data


def run_update(
    script: Path,
    *,
    workbook: Path,
    business_date: str,
    row_number: int,
    cells: list[str],
    row_json: Path,
) -> None:
    row_json.parent.mkdir(parents=True, exist_ok=True)
    row_json.write_text(
        json.dumps({"date": business_date, "row_number": row_number, "cells": cells}),
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        str(script),
        "--workbook",
        str(workbook),
        "--date",
        business_date,
        "--row-number",
        str(row_number),
        "--row-json",
        str(row_json),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError("update_workbook failed")
