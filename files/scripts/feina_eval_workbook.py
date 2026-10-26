#!/usr/bin/env python3
"""By 06:00 Madrid the AFSA workbook must exist and read back. Silent when it does."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feina_client.cliutil import enabled  # noqa: E402
from feina_client.evals import workbook_eval  # noqa: E402
from feina_client.jobs import load_night  # noqa: E402
from feina_client.runtime import madrid_now, post_ops_alert  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    del argv
    if not enabled("afsa-evals"):
        return 0
    now = madrid_now()
    status = load_night(now.date().isoformat())
    book = Path(status["workbook"]) if status.get("workbook") else None
    ok, reason = workbook_eval(status, book, now)
    if not ok:
        post_ops_alert(reason, part="afsa-evals", when=now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
