"""Attach Playwright to the agent's existing browser profile.

Prefer the Chrome DevTools port the agent already has open. Open a new tab in
that browser. Follow a tab this run's click creates, and close only those
tabs. Never navigate or close a tab that was already open (Harlands, for
example). If that port is down, launch Chromium on the same user-data
directory. Never create a fresh empty profile, and never close a browser we
only attached to.

A supervised run of this flow finished in 26.8s. The timeouts below are caps.
A page that is already idle returns immediately.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from .download import (
    NoProfile,
    allowed_hostnames,
    assert_allowed_url,
    assert_safe_click,
    assert_safe_fill,
)
from .login_page import annotate_structure, structure_from_html

# Caps, not sleeps on the success path. Ten actions stayed under a minute live.
_NAV_TIMEOUT_MS = 20_000
_IDLE_TIMEOUT_MS = 3_000
_CONTROL_TIMEOUT_MS = 8_000
_DOWNLOAD_TIMEOUT_MS = 30_000
_POPUP_TIMEOUT_MS = 10_000


def tabs_we_may_close(owned: list, preexisting: list) -> list:
    """Tabs this run opened. Tabs that were already open stay open."""
    blocked = {id(page) for page in preexisting}
    return [page for page in owned if id(page) not in blocked]


class PlaywrightSession:
    def __init__(
        self,
        playwright,
        browser,
        context,
        page,
        *,
        attached: bool,
        allowed: set[str],
        club: str,
        preexisting: list,
        owned: list,
    ):
        self._playwright = playwright
        self._browser = browser
        self._context = context
        self._page = page
        self._attached = attached
        self._allowed = allowed
        self._club = club
        self._preexisting = list(preexisting)
        self._owned = list(owned)

    def goto(self, url: str) -> None:
        assert_allowed_url(url, self._allowed)
        self._page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        self._wait_settled()
        self.wait_for_view()
        assert_allowed_url(self.url(), self._allowed)

    def url(self) -> str:
        return self._page.url

    def content(self) -> str:
        return self._page.content()

    def wait_for_view(self) -> None:
        self._wait_for_visible_controls()

    def wait_for_selector(self, selector: str) -> None:
        if not selector or assert_safe_selector(selector) is False:
            return
        self._page.locator(selector).first.wait_for(state="visible", timeout=_CONTROL_TIMEOUT_MS)

    def has_text(self, label: str, exact: bool = False) -> bool:
        assert_safe_click(label)
        try:
            return self._page.get_by_text(label, exact=exact).count() > 0
        except Exception:
            return False

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
        assert_safe_click(label)
        try:
            if submenu:
                self._click_submenu(label, parent_selector, child_selector)
                return
            locator = self._page.get_by_text(label, exact=exact)
            locator.first.wait_for(state="visible", timeout=_CONTROL_TIMEOUT_MS)
            self._click_maybe_new_tab(locator.first, opens_tab=opens_tab)
        except PermissionError:
            raise
        except LookupError:
            raise
        except Exception as exc:
            raise LookupError(label) from exc

    def _click_submenu(self, label: str, parent_selector: str, child_selector: str) -> None:
        if not parent_selector or not child_selector:
            raise LookupError(label)
        parent = self._page.locator(parent_selector).filter(has_text=label)
        parent.first.wait_for(state="visible", timeout=_CONTROL_TIMEOUT_MS)
        parent.first.click(timeout=_CONTROL_TIMEOUT_MS)
        child = self._page.locator(child_selector).filter(has_text=label)
        child.first.wait_for(state="visible", timeout=_CONTROL_TIMEOUT_MS)
        self._click_maybe_new_tab(child.first, opens_tab=True)

    def _click_maybe_new_tab(self, locator, *, opens_tab: bool) -> None:
        if not opens_tab:
            locator.click(timeout=_CONTROL_TIMEOUT_MS)
            self._wait_settled()
            assert_allowed_url(self.url(), self._allowed)
            return
        try:
            with self._context.expect_page(timeout=_POPUP_TIMEOUT_MS) as info:
                locator.click(timeout=_CONTROL_TIMEOUT_MS)
            page = info.value
        except Exception as exc:
            raise LookupError("insights tab did not open") from exc
        self._adopt_page(page)

    def _adopt_page(self, page) -> None:
        """Follow a tab this click opened. A pre-existing tab is never adopted."""
        self._owned.append(page)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        except Exception:
            pass
        self._wait_settled(page)
        try:
            self._wait_for_visible_controls(page)
        except Exception:
            pass
        self._page = page
        assert_allowed_url(page.url, self._allowed)

    def fill(self, selector: str, value: str) -> None:
        assert_safe_fill(selector, value)
        locator = self._page.locator(selector).first
        locator.wait_for(state="visible", timeout=_CONTROL_TIMEOUT_MS)
        locator.fill(value, timeout=_CONTROL_TIMEOUT_MS)
        self._wait_settled()

    def ensure_only_gym(self, gym_name: str, *, label: str = "Select Gyms") -> dict:
        """Leave one gym selected by clicking the visible Remove controls.

        The read-back is selected_gyms(). A screen that does not show exactly
        this gym stays unverified; the caller stops.
        """
        assert_safe_click(gym_name)
        assert_safe_click(label)
        page = self._page
        page.get_by_text(label, exact=False).first.wait_for(state="visible", timeout=_CONTROL_TIMEOUT_MS)
        for extra in [name for name in self._gym_chip_names() if name != gym_name]:
            assert_safe_click(extra)
            remove = page.get_by_role("button", name=f"Remove {extra}", exact=True)
            if remove.count() == 0:
                remove = page.locator(f"[aria-label='Remove {extra}']")
            if remove.count() == 0:
                break
            remove.first.click(timeout=_CONTROL_TIMEOUT_MS)
            self._wait_settled()
        if gym_name not in self._gym_chip_names():
            page.get_by_text(label, exact=False).first.click(timeout=_CONTROL_TIMEOUT_MS)
            option = page.get_by_role("option", name=gym_name, exact=True)
            if option.count() == 0:
                option = page.get_by_text(gym_name, exact=True)
            if option.count() > 0:
                option.first.click(timeout=_CONTROL_TIMEOUT_MS)
                self._wait_settled()
        selected = self._gym_chip_names()
        return {"verified": selected == [gym_name], "selected": selected}

    def selected_gyms(self) -> list[str]:
        return self._gym_chip_names()

    def _gym_chip_names(self) -> list[str]:
        names: list[str] = []
        removes = self._page.locator("[aria-label^='Remove ']")
        try:
            count = min(removes.count(), 20)
        except Exception:
            return names
        for index in range(count):
            aria = removes.nth(index).get_attribute("aria-label") or ""
            if not aria.startswith("Remove "):
                continue
            name = aria[len("Remove ") :].strip()
            if name and name not in names:
                names.append(name)
        return names

    def read_screen(self, count_selectors: list[str], total_selectors: list[str]) -> dict:
        """Read Membr's own on-screen count. The text is not edited.

        The count is read twice so a late paint does not capture a stale 0.
        This is one settle, not a refresh loop.
        """
        self._wait_settled()
        return {
            "count_text": self._settled_text(count_selectors),
            "total_text": self._locator_text(total_selectors, wait=False),
        }

    def _settled_text(self, selectors: list[str]) -> str | None:
        self._locator_text(selectors, wait=True)
        previous = None
        last = None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = self._locator_text(selectors, wait=False)
            last = current
            if current is not None and current == previous:
                return current
            previous = current
            time.sleep(0.25)
        return last

    def _locator_text(self, selectors: list[str], *, wait: bool) -> str | None:
        for selector in selectors:
            if assert_safe_selector(selector) is False:
                continue
            locator = self._page.locator(selector)
            try:
                if wait:
                    locator.first.wait_for(state="visible", timeout=_CONTROL_TIMEOUT_MS)
                elif locator.count() == 0:
                    continue
                if locator.count() == 0:
                    continue
                return locator.first.inner_text(timeout=_CONTROL_TIMEOUT_MS)
            except Exception:
                continue
        return None

    def download(self, selectors: list[str], dest: Path, *, two_step: bool = False) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if two_step:
            if len(selectors) < 2:
                raise LookupError("download menu")
            opener, choice = selectors[0], selectors[1]
            if assert_safe_selector(opener) is False or assert_safe_selector(choice) is False:
                raise LookupError("download control not found")
            self._page.locator(opener).first.click(timeout=_CONTROL_TIMEOUT_MS)
            target = self._page.locator(choice).first
            target.wait_for(state="visible", timeout=_CONTROL_TIMEOUT_MS)
            with self._page.expect_download(timeout=_DOWNLOAD_TIMEOUT_MS) as info:
                target.click(timeout=_CONTROL_TIMEOUT_MS)
            info.value.save_as(str(dest))
            return
        last = "download control not found"
        for selector in selectors:
            if assert_safe_selector(selector) is False:
                continue
            locator = self._page.locator(selector)
            if locator.count() == 0:
                continue
            with self._page.expect_download(timeout=_DOWNLOAD_TIMEOUT_MS) as info:
                locator.first.click()
            info.value.save_as(str(dest))
            return
        raise LookupError(last)

    def snapshot(self) -> dict:
        self.wait_for_view()
        try:
            raw = self._page.evaluate(_SNAPSHOT_JS)
            raw["login_wall"] = None
        except Exception:
            raw = structure_from_html(self.url(), self.content())
        return annotate_structure(raw)

    def cookies(self) -> list[dict]:
        """Names, hosts and expiries only. Values are dropped here.

        Cookie names are not a Membr login signal. Session detection reads the
        page (dashboard versus login form or captcha).
        """
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

    def _wait_settled(self, page=None) -> None:
        page = page or self._page
        try:
            page.wait_for_load_state("networkidle", timeout=_IDLE_TIMEOUT_MS)
        except Exception:
            return

    def _wait_for_visible_controls(self, page=None) -> None:
        page = page or self._page
        self._wait_settled(page)
        try:
            page.locator(
                "a:visible, button:visible, input:visible, textarea:visible, select:visible"
            ).first.wait_for(timeout=_CONTROL_TIMEOUT_MS)
        except Exception:
            # A captcha shell can render without those tags. The caller still
            # reads the HTML and stops when the page is a login wall.
            return

    def close(self) -> None:
        for page in tabs_we_may_close(self._owned, self._preexisting):
            try:
                if page.is_closed():
                    continue
                page.close()
            except Exception:
                pass
        self._owned = []
        if self._attached:
            # Disconnect only. browser.close() on a CDP session closes the window.
            try:
                self._playwright.stop()
            except Exception:
                pass
            return
        # This browser was started for the run. context.close() ends that
        # process. Attach over CDP when other sites already have tabs open.
        try:
            self._context.close()
        finally:
            try:
                self._playwright.stop()
            except Exception:
                pass


def assert_safe_selector(selector: str) -> bool:
    lowered = (selector or "").lower()
    if "password" in lowered or "captcha" in lowered:
        return False
    return True


def _own_page(context):
    preexisting = list(context.pages)
    page = context.new_page()
    return page, preexisting


def open_session(cfg: dict) -> PlaywrightSession:
    from playwright.sync_api import sync_playwright

    browser_cfg = cfg.get("browser") or {}
    club = str(cfg["club_base_url"])
    allowed = allowed_hostnames(cfg)
    assert_allowed_url(club, allowed)
    playwright = sync_playwright().start()
    cdp = browser_cfg.get("cdp_url") or "http://127.0.0.1:9222"
    try:
        browser = playwright.chromium.connect_over_cdp(cdp, timeout=5_000)
        context = browser.contexts[0] if browser.contexts else browser.new_context(accept_downloads=True)
        page, preexisting = _own_page(context)
        return PlaywrightSession(
            playwright,
            browser,
            context,
            page,
            attached=True,
            allowed=allowed,
            club=club,
            preexisting=preexisting,
            owned=[page],
        )
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
    page, preexisting = _own_page(context)
    return PlaywrightSession(
        playwright,
        None,
        context,
        page,
        attached=False,
        allowed=allowed,
        club=club,
        preexisting=preexisting,
        owned=[page],
    )


_SNAPSHOT_JS = """
() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const take = (sel) => Array.from(document.querySelectorAll(sel)).filter(visible).slice(0, 200).map((el) => ({
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
    elements: take("a, button, input, select, textarea, h1, h2, h3, label, [role='menuitem']")
  };
}
"""
