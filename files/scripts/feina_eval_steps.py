#!/usr/bin/env python3
"""Step budget: under 15 model calls and under 20 minutes. Silent when it passes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feina_client.cliutil import enabled  # noqa: E402
from feina_client.evals import step_budget  # noqa: E402
from feina_client.jobs import load_night  # noqa: E402
from feina_client.runtime import madrid_now, post_ops_alert  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    del argv
    if not enabled("afsa-evals"):
        return 0
    now = madrid_now()
    record = load_night(now.date().isoformat())
    ok, reason = step_budget(record)
    if not ok:
        post_ops_alert(reason, part="afsa-evals", when=now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
