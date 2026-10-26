"""Login-wall detection and the Membr download walker. No live browser."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from feina_client.browser import tabs_we_may_close
from feina_client.download import (
    EXIT_FAILED,
    EXIT_LOGIN,
    EXIT_OK,
    assert_allowed_url,
    assert_club_url,
    assert_safe_click,
    assert_safe_fill,
    exact_hostname,
    exit_code,
    parse_row_count,
    run_download,
)
from feina_client.login_page import detect_login_wall, structure_from_html
from feina_client.runtime import load_yaml
from feina_client.xlsxio import count_data_rows, write_xlsx


CLUB = "https://club.membr.com"
INSIGHTS = "https://insights.eu.membr.com/home"
ROOT = Path(__file__).resolve().parents[1]
GYM = "Anytime Fitness Sant Adrià"


class FakeSession:
    def __init__(
        self,
        pages: list[tuple[str, str]],
        download_book: dict | None = None,
        *,
        insights_pages: list[tuple[str, str]] | None = None,
        raw_bytes: bytes | None = None,
    ):
        self.pages = pages
        self.index = 0
        self.clicks: list[str] = []
        self.click_meta: list[dict] = []
        self.fills: list[tuple[str, str]] = []
        self.downloads: list[list[str]] = []
        self.two_steps: list[bool] = []
        self.gotos: list[str] = []
        self.download_book = download_book
        self.raw_bytes = raw_bytes
        self.closed = False
        self.closed_tabs: list = []
        self.screen_reads: list[tuple[list[str], list[str]]] = []
        self.count_text = None
        self.total_text = None
        self.insights_pages = insights_pages or []
        self.waits: list[str] = []
        self.waited_selectors: list[str] = []
        self.selected: list[str] = []
        self.gym_calls: list[dict] = []
        self.gym_fail = False
        self.harlands = object()
        self.preexisting = [self.harlands]
        self.owned: list = [object()]

    def goto(self, url: str) -> None:
        self.gotos.append(url)

    def url(self) -> str:
        return self.pages[self.index][0]

    def content(self) -> str:
        return self.pages[self.index][1]

    def wait_for_view(self) -> None:
        self.waits.append(self.url())

    def wait_for_selector(self, selector: str) -> None:
        self.waited_selectors.append(selector)

    def snapshot(self) -> dict:
        return structure_from_html(self.url(), self.content())

    def has_text(self, label: str, exact: bool = False) -> bool:
        if exact:
            return any((el.get("text") or "") == label for el in self.snapshot()["elements"])
        return label in self.content()

    def click_text(
        self,
        label: str,
        *,
        exact: bool = False,
        submenu: bool = False,
        opens_tab: bool = False,
        parent_selector: str = "",
        child_selector: str = "",
    ) -> None:
        present = self.has_text(label, exact=False if submenu else exact)
        if not present:
            raise LookupError(label)
        meta = {
            "label": label,
            "exact": exact,
            "submenu": submenu,
            "opens_tab": opens_tab or submenu,
            "parent_selector": parent_selector,
            "child_selector": child_selector,
        }
        self.click_meta.append(meta)
        self.clicks.append(label)
        if submenu:
            self.clicks.append(label)
            self.click_meta.append({**meta, "child": True})
            self._open_tab()
            return
        if opens_tab:
            self._open_tab()
            return
        if self.index + 1 < len(self.pages):
            self.index += 1

    def _open_tab(self) -> None:
        self.owned.append(object())
        if self.insights_pages:
            self.pages = list(self.insights_pages)
            self.index = 0

    def fill(self, selector: str, value: str) -> None:
        self.fills.append((selector, value))

    def ensure_only_gym(self, name: str, *, label: str = "Select Gyms") -> dict:
        self.gym_calls.append({"label": label, "gym": name})
        if self.gym_fail:
            return {"verified": False, "selected": list(self.selected)}
        self.selected = [name]
        return {"verified": True, "selected": [name]}

    def selected_gyms(self) -> list[str]:
        return list(self.selected)

    def read_screen(self, count_selectors: list[str], total_selectors: list[str]) -> dict:
        self.screen_reads.append((list(count_selectors), list(total_selectors)))
        count = self.count_text
        if count is None:
            match = re.search(r"<b>\s*(\d+)\s*</b>\s*total rows", self.content(), re.IGNORECASE)
            count = match.group(1) if match else None
        return {"count_text": count, "total_text": self.total_text}

    def download(self, selectors: list[str], dest: Path, *, two_step: bool = False) -> None:
        self.downloads.append(list(selectors))
        self.two_steps.append(two_step)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self.raw_bytes is not None:
            dest.write_bytes(self.raw_bytes)
            return
        if self.download_book is None:
            dest.write_bytes(b"not-a-workbook")
            return
        write_xlsx(dest, self.download_book)

    def close(self) -> None:
        self.closed = True
        self.closed_tabs = tabs_we_may_close(self.owned, self.preexisting)


class LateSession(FakeSession):
    """Page body stays empty until the walker waits for it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.revealed = False

    def wait_for_view(self) -> None:
        super().wait_for_view()
        self.revealed = True

    def content(self) -> str:
        if not self.revealed:
            return "<html><head><title></title></head><body></body></html>"
        return super().content()


