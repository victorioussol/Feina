#!/usr/bin/env python3
"""Regression tests for feina-vince launch fixes (no VM required)."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


class OrgoEnvDetectionTests(unittest.TestCase):
    def test_no_false_positive_without_orgo_keys(self) -> None:
        """grep|wc under pipefail must not look like ORGO keys are present."""
        with tempfile.TemporaryDirectory() as td:
            env = Path(td) / ".env"
            env.write_text("TELEGRAM_BOT_TOKEN=abc\nHONCHO_WORKSPACE_ID=feina-vince\n")
            script = f"""
set -euo pipefail
ENV_FILE="{env}"
HERMES_HOME="{td}"
if grep -qE '^ORGO_API_KEY=|^ORGO_DEFAULT_COMPUTER_ID=' "$ENV_FILE" /root/.env 2>/dev/null; then
  exit 1
fi
exit 0
"""
            r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


class HermesPathTests(unittest.TestCase):
    def test_node_glob_prepends_tools_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            node_bin = Path(td) / "tools" / "node-v22.0.0" / "bin"
            node_bin.mkdir(parents=True)
            (node_bin / "node").write_text("")
            script = f"""
export HERMES_HOME="{td}"
. files/feina-hermes-path.sh
feina_prepend_hermes_node_path
case ":$PATH:" in *":{node_bin}:"*) exit 0;; *) exit 1;; esac
"""
            r = subprocess.run(["bash", "-c", script], cwd=Path(__file__).resolve().parents[1])
            self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
