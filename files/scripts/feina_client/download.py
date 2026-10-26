"""Download Membr reports by clicking the club's own screens.

The script attaches to the browser profile that is already logged in. It opens
one new tab on the club home page, follows the Insights tab that the Informes
submenu opens, and closes only those tabs. It never types a password, never
fills anything except a date, and never calls a host outside the allow-list.
If the page is a login or a captcha, it stops. The POS file is saved as
pos-export.xlsx. The bytes are Membr's own download; this script does not
rebuild the workbook.

The vendored afsa_checks.py export check still requires the Spanish sheet names
Informe and Informe Meta Data and the report name Transaccion Punto de Venta.
A live Insights export uses Report, Report Meta Data, and POS Transaction.
That checker is not modified here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .login_page import annotate_structure, detect_login_wall, structure_from_html
from .runtime import sha256_file, write_json
from .xlsxio import count_data_rows

EXIT_OK = 0
EXIT_FAILED = 2
EXIT_LOGIN = 10

INSIGHTS_ERROR = "Oops, an error has occurred"
DATE_FILTER_TIMEZONE = "unverified"
DATE_FILTER_TIMEZONE_TODO = (
    "TODO: confirm whether the From/Until filter uses UTC or the club local timezone. "
    "The export download-time metadata is UTC. This field stays unverified until that check exists."
)
REPORT_SHEET = "Report"

_BANNED_FILL = re.compile(r"password|passwd|captcha|otp|secret|token", re.IGNORECASE)
_BANNED_CLICK = re.compile(
    r"^(log ?in|sign ?in|iniciar sesi[oó]n|connexion|acceder|captcha|i.?m not a robot|no soy un robot)$",
    re.IGNORECASE,
)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SECRET_QUERY = re.compile(r"token|password|key=", re.IGNORECASE)


class LoginRequired(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class RunHalt(Exception):
    """A download outcome that must not be reported as success."""

    def __init__(self, status: str, *, reason: str | None = None, saved: dict | None = None):
        super().__init__(status)
        self.status = status
        self.reason = reason
        self.saved = saved


class NoProfile(Exception):
    pass


def allowed_hostnames(cfg: dict) -> set[str]:
    """Club host plus the explicit allow-list. No wildcards and no other hosts."""
    hosts: set[str] = set()
    club_host = (urlparse(str(cfg.get("club_base_url") or "")).hostname or "").lower()
    if club_host:
        hosts.add(club_host)
    for item in cfg.get("allowed_hosts") or []:
        hosts.add(exact_hostname(str(item)))
    return hosts


def exact_hostname(text: str) -> str:
    raw = (text or "").strip().lower()
    if not raw or "*" in raw or "@" in raw or raw.startswith("."):
        raise PermissionError("allow-list entries are exact hosts")
    if "://" in raw and not raw.startswith("https://"):
        raise PermissionError("allow-list entries are https hosts")
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise PermissionError("allow-list entries are exact hosts")
    return host


def assert_allowed_url(url: str, allowed: set[str]) -> None:
    target = urlparse(url or "")
    host = (target.hostname or "").lower()
    if target.scheme != "https" or not host:
        raise PermissionError("only https on an allowed host")
    if host not in {item.lower() for item in allowed}:
        raise PermissionError("refusing to leave the allowed hosts")
    if target.query and _SECRET_QUERY.search(target.query):
        raise PermissionError("refusing a url that carries a secret")
    if target.fragment and _SECRET_QUERY.search(target.fragment):
        raise PermissionError("refusing a url that carries a secret")


def assert_club_url(url: str, club_base: str, allowed_hosts: set[str] | None = None) -> None:
    hosts = set(allowed_hosts or set())
    base = (urlparse(club_base).hostname or "").lower()
    if base:
        hosts.add(base)
    assert_allowed_url(url, hosts)


def assert_safe_fill(selector: str, value: str) -> None:
    if _BANNED_FILL.search(selector or ""):
        raise PermissionError("refusing to type into a credential or captcha field")
    if not _DATE.match(value or ""):
        raise PermissionError("only a YYYY-MM-DD date may be typed")


def assert_safe_click(label: str) -> None:
    if _BANNED_CLICK.match((label or "").strip()):
        raise PermissionError("refusing to click a login or captcha control")


def parse_row_count(text: str | None) -> int | None:
    """N from a bold row-count, or from the whole 'N total rows' string."""
    if text is None:
        return None
    raw = " ".join(str(text).split())
    if re.fullmatch(r"\d+", raw):
        return int(raw)
    match = re.fullmatch(r"(\d+)\s+total rows", raw, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _hostname(url: str) -> str:
    return (urlparse(url or "").hostname or "").lower()


def _named_host(which: str, club: str, allowed: set[str]) -> str:
    label = (which or "").strip().lower()
    club_host = _hostname(club)
    if label == "club":
        if not club_host:
            raise PermissionError("club host missing")
        return club_host
    if label == "insights":
        matches = sorted(host for host in allowed if host != club_host and host.startswith("insights."))
        if len(matches) == 1:
            return matches[0]
        raise PermissionError("insights host is not in the allow-list")
    if label in allowed:
        return label
    raise PermissionError("step host is not allow-listed")


def _require_host(session, step: dict, club: str, allowed: set[str]) -> None:
    which = str(step.get("host") or "").strip()
    if not which:
        return
    expect = _named_host(which, club, allowed)
    if _hostname(session.url()) != expect:
        raise PermissionError("refusing to act on a different host")


def _wall(session, club_base: str, allowed: set[str]) -> str | None:
    if hasattr(session, "wait_for_view"):
        session.wait_for_view()
    url = session.url()
    assert_club_url(url, club_base, allowed_hosts=allowed)
    return detect_login_wall(url, session.content())


def _record(session, manifest: dict, *, after: str | None = None) -> None:
    if hasattr(session, "wait_for_view"):
        session.wait_for_view()
    if hasattr(session, "snapshot"):
        page = session.snapshot()
    else:
        page = structure_from_html(session.url(), session.content())
    page = annotate_structure(page)
    if after is not None:
        page["after"] = after
    manifest["pages"].append(page)


def _must_match_rows(report: dict) -> bool:
    for step in report.get("steps") or []:
        if step.get("action") != "read_screen":
            continue
        for selector in step.get("count_selectors") or []:
            if "total rows" in str(selector):
                return True
    return False


def run_download(
    cfg: dict,
    *,
    business_date: str,
    out_dir: Path,
    session,
    mode: str = "download",
) -> dict:
    """mode is 'download', 'inspect', or 'dry-run'.

    inspect walks the configured clicks, waits for the page, and records
    menus, inputs and buttons. dry-run records only the landing page.
    Both stop on a login wall and neither downloads.
    """
    if mode not in {"download", "inspect", "dry-run"}:
        raise ValueError(mode)
    club = str(cfg["club_base_url"])
    allowed = allowed_hostnames(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "business_date": business_date,
        "mode": mode,
        "status": "OK",
        "date_filter_timezone": DATE_FILTER_TIMEZONE,
        "date_filter_timezone_todo": DATE_FILTER_TIMEZONE_TODO,
        "files": [],
        "pages": [],
        "errors": [],
    }
    try:
        session.goto(club)
        if hasattr(session, "wait_for_view"):
            session.wait_for_view()
        wall = _wall(session, club, allowed)
        _record(session, manifest)
        if wall:
            raise LoginRequired(wall)
        if mode == "dry-run":
            manifest["status"] = "INSPECTED"
            return manifest
        for report in cfg.get("reports") or []:
            if report.get("enabled", True) is False:
                continue
            try:
                saved = _one_report(
                    session,
                    report,
                    club_base=club,
                    allowed=allowed,
                    gym_name=str(cfg.get("gym_name") or ""),
                    business_date=business_date,
                    out_dir=out_dir,
                    mode=mode,
                    manifest=manifest,
                )
            except LoginRequired:
                raise
            except RunHalt:
                raise
            except Exception as exc:
                manifest["errors"].append({"report": report.get("id"), "error": type(exc).__name__})
                if report.get("required", True) and mode == "download":
                    manifest["status"] = "FAILED"
                    manifest["reason"] = type(exc).__name__
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
    except RunHalt as exc:
        manifest["status"] = exc.status
        if exc.reason:
            manifest["reason"] = exc.reason
        if exc.saved:
            manifest["files"].append(exc.saved)
    except LoginRequired as exc:
        manifest["status"] = "LOGIN_REQUIRED"
        manifest["reason"] = exc.reason
    except Exception as exc:
        manifest["status"] = "FAILED"
        manifest["reason"] = type(exc).__name__
    finally:
        _write_manifest(out_dir, manifest)
    return manifest


def _one_report(
    session,
    report,
    *,
    club_base,
    allowed,
    gym_name,
    business_date,
    out_dir,
    mode,
    manifest,
) -> dict | None:
    for step in report.get("steps") or []:
        action = step.get("action")
        if action == "click_text":
            _require_host(session, step, club_base, allowed)
            chosen = _click_step(session, step)
            if chosen is None:
                if mode == "download":
                    raise LookupError(report.get("id") or "report")
                _record(session, manifest)
                continue
            if step.get("opens_tab") or step.get("submenu"):
                expect = _named_host("insights", club_base, allowed)
                if _hostname(session.url()) != expect:
                    raise PermissionError("refusing to follow a tab off the insights host")
            else:
                _require_host(session, step, club_base, allowed)
            wall = _wall(session, club_base, allowed)
            _record(session, manifest, after=chosen)
            if wall:
                raise LoginRequired(wall)
        elif action == "fill_date":
            _require_host(session, step, club_base, allowed)
            selector = step.get("selector") or ""
            if hasattr(session, "wait_for_selector"):
                session.wait_for_selector(selector)
            if mode != "download":
                _record(session, manifest)
                continue
            value = business_date
            assert_safe_fill(selector, value)
            session.fill(selector, value)
            wall = _wall(session, club_base, allowed)
            if wall:
                raise LoginRequired(wall)
        elif action == "ensure_gym":
            _ensure_gym(session, step, club_base, allowed, gym_name, mode, manifest)
        elif action == "read_screen":
            _require_host(session, step, club_base, allowed)
            captured = {"count_text": None, "total_text": None}
            if hasattr(session, "read_screen"):
                captured = session.read_screen(
                    step.get("count_selectors") or [],
                    step.get("total_selectors") or [],
                ) or captured
            row_count = parse_row_count(captured.get("count_text"))
            manifest["screen"] = {
                "count_text": captured.get("count_text"),
                "total_text": captured.get("total_text"),
                "row_count": row_count,
            }
            if mode == "download" and session.has_text(INSIGHTS_ERROR):
                raise RunHalt("FAILED", reason="insights_error")
        elif action == "download":
            _require_host(session, step, club_base, allowed)
            if mode != "download":
                continue
            return _save_download(
                session,
                report,
                step,
                business_date=business_date,
                out_dir=out_dir,
                manifest=manifest,
            )
        else:
            raise ValueError(f"unknown step {action}")
    return None


def _click_step(session, step: dict) -> str | None:
    exact = bool(step.get("exact"))
    opens_tab = bool(step.get("opens_tab") or step.get("submenu"))
    for label in step.get("texts") or []:
        assert_safe_click(label)
        try:
            session.click_text(
                label,
                exact=exact,
                submenu=bool(step.get("submenu")),
                opens_tab=opens_tab,
                parent_selector=step.get("parent_selector") or "",
                child_selector=step.get("child_selector") or "",
            )
        except LookupError:
            continue
        return label
    return None


def _ensure_gym(session, step, club_base, allowed, gym_name, mode, manifest) -> None:
    _require_host(session, step, club_base, allowed)
    configured = str(gym_name or "").strip()
    step_gym = str(step.get("gym") or configured).strip()
    label = ((step.get("texts") or ["Select Gyms"])[0] or "Select Gyms").strip()
    assert_safe_click(label)
    if configured:
        assert_safe_click(configured)
    if mode != "download":
        selected = list(session.selected_gyms()) if hasattr(session, "selected_gyms") else []
        manifest["gym"] = {
            "name": configured,
            "selected": selected,
            "verified": False,
            "changed": False,
        }
        _record(session, manifest)
        return
    if not configured or step_gym != configured:
        manifest["gym"] = {"name": configured, "selected": [], "verified": False}
        raise RunHalt("GYM_FILTER_UNVERIFIED", reason="gym_name")
    session.ensure_only_gym(configured, label=label)
    selected = [str(item).strip() for item in session.selected_gyms()]
    verified = selected == [configured]
    manifest["gym"] = {"name": configured, "selected": selected, "verified": verified}
    wall = _wall(session, club_base, allowed)
    if wall:
        raise LoginRequired(wall)
    if not verified:
        raise RunHalt("GYM_FILTER_UNVERIFIED")


def _save_download(session, report, step, *, business_date, out_dir, manifest) -> dict:
    filename = str(report.get("filename") or "{id}-{date}.xlsx").format(
        id=report.get("id") or "report",
        date=business_date,
    )
    dest = out_dir / filename
    session.download(step.get("selectors") or [], dest, two_step=bool(step.get("two_step")))
    digest = sha256_file(dest)
    screen = manifest.get("screen") or {}
    file_rows = count_data_rows(dest, REPORT_SHEET) if _must_match_rows(report) else None
    entry = {
        "report": report.get("id"),
        "path": str(dest),
        "sha256": digest,
        "bytes": dest.stat().st_size,
        "screen_count_text": screen.get("count_text"),
        "screen_total_text": screen.get("total_text"),
        "screen_row_count": screen.get("row_count"),
        "file_row_count": file_rows,
    }
    if _must_match_rows(report):
        screen_n = screen.get("row_count")
        if not isinstance(screen_n, int) or file_rows is None or screen_n != file_rows:
            raise RunHalt("SCREEN_MISMATCH", saved=entry)
        if screen_n == 0:
            if session.has_text(INSIGHTS_ERROR):
                raise RunHalt("FAILED", reason="insights_error", saved=entry)
            raise RunHalt("EMPTY_DAY_NEEDS_CONFIRMATION", saved=entry)
    return entry


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
            "date_filter_timezone": manifest.get("date_filter_timezone"),
            "files": [
                {
                    "report": item.get("report"),
                    "sha256": item.get("sha256"),
                    "bytes": item.get("bytes"),
                    "screen_row_count": item.get("screen_row_count"),
                    "file_row_count": item.get("file_row_count"),
                }
                for item in manifest.get("files") or []
            ],
        },
        sort_keys=True,
    )