def _html(fixtures: Path, name: str) -> str:
    return (fixtures / name).read_text(encoding="utf-8")


def _cfg(steps: list[dict], **extra) -> dict:
    cfg = {
        "club_base_url": CLUB,
        "pos_report_id": "pos_transactions",
        "reports": [
            {
                "id": "pos_transactions",
                "enabled": True,
                "required": True,
                "filename": "membr-pos-{date}.xlsx",
                "steps": steps,
            }
        ],
    }
    cfg.update(extra)
    return cfg


def test_login_fixture_is_a_wall_and_drops_password_values(fixtures: Path):
    html = _html(fixtures, "login.html")
    url = f"{CLUB}/login"
    assert detect_login_wall(url, html) == "login"
    recorded = structure_from_html(url, html)
    blob = json.dumps(recorded)
    assert "should-not-appear" not in blob
    assert recorded["login_wall"] == "login"
    assert recorded["title"].startswith("Membr")


def test_captcha_fixture_stops_before_any_click(fixtures: Path, tmp_path: Path):
    html = _html(fixtures, "captcha.html")
    session = FakeSession([(f"{CLUB}/dashboard", html)])
    manifest = run_download(
        _cfg([{"action": "click_text", "texts": ["Reports"]}]),
        business_date="2026-10-25",
        out_dir=tmp_path,
        session=session,
        mode="download",
    )
    assert manifest["status"] == "LOGIN_REQUIRED"
    assert manifest["reason"] == "captcha"
    assert session.clicks == []
    assert session.fills == []
    assert session.downloads == []
    assert exit_code(manifest) == EXIT_LOGIN
    assert (tmp_path / "manifest.json").is_file()


def test_login_page_stops_and_does_not_type(fixtures: Path, tmp_path: Path):
    html = _html(fixtures, "login.html")
    session = FakeSession([(f"{CLUB}/login", html)])
    manifest = run_download(
        _cfg(
            [
                {"action": "fill_date", "selector": "input[name='dateFrom']"},
                {"action": "click_text", "texts": ["Log in"]},
            ]
        ),
        business_date="2026-10-25",
        out_dir=tmp_path,
        session=session,
    )
    assert manifest["status"] == "LOGIN_REQUIRED"
    assert manifest["reason"] == "login"
    assert session.fills == []
    assert session.clicks == []


def test_signed_in_page_is_not_a_wall(fixtures: Path):
    html = _html(fixtures, "reports.html")
    assert detect_login_wall(f"{CLUB}/reports", html) is None


