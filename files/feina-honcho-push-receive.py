#!/usr/bin/env python3
"""Read Honcho push JSON from stdin, apply via feina-honcho-apply.py, delete temp file."""
from __future__ import annotations

import os
import subprocess
import sys

PATH = "/run/feina/honcho-apply.json"
APPLY = "/usr/local/bin/feina-honcho-apply.py"


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        print("Expected JSON on stdin", file=sys.stderr)
        return 1
    os.makedirs("/run/feina", mode=0o700, exist_ok=True)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(raw)
    os.chmod(PATH, 0o600)
    try:
        with open(PATH, "rb") as inf:
            proc = subprocess.run(
                [sys.executable, APPLY],
                stdin=inf,
                check=False,
            )
        return proc.returncode
    finally:
        try:
            os.remove(PATH)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
