"""Download Membr reports by clicking the club's own screens.

The script attaches to the browser profile that is already logged in. It never
types a password, never fills anything except a date, and never calls a Membr
URL other than the configured club home page. If that page is a login or a
captcha, it stops.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .login_page import detect_login_wall, structure_from_html
from .runtime import sha256_file, write_json

EXIT_OK = 0
EXIT_FAILED = 2
EXIT_LOGIN = 10

_BANNED_FILL = re.compile(r"password|passwd|captcha|otp|secret|token", re.IGNORECASE)
_BANNED_CLICK = re.compile(
    r"^(log ?in|sign ?in|iniciar sesi[oó]n|connexion|acceder|captcha|i.?m not a robot|no soy un robot)$",
    re.IGNORECASE,
)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LoginRequired(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class NoProfile(Exception):
    pass


def assert_club_url(url: str, club_base: str) -> None:
    target = urlparse(url)
    base = urlparse(club_base)
    if target.scheme != "https" or not target.hostname:
        raise PermissionError("only https on the club host")
    if target.hostname != base.hostname:
        raise PermissionError("refusing to leave the club host")
    if target.query and re.search(r"token|password|key=", target.query, re.IGNORECASE):
        raise PermissionError("refusing a url that carries a secret")


def assert_safe_fill(selector: str, value: str) -> None:
    if _BANNED_FILL.search(selector or ""):
        raise PermissionError("refusing to type into a credential or captcha field")
    if not _DATE.match(value or ""):
        raise PermissionError("only a YYYY-MM-DD date may be typed")


def assert_safe_click(label: str) -> None:
    if _BANNED_CLICK.match((label or "").strip()):
        raise PermissionError("refusing to click a login or captcha control")


def _wall(session, club_base: str) -> str | None:
    url = session.url()
    assert_club_url(url, club_base)
    return detect_login_wall(url, session.content())


def run_download(
    cfg: dict,
    *,
    business_date: str,
    out_dir: Path,
    session,
    mode: str = "download",
) -> dict:
    """mode is 'download', 'inspect', or 'dry-run'.

    inspect walks the configured clicks and records each page.
    dry-run records only the landing page.
    Both stop on a login wall and neither downloads.
    """
    if mode not in {"download", "inspect", "dry-run"}:
        raise ValueError(mode)
    club = str(cfg["club_base_url"])
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "business_date": business_date,
        "mode": mode,
        "status": "OK",
        "files": [],
        "pages": [],
        "errors": [],
    }
    try:
        session.goto(club)
        wall = _wall(session, club)
        manifest["pages"].append(session.snapshot() if hasattr(session, "snapshot") else structure_from_html(session.url(), session.content()))
        if wall:
            raise LoginRequired(wall)
        if mode == "dry-run":
            manifest["status"] = "INSPECTED"
            _write_manifest(out_dir, manifest)
            return manifest
        for report in cfg.get("reports") or []:
            if report.get("enabled", True) is False:
                continue
            try:
                saved = _one_report(
                    session,
                    report,
                    club_base=club,
                    business_date=business_date,
                    out_dir=out_dir,
                    mode=mode,
                    manifest=manifest,
                )
            except LoginRequired:
                raise
            except Exception as exc:
                manifest["errors"].append({"report": report.get("id"), "error": type(exc).__name__})
                if report.get("required", True) and mode == "download":
                    manifest["status"] = "FAILED"
                    break
                continue
            if saved and mode == "download":
                manifest["files"].append(saved)
        if mode == "inspect":
            manifest["status"] = "INSPECTED"
        elif manifest["status"] == "OK":
            required = [r for r in cfg.get("reports") or [] if r.get("enabled", True) and r.get("required", True)]
            got = {item["report"] for item in manifest["files"]}
            if any(r.get("id") not in got for r in required):
                manifest["status"] = "FAILED"
    except LoginRequired as exc:
        manifest["status"] = "LOGIN_REQUIRED"
        manifest["reason"] = exc.reason
        manifest["files"] = manifest["files"]
    _write_manifest(out_dir, manifest)
    return manifest


def _one_report(session, report, *, club_base, business_date, out_dir, mode, manifest) -> dict | None:
    for step in report.get("steps") or []:
        action = step.get("action")
        if action == "click_text":
            chosen = None
            for label in step.get("texts") or []:
                assert_safe_click(label)
                if session.has_text(label):
                    session.click_text(label)
                    chosen = label
                    break
            if chosen is None and mode == "download":
                raise LookupError(report.get("id") or "report")
            wall = _wall(session, club_base)
            page = session.snapshot() if hasattr(session, "snapshot") else structure_from_html(session.url(), session.content())
            page["after"] = chosen
            manifest["pages"].append(page)
            if wall:
                raise LoginRequired(wall)
        elif action == "fill_date":
            if mode != "download":
                continue
            selector = step.get("selector") or ""
            value = business_date
            assert_safe_fill(selector, value)
            session.fill(selector, value)
            wall = _wall(session, club_base)
            if wall:
                raise LoginRequired(wall)
        elif action == "read_screen":
            captured = {"count_text": None, "total_text": None}
            if hasattr(session, "read_screen"):
                captured = session.read_screen(
                    step.get("count_selectors") or [],
                    step.get("total_selectors") or [],
                ) or captured
            manifest["screen"] = {
                "count_text": captured.get("count_text"),
                "total_text": captured.get("total_text"),
            }
        elif action == "download":
            if mode != "download":
                continue
            filename = str(report.get("filename") or "{id}-{date}.xlsx").format(
                id=report.get("id") or "report",
                date=business_date,
            )
            dest = out_dir / filename
            session.download(step.get("selectors") or [], dest)
            digest = sha256_file(dest)
            screen = manifest.get("screen") or {}
            return {
                "report": report.get("id"),
                "path": str(dest),
                "sha256": digest,
                "bytes": dest.stat().st_size,
                "screen_count_text": screen.get("count_text"),
                "screen_total_text": screen.get("total_text"),
            }
        else:
            raise ValueError(f"unknown step {action}")
    return None


def _write_manifest(out_dir: Path, manifest: dict) -> None:
    write_json(out_dir / "manifest.json", manifest)


def exit_code(manifest: dict) -> int:
    status = manifest.get("status")
    if status == "LOGIN_REQUIRED":
        return EXIT_LOGIN
    if status in {"OK", "INSPECTED"}:
        return EXIT_OK
    return EXIT_FAILED


def manifest_text(manifest: dict) -> str:
    return json.dumps(
        {
            "status": manifest.get("status"),
            "reason": manifest.get("reason"),
            "files": [
                {"report": item.get("report"), "sha256": item.get("sha256"), "bytes": item.get("bytes")}
                for item in manifest.get("files") or []
            ],
        },
        sort_keys=True,
    )