def test_download_clicks_dates_and_saves_hash(fixtures: Path, tmp_path: Path):
    html = _html(fixtures, "reports.html")
    book = {"Sheet1": [["Fecha", "Importe"], ["2026-10-25", "10.00"]]}
    session = FakeSession([(f"{CLUB}/reports", html)], download_book=book)
    manifest = run_download(
        _cfg(
            [
                {"action": "click_text", "texts": ["Reports", "Informes"]},
                {"action": "fill_date", "selector": "input[name='dateFrom']"},
                {"action": "fill_date", "selector": "input[name='dateTo']"},
                {"action": "download", "selectors": ["text=Download", "text=Excel"]},
            ]
        ),
        business_date="2026-10-25",
        out_dir=tmp_path,
        session=session,
        mode="download",
    )
    assert manifest["status"] == "OK"
    assert session.clicks == ["Reports"]
    assert session.fills == [
        ("input[name='dateFrom']", "2026-10-25"),
        ("input[name='dateTo']", "2026-10-25"),
    ]
    saved = tmp_path / "membr-pos-2026-10-25.xlsx"
    assert saved.is_file()
    assert manifest["files"][0]["sha256"]
    assert manifest["files"][0]["report"] == "pos_transactions"
    assert len(manifest["files"][0]["sha256"]) == 64


def test_download_stores_the_on_screen_count_and_total_without_editing_them(fixtures: Path, tmp_path: Path):
    html = _html(fixtures, "reports.html")
    book = {"Sheet1": [["Fecha", "Importe"], ["2026-10-25", "10.00"]]}
    session = FakeSession([(f"{CLUB}/reports", html)], download_book=book)
    session.count_text = "Rows: 1"
    session.total_text = "Total 10,00 €"
    manifest = run_download(
        _cfg(
            [
                {"action": "click_text", "texts": ["Reports"]},
                {
                    "action": "read_screen",
                    "count_selectors": [".report-row-count", "input[type='password']"],
                    "total_selectors": [".report-total"],
                },
                {"action": "download", "selectors": ["text=Download"]},
            ]
        ),
        business_date="2026-10-25",
        out_dir=tmp_path,
        session=session,
        mode="download",
    )
    assert manifest["status"] == "OK"
    assert session.screen_reads == [([".report-row-count", "input[type='password']"], [".report-total"])]
    assert session.fills == []
    saved = manifest["files"][0]
    assert saved["screen_count_text"] == "Rows: 1"
    assert saved["screen_total_text"] == "Total 10,00 €"
    from feina_client.browser import assert_safe_selector

    assert assert_safe_selector("input[type='password']") is False
    assert assert_safe_selector(".report-total") is True


def test_inspect_records_structure_and_does_not_download(fixtures: Path, tmp_path: Path):
    html = _html(fixtures, "reports.html")
    session = FakeSession([(f"{CLUB}/reports", html), (f"{CLUB}/reports", html)])
    manifest = run_download(
        _cfg(
            [
                {"action": "click_text", "texts": ["Reports"]},
                {"action": "fill_date", "selector": "input[name='dateFrom']"},
                {"action": "download", "selectors": ["text=Download"]},
            ]
        ),
        business_date="2026-10-25",
        out_dir=tmp_path,
        session=session,
        mode="inspect",
    )
    assert manifest["status"] == "INSPECTED"
    assert session.fills == []
    assert session.downloads == []
    assert manifest["files"] == []
    assert manifest["pages"][0]["elements"]


def test_dry_run_stays_on_the_landing_page(fixtures: Path, tmp_path: Path):
    html = _html(fixtures, "reports.html")
    session = FakeSession([(f"{CLUB}/reports", html)])
    manifest = run_download(
        _cfg([{"action": "click_text", "texts": ["Reports"]}]),
        business_date="2026-10-25",
        out_dir=tmp_path,
        session=session,
        mode="dry-run",
    )
    assert manifest["status"] == "INSPECTED"
    assert session.clicks == []
    assert session.gotos == [CLUB]


def test_refuses_password_fields_login_clicks_and_other_hosts():
    with pytest.raises(PermissionError):
        assert_safe_fill("input[type=password]", "2026-10-25")
    with pytest.raises(PermissionError):
        assert_safe_fill("input[name='dateFrom']", "yesterday")
    with pytest.raises(PermissionError):
        assert_safe_click("Log in")
    with pytest.raises(PermissionError):
        assert_safe_click("I'm not a robot")
    with pytest.raises(PermissionError):
        assert_club_url("https://evil.example/export", CLUB)
    with pytest.raises(PermissionError):
        assert_club_url("http://club.membr.com/reports", CLUB)
    with pytest.raises(PermissionError):
        assert_club_url(f"{CLUB}/reports?token=abc", CLUB)


