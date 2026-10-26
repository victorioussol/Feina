"""Attach Playwright to the agent's existing browser profile.

Prefer the Chrome DevTools port the agent already has open. If that port is
down, launch Chromium on the same user-data directory. Never create a fresh
empty profile, and never close a browser we only attached to.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .download import NoProfile, assert_club_url, assert_safe_click, assert_safe_fill
from .login_page import structure_from_html


class PlaywrightSession:
    def __init__(self, playwright, browser, context, page, *, attached: bool):
        self._playwright = playwright
        self._browser = browser
        self._context = context
        self._page = page
        self._attached = attached

    def goto(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)

    def url(self) -> str:
        return self._page.url

    def content(self) -> str:
        return self._page.content()

    def has_text(self, label: str) -> bool:
        assert_safe_click(label)
        return self._page.get_by_text(label, exact=False).count() > 0

    def click_text(self, label: str) -> None:
        assert_safe_click(label)
        self._page.get_by_text(label, exact=False).first.click(timeout=10_000)

    def fill(self, selector: str, value: str) -> None:
        assert_safe_fill(selector, value)
        self._page.fill(selector, value, timeout=10_000)

    def download(self, selectors: list[str], dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        last = "download control not found"
        for selector in selectors:
            if assert_safe_selector(selector) is False:
                continue
            locator = self._page.locator(selector)
            if locator.count() == 0:
                continue
            with self._page.expect_download(timeout=120_000) as info:
                locator.first.click()
            info.value.save_as(str(dest))
            return
        raise LookupError(last)

    def snapshot(self) -> dict:
        try:
            raw = self._page.evaluate(_SNAPSHOT_JS)
            raw["login_wall"] = None
            return raw
        except Exception:
            return structure_from_html(self.url(), self.content())

    def cookies(self) -> list[dict]:
        """Names, hosts and expiries only. Values are dropped here."""
        rows = []
        for cookie in self._context.cookies():
            raw = cookie.get("expires") or 0
            when = datetime.fromtimestamp(raw, tz=timezone.utc) if raw and raw > 0 else None
            rows.append(
                {
                    "host": cookie.get("domain") or "",
                    "name": cookie.get("name") or "",
                    "expires_at": when,
                }
            )
        return rows

    def close(self) -> None:
        if self._attached:
            # Disconnect only. browser.close() on a CDP session closes the window.
            self._playwright.stop()
            return
        try:
            self._context.close()
        finally:
            self._playwright.stop()


def assert_safe_selector(selector: str) -> bool:
    lowered = (selector or "").lower()
    if "password" in lowered or "captcha" in lowered:
        return False
    return True


def open_session(cfg: dict) -> PlaywrightSession:
    from playwright.sync_api import sync_playwright

    browser_cfg = cfg.get("browser") or {}
    club = str(cfg["club_base_url"])
    assert_club_url(club, club)
    playwright = sync_playwright().start()
    cdp = browser_cfg.get("cdp_url") or "http://127.0.0.1:9222"
    try:
        browser = playwright.chromium.connect_over_cdp(cdp, timeout=5_000)
        context = browser.contexts[0] if browser.contexts else browser.new_context(accept_downloads=True)
        page = context.pages[0] if context.pages else context.new_page()
        return PlaywrightSession(playwright, browser, context, page, attached=True)
    except Exception as exc:
        cdp_error = exc
    profile = Path(str(browser_cfg.get("user_data_dir") or "")).expanduser()
    if not profile.is_dir():
        playwright.stop()
        raise NoProfile(str(cdp_error.__class__.__name__))
    context = playwright.chromium.launch_persistent_context(
        str(profile),
        headless=True,
        accept_downloads=True,
    )
    page = context.pages[0] if context.pages else context.new_page()
    return PlaywrightSession(playwright, None, context, page, attached=False)


_SNAPSHOT_JS = """
() => {
  const take = (sel) => Array.from(document.querySelectorAll(sel)).slice(0, 200).map((el) => ({
    tag: el.tagName.toLowerCase(),
    id: el.id || "",
    name: el.getAttribute("name") || "",
    type: (el.getAttribute("type") || "").toLowerCase() === "password" ? "password" : (el.getAttribute("type") || ""),
    href: el.tagName === "A" ? (el.getAttribute("href") || "") : "",
    aria: el.getAttribute("aria-label") || "",
    placeholder: el.getAttribute("placeholder") || "",
    role: el.getAttribute("role") || "",
    text: (el.innerText || "").replace(/\\s+/g, " ").trim().slice(0, 120)
  }));
  return {
    url: location.href,
    title: document.title || "",
    elements: take("a, button, input, select, textarea, h1, h2, h3, label")
  };
}
"""
