#!/usr/bin/env python3
"""Alert Slack when the installed membr-card-reconciliation skill no longer matches the approved hashes.

This does not edit the skill and does not change Hermes background review.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feina_client.cliutil import enabled  # noqa: E402
from feina_client.evals import skill_hash_eval  # noqa: E402
from feina_client.runtime import client_root, hermes_home, madrid_now, post_ops_alert  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    del argv
    if not enabled("afsa-evals"):
        return 0
    recorded_path = client_root() / "skill-hashes.json"
    skill_dir = hermes_home() / "skills" / "membr-card-reconciliation"
    recorded = {}
    if recorded_path.is_file():
        recorded = json.loads(recorded_path.read_text(encoding="utf-8"))
    ok, reason = skill_hash_eval(recorded, skill_dir)
    if not ok:
        post_ops_alert(reason, part="afsa-evals", when=madrid_now())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