def test_login_mid_walk_does_not_download(fixtures: Path, tmp_path: Path):
    reports = _html(fixtures, "reports.html")
    login = _html(fixtures, "login.html")
    session = FakeSession(
        [
            (f"{CLUB}/reports", reports),
            (f"{CLUB}/login", login),
        ]
    )
    manifest = run_download(
        _cfg(
            [
                {"action": "click_text", "texts": ["Reports"]},
                {"action": "download", "selectors": ["text=Download"]},
            ]
        ),
        business_date="2026-10-25",
        out_dir=tmp_path,
        session=session,
    )
    assert manifest["status"] == "LOGIN_REQUIRED"
    assert session.downloads == []


def _live_cfg() -> dict:
    cfg = load_yaml(ROOT / "files/skills/client-drop/membr-download/membr.reports.yaml")
    cfg["club_base_url"] = CLUB
    return cfg


def _live_session(fixtures: Path, name: str, *, raw: bytes | None = None, late: bool = False, gym_fail: bool = False):
    club = (f"{CLUB}/admin/dashboard", _html(fixtures, "club-admin.html"))
    insights = (INSIGHTS, _html(fixtures, name))
    cls = LateSession if late else FakeSession
    session = cls([club], insights_pages=[insights], raw_bytes=raw)
    session.selected = ["Other Gym", GYM]
    session.gym_fail = gym_fail
    return session


def _workbook_bytes(path: Path, data_rows: int) -> bytes:
    rows = [["Col"]] + [["x"] for _ in range(data_rows)]
    write_xlsx(
        path,
        {
            "Report": rows,
            "Report Meta Data": [["Report Name"], ["POS Transaction"]],
        },
    )
    return path.read_bytes()


def test_live_config_names_the_gym_host_and_xlsx_menu():
    path = ROOT / "files/skills/client-drop/membr-download/membr.reports.yaml"
    cfg = load_yaml(path)
    text = path.read_text(encoding="utf-8")
    assert cfg["gym_name"] == GYM
    assert cfg["allowed_hosts"] == ["insights.eu.membr.com"]
    assert cfg["browser"]["cookie_names"] == []
    for banned in ("PHPSESSID", "membr_session", "MEMBRSESSID"):
        assert banned not in text
    steps = next(item["steps"] for item in cfg["reports"] if item["id"] == "pos_transactions")
    informes = steps[0]
    assert informes["submenu"] is True and informes["opens_tab"] is True
    assert informes["parent_selector"] == "a.Aside-menu-link.has-subMenu"
    assert informes["child_selector"] == "a.Aside-submenu-link"
    pos = next(step for step in steps if step.get("texts") == ["POS Transactions"])
    assert pos["exact"] is True
    gym = next(step for step in steps if step["action"] == "ensure_gym")
    run = next(step for step in steps if step.get("texts") == ["Run Report"])
    assert steps.index(gym) < steps.index(run)
    assert gym["gym"] == GYM
    download = next(step for step in steps if step["action"] == "download")
    assert download["two_step"] is True
    assert download["selectors"] == ["text='Download Report'", "text='Download Report (.xlsx)'"]
    assert [step["selector"] for step in steps if step["action"] == "fill_date"] == [
        "input[name='from']",
        "input[name='until']",
    ]


def test_row_count_parser_accepts_only_the_on_screen_total():
    assert parse_row_count("4") == 4
    assert parse_row_count("0") == 0
    assert parse_row_count("4 total rows") == 4
    assert parse_row_count("Rows: 1") is None
    assert parse_row_count(None) is None


def test_allow_list_is_exact_hosts_and_rejects_other_sites():
    allowed = {"club.membr.com", "insights.eu.membr.com"}
    assert_allowed_url("https://insights.eu.membr.com/home", allowed)
    assert_club_url("https://insights.eu.membr.com/home", CLUB, allowed_hosts=allowed)
    with pytest.raises(PermissionError):
        assert_club_url("https://insights.eu.membr.com/home", CLUB)
    with pytest.raises(PermissionError):
        assert_allowed_url("https://secure.harlands-ddms.co.uk/ddms2/home/", allowed)
    with pytest.raises(PermissionError):
        assert_allowed_url("https://insights.eu.membr.com/home?token=abc", allowed)
    with pytest.raises(PermissionError):
        assert_allowed_url("https://insights.eu.membr.com/home#token=abc", allowed)
    with pytest.raises(PermissionError):
        exact_hostname("*.membr.com")
    with pytest.raises(PermissionError):
        exact_hostname("https://user:secret@insights.eu.membr.com")


