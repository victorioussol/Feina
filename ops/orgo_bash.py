#!/usr/bin/env python3
"""Orgo REST /computers/{id}/bash — shared client with exit_code checking."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class OrgoBashError(RuntimeError):
    """Remote bash command failed (non-zero exit or API error field)."""


def _parse_bash_response(data: Any) -> tuple[str, dict]:
    if isinstance(data, str):
        return data, {}
    if not isinstance(data, dict):
        return str(data), {}
    out = str(data.get("output") or data.get("stdout") or "")
    return out, data


def check_bash_result(data: dict, output: str = "") -> str:
    """Raise OrgoBashError if the API reports failure; return output text."""
    if not data:
        return output
    err = data.get("error")
    if err:
        raise OrgoBashError(f"Orgo bash error field: {err!r}\n{output}".strip())
    if data.get("success") is False:
        raise OrgoBashError(f"Orgo bash success=false\n{output}".strip())
    exit_code = data.get("exit_code")
    if exit_code is None:
        exit_code = data.get("exitCode")
    if exit_code is not None and int(exit_code) != 0:
        raise OrgoBashError(
            f"Orgo bash exit_code={exit_code}\n{output}".strip() or f"exit_code={exit_code}"
        )
    return output


def orgo_bash(
    api_base: str,
    api_key: str,
    computer_id: str,
    command: str,
    *,
    timeout: int = 180,
) -> str:
    url = f"{api_base.rstrip('/')}/computers/{computer_id}/bash"
    body = json.dumps({"command": command, "timeout": timeout}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout + 30) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": raw}
        out, meta = _parse_bash_response(payload)
        raise OrgoBashError(f"Orgo bash HTTP {exc.code}: {meta.get('error', raw)}\n{out}".strip()) from exc

    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return raw
    out, meta = _parse_bash_response(payload)
    return check_bash_result(meta, out)
