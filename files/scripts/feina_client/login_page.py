"""Decide whether an HTML page is Membr's login or a captcha.

This looks at the page the club's normal address returned. It does not submit
the form, and it does not call any Membr URL itself.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlparse

CAPTCHA_MARKERS = (
    "g-recaptcha",
    "h-captcha",
    "cf-turnstile",
    "data-sitekey",
    "recaptcha",
    "hcaptcha",
    "captcha",
    "no soy un robot",
    "i'm not a robot",
    "je ne suis pas un robot",
)

_PASSWORD_INPUT = re.compile(
    r"<input\b[^>]*\btype\s*=\s*['\"]password['\"][^>]*>",
    re.IGNORECASE,
)

_LOGIN_PATHS = ("/login", "/signin", "/sign-in", "/auth/login", "/account/login")


def detect_login_wall(url: str, html: str) -> str | None:
    """Return 'captcha', 'login', or None when the page looks signed in."""
    blob = html or ""
    lowered = blob.lower()
    if any(marker in lowered for marker in CAPTCHA_MARKERS):
        return "captcha"
    path = (urlparse(url or "").path or "").lower().rstrip("/")
    for login_path in _LOGIN_PATHS:
        if path == login_path.rstrip("/") or path.endswith(login_path.rstrip("/")):
            return "login"
    if _PASSWORD_INPUT.search(blob):
        return "login"
    return None


class _StructureParser(HTMLParser):
    _TAGS = {"a", "button", "input", "select", "textarea", "h1", "h2", "h3", "label"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self._capture: dict | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._flush()
        if tag not in self._TAGS or len(self.items) >= 300:
            return
        attr = {k: (v or "") for k, v in attrs}
        if attr.get("type", "").lower() == "password":
            attr.pop("value", None)
        item = {
            "tag": tag,
            "id": attr.get("id", ""),
            "name": attr.get("name", ""),
            "type": attr.get("type", ""),
            "href": attr.get("href", "") if tag == "a" else "",
            "aria": attr.get("aria-label", ""),
            "placeholder": attr.get("placeholder", ""),
            "role": attr.get("role", ""),
        }
        self.items.append(item)
        self._capture = item
        self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if self._capture and self._capture.get("tag") == tag:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._buf.append(data)

    def _flush(self) -> None:
        if self._capture is None:
            return
        text = " ".join("".join(self._buf).split())[:120]
        self._capture["text"] = text
        self._capture = None
        self._buf = []


def structure_from_html(url: str, html: str) -> dict:
    parser = _StructureParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        pass
    parser._flush()
    title = ""
    match = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.IGNORECASE | re.DOTALL)
    if match:
        title = " ".join(match.group(1).split())[:160]
    return {
        "url": url,
        "title": title,
        "login_wall": detect_login_wall(url, html),
        "elements": parser.items,
    }
