"""Redirect the approved AFSA state directory for a child Python process.

afsa_checks.py hardcodes /root/.hermes/automation/af-ingresos and is run as a
subprocess. It reads no env var for that path, and datetime.datetime is an
immutable builtin, so datetime.now cannot be patched from outside the file.
This module is loaded only when a test puts this directory on PYTHONPATH.
FEINA_AFSA_STATE_DIR then replaces that hardcoded directory. The vendored
script is not edited.
"""

from __future__ import annotations

import os

_STATE = os.environ.get("FEINA_AFSA_STATE_DIR")
_HARD = "/root/.hermes/automation/af-ingresos"

if _STATE:
    import pathlib

    _Posix = pathlib.PosixPath

    class _Redirect(pathlib.Path):
        def __new__(cls, *args, **kwargs):
            if args and isinstance(args, tuple) and isinstance(args[0], str):
                raw = args[0]
                if raw == _HARD or raw.startswith(_HARD + "/"):
                    args = (_STATE + raw[len(_HARD) :],) + args[1:]
            self = _Posix.__new__(_Posix, *args, **kwargs)
            _Posix.__init__(self, *args)
            return self

    pathlib.Path = _Redirect
