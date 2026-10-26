#!/usr/bin/env python3
"""Run a command while holding the AFSA lock. Exit 75 if the night job has it."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feina_client.jobs import run_with_lock  # noqa: E402
from feina_client.runtime import JobLock  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        sys.stderr.write("usage: feina_with_lock.py -- command\n")
        return 2
    return run_with_lock(argv, JobLock())


if __name__ == "__main__":
    raise SystemExit(main())
