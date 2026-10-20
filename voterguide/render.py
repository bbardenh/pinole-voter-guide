"""Headless-browser fallback for pages that block plain HTTP clients or render with JavaScript.

Playwright is optional: if it is not installed, render_html() returns None and callers keep the
plain-HTTP result. Disable with VG_RENDER=0.
"""
from __future__ import annotations

import os

CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/124.0.0.0 Safari/537.36")


def enabled() -> bool:
    return os.environ.get("VG_RENDER", "1") != "0"


def render_html(url: str, timeout_ms: int = 35000) -> tuple[int, str, str] | None:
    """Return (http_status, final_url, html) after JavaScript has run, or None if unavailable/failed."""
    if not enabled():
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                ctx = browser.new_context(user_agent=CHROME_UA, locale="en-US", viewport={"width": 1280, "height": 900})
                page = ctx.new_page()
                resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass   # long-polling pages never go idle; take what has rendered
                return (resp.status if resp else 0, page.url, page.content())
            finally:
                browser.close()
    except Exception:
        return None