def test_preexisting_tabs_are_not_ours_to_close():
    harlands = object()
    ours = object()
    insights = object()
    assert tabs_we_may_close([ours, insights, harlands], [harlands]) == [ours, insights]


def test_click_on_the_club_host_does_not_use_an_insights_label(tmp_path: Path):
    session = FakeSession([(f"{CLUB}/admin/dashboard", "<a>My Reports</a>")])
    manifest = run_download(
        _cfg(
            [{"action": "click_text", "texts": ["My Reports"], "host": "insights"}],
            allowed_hosts=["insights.eu.membr.com"],
        ),
        business_date="2026-10-25",
        out_dir=tmp_path,
        session=session,
    )
    assert manifest["status"] == "FAILED"
    assert manifest["reason"] == "PermissionError"
    assert session.clicks == []
    assert session.gotos == [CLUB]


def test_wall_check_waits_before_deciding_the_page_is_signed_in(fixtures: Path, tmp_path: Path):
    session = LateSession([(f"{CLUB}/admin/dashboard", _html(fixtures, "login.html"))])
    manifest = run_download(
        _cfg([{"action": "click_text", "texts": ["Reports"]}]),
        business_date="2026-10-25",
        out_dir=tmp_path,
        session=session,
    )
    assert manifest["status"] == "LOGIN_REQUIRED"
    assert manifest["reason"] == "login"
    assert session.clicks == []
    assert session.waits


def test_insights_new_tab_flow_saves_membr_bytes_and_matches_rows(fixtures: Path, tmp_path: Path):
    raw = _workbook_bytes(tmp_path / "source.xlsx", 4)
    session = _live_session(fixtures, "insights-pos.html", raw=raw)
    manifest = run_download(
        _live_cfg(),
        business_date="2026-10-25",
        out_dir=tmp_path / "run",
        session=session,
    )
    session.close()
    assert manifest["status"] == "OK"
    assert manifest["date_filter_timezone"] == "unverified"
    assert "TODO" in manifest["date_filter_timezone_todo"]
    assert "UTC" in manifest["date_filter_timezone_todo"]
    assert manifest["date_filter_timezone"] not in {"UTC", "local", "Europe/Madrid"}
    assert session.gotos == [CLUB]
    assert session.url() == INSIGHTS
    assert session.harlands not in session.closed_tabs
    assert session.harlands not in session.owned
    assert set(session.closed_tabs) == set(session.owned)
    assert session.clicks.count("Informes") == 2
    assert session.click_meta[0]["submenu"] is True
    assert session.click_meta[0]["parent_selector"] == "a.Aside-menu-link.has-subMenu"
    assert session.click_meta[0]["child_selector"] == "a.Aside-submenu-link"
    assert "Cash Register" not in session.clicks
    assert "Past Transactions" not in session.clicks
    assert any(item["label"] == "POS Transactions" and item["exact"] is True for item in session.click_meta)
    assert session.fills == [
        ("input[name='from']", "2026-10-25"),
        ("input[name='until']", "2026-10-25"),
    ]
    assert session.gym_calls == [{"label": "Select Gyms", "gym": GYM}]
    assert session.selected == [GYM]
    assert manifest["gym"]["verified"] is True
    assert session.downloads == [["text='Download Report'", "text='Download Report (.xlsx)'"]]
    assert session.two_steps == [True]
    assert all(".csv" not in item and ".json" not in item for item in session.downloads[0])
    saved_path = tmp_path / "run" / "pos-export.xlsx"
    assert saved_path.read_bytes() == raw
    saved = manifest["files"][0]
    assert saved["sha256"] == hashlib.sha256(raw).hexdigest()
    assert saved["screen_count_text"] == "4"
    assert saved["screen_row_count"] == 4
    assert saved["file_row_count"] == 4
    assert saved["screen_total_text"] is None
    assert count_data_rows(saved_path, "Report") == 4
    assert count_data_rows(saved_path, "Report Meta Data") == 1
    assert exit_code(manifest) == EXIT_OK


