#!/usr/bin/env python3
"""Test double for the approved checks. Production does not ship this logic."""

import os
import sys

body = os.environ.get("FEINA_TEST_CHECKS_JSON", "")
if not body:
    sys.stderr.write("no fixture result\n")
    raise SystemExit(2)
sys.stdout.write(body)
