"""Put the client scripts on the path and isolate each test's state directory."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "files" / "scripts"))
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
_AFSA_SHIM = Path(__file__).resolve().parent / "afsa_isolate"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FEINA_CLIENT_ROOT", str(tmp_path))
    monkeypatch.delenv("FEINA_VINCE_SLACK_WEBHOOK", raising=False)
    monkeypatch.delenv("FEINA_OPS_SLACK_WEBHOOK", raising=False)
    monkeypatch.delenv("FEINA_FORCE", raising=False)
    return tmp_path


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def afsa_state(tmp_path, monkeypatch):
    """Point the approved check's hardcoded ledger at a temp directory.

    The child process loads tests/afsa_isolate/sitecustomize.py. The wall
    clock is left alone: afsa_checks.py does not read an env var for it, and
    datetime.datetime.now cannot be replaced from outside that file.
    """
    state = tmp_path / "af-ingresos"
    (state / "runs").mkdir(parents=True)
    monkeypatch.setenv("FEINA_AFSA_STATE_DIR", str(state))
    current = os.environ.get("PYTHONPATH", "")
    prefix = str(_AFSA_SHIM)
    monkeypatch.setenv("PYTHONPATH", prefix + (os.pathsep + current if current else ""))
    return state