def test_gym_filter_stops_when_another_gym_stays_selected(fixtures: Path, tmp_path: Path):
    session = _live_session(fixtures, "insights-pos.html", gym_fail=True)
    manifest = run_download(
        _live_cfg(),
        business_date="2026-10-25",
        out_dir=tmp_path,
        session=session,
    )
    assert manifest["status"] == "GYM_FILTER_UNVERIFIED"
    assert manifest["gym"]["verified"] is False
    assert manifest["gym"]["selected"] == ["Other Gym", GYM]
    assert "Run Report" not in session.clicks
    assert session.downloads == []
    assert manifest["files"] == []
    assert exit_code(manifest) == EXIT_FAILED


def test_row_count_mismatch_stops_after_the_download(fixtures: Path, tmp_path: Path):
    raw = _workbook_bytes(tmp_path / "source.xlsx", 1)
    session = _live_session(fixtures, "insights-pos.html", raw=raw)
    manifest = run_download(
        _live_cfg(),
        business_date="2026-10-25",
        out_dir=tmp_path / "run",
        session=session,
    )
    assert manifest["status"] == "SCREEN_MISMATCH"
    assert manifest["files"][0]["screen_row_count"] == 4
    assert manifest["files"][0]["file_row_count"] == 1
    assert (tmp_path / "run" / "pos-export.xlsx").read_bytes() == raw
    assert exit_code(manifest) == EXIT_FAILED


def test_empty_day_is_not_a_success(fixtures: Path, tmp_path: Path):
    raw = _workbook_bytes(tmp_path / "source.xlsx", 0)
    session = _live_session(fixtures, "insights-empty.html", raw=raw)
    manifest = run_download(
        _live_cfg(),
        business_date="2026-10-25",
        out_dir=tmp_path / "run",
        session=session,
    )
    assert manifest["status"] == "EMPTY_DAY_NEEDS_CONFIRMATION"
    assert manifest["status"] != "OK"
    assert manifest["files"][0]["screen_row_count"] == 0
    assert manifest["files"][0]["file_row_count"] == 0
    assert exit_code(manifest) == EXIT_FAILED


def test_insights_error_beside_zero_rows_is_not_an_empty_day(fixtures: Path, tmp_path: Path):
    session = _live_session(fixtures, "insights-error.html")
    manifest = run_download(
        _live_cfg(),
        business_date="2026-10-25",
        out_dir=tmp_path,
        session=session,
    )
    assert manifest["status"] == "FAILED"
    assert manifest["reason"] == "insights_error"
    assert manifest["status"] != "EMPTY_DAY_NEEDS_CONFIRMATION"
    assert session.downloads == []
    assert exit_code(manifest) == EXIT_FAILED


def test_inspect_waits_and_records_menus_inputs_and_buttons(fixtures: Path, tmp_path: Path):
    session = _live_session(fixtures, "insights-pos.html", late=True)
    manifest = run_download(
        _live_cfg(),
        business_date="2026-10-25",
        out_dir=tmp_path,
        session=session,
        mode="inspect",
    )
    assert manifest["status"] == "INSPECTED"
    assert session.fills == []
    assert session.downloads == []
    assert session.waits
    assert "Informes" in manifest["pages"][0]["menus"]
    assert manifest["pages"][0]["elements"]
    assert any(item.get("name") == "from" for page in manifest["pages"] for item in page.get("inputs") or [])
    assert any(item.get("name") == "until" for page in manifest["pages"] for item in page.get("inputs") or [])
    buttons = [label for page in manifest["pages"] for label in page.get("buttons") or []]
    assert "POS Transactions" in buttons
    assert "Cash Register" in buttons
    assert "Past Transactions" in buttons
    assert "Run Report" in buttons
    assert "Download Report" in buttons
    assert "input[name='from']" in session.waited_selectors
    assert "input[name='until']" in session.waited_selectors
    assert manifest["gym"]["changed"] is False
    assert manifest["gym"]["selected"] == ["Other Gym", GYM]
    assert manifest["date_filter_timezone"] == "unverified"
    assert exit_code(manifest) == EXIT_OK
