"""Login-wall detection and the Membr download walker. No live browser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from feina_client.download import (
    EXIT_LOGIN,
    assert_club_url,
    assert_safe_click,
    assert_safe_fill,
    exit_code,
    run_download,
)
from feina_client.login_page import detect_login_wall, structure_from_html
from feina_client.xlsxio import write_xlsx


CLUB = "https://club.membr.com"


class FakeSession:
    def __init__(self, pages: list[tuple[str, str]], download_book: dict | None = None):
        self.pages = pages
        self.index = 0
        self.clicks: list[str] = []
        self.fills: list[tuple[str, str]] = []
        self.downloads: list[list[str]] = []
        self.gotos: list[str] = []
        self.download_book = download_book
        self.closed = False

    def goto(self, url: str) -> None:
        self.gotos.append(url)

    def url(self) -> str:
        return self.pages[self.index][0]

    def content(self) -> str:
        return self.pages[self.index][1]

    def snapshot(self) -> dict:
        return structure_from_html(self.url(), self.content())

    def has_text(self, label: str) -> bool:
        return label in self.content()

    def click_text(self, label: str) -> None:
        self.clicks.append(label)
        if self.index + 1 < len(self.pages):
            self.index += 1

    def fill(self, selector: str, value: str) -> None:
        self.fills.append((selector, value))

    def download(self, selectors: list[str], dest: Path) -> None:
        self.downloads.append(list(selectors))
        if self.download_book is None:
            dest.write_bytes(b"not-a-workbook")
            return
        write_xlsx(dest, self.download_book)

    def close(self) -> None:
        self.closed = True


def _html(fixtures: Path, name: str) -> str:
    return (fixtures / name).read_text(encoding="utf-8")


def _cfg(steps: list[dict]) -> dict:
    return {
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
