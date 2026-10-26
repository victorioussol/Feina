"""Put the client scripts on the path and isolate each test's state directory."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "files" / "scripts"))
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


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
