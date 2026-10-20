"""Ask the model which links on an organization's pages lead to its 2026 endorsements.

Used when rule-based discovery's top candidates did not turn out to be endorsement pages. The model sees
only link texts and URLs (a few thousand tokens), and every URL it returns is checked to exist in that list.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import locality
from .discover import SOCIAL_HOSTS, fetch, site_root
from .extract import MODEL

MAX_LINKS = 400

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["urls", "reason"],
    "properties": {
        "urls": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
}

SYSTEM = """You help find an organization's voter guide. You are given the links found on its web pages.
Pick up to 4 links most likely to lead to this organization's endorsements or voter guide for the
November 3, 2026 general election (__AREA__). Prefer pages whose text or URL
mention 2026, the November general election, endorsements, voter guide, slate, ballot or recommendations.
Avoid older years, the June primary, other states and cities, event pages, news posts about other topics, and
social-media links. Copy each URL exactly as it appears in the list. Return an empty list if nothing looks right.""".replace(
    "__AREA__", locality.load()["area_text"])


def collect_links(page_urls: list[str]) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    for page_url in page_urls:
        f = fetch(page_url)
        if not f.ok or f.is_pdf:
            continue
        soup = BeautifulSoup(f.text, "html.parser")
        base = f.final_url or page_url
        for a in soup.find_all("a", href=True):
            href = urljoin(base, a["href"]).split("#")[0]
            p = urlparse(href)
            if p.scheme not in ("http", "https") or any(h in p.netloc for h in SOCIAL_HOSTS if "google.com" not in h):
                continue
            text = " ".join(a.get_text(" ", strip=True).split())[:80]
            if href not in seen or (text and not seen[href]):
                seen[href] = text
    return list(seen.items())


def choose_links(org: dict, page_urls: list[str], exclude: set[str], client=None) -> tuple[list[str], str, int, int]:
    """Return (urls, reason, input_tokens, output_tokens)."""
    import anthropic

    links = [(u, t) for u, t in collect_links(page_urls) if u not in exclude][:MAX_LINKS]
    if not links:
        return [], "no links collected", 0, 0
    client = client or anthropic.Anthropic()
    listing = "\n".join(f"{t or '(no text)'} -> {u}" for u, t in links)
    kwargs = dict(
        model=MODEL, max_tokens=2000, system=SYSTEM,
        messages=[{"role": "user", "content": f"Organization: {org['name']}\nLinks:\n{listing}"}],
        output_config={"effort": os.environ.get("VG_EFFORT", "medium"),
                       "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        if os.environ.get("VG_FALLBACKS", "1") != "0":
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            resp = client.messages.create(**kwargs)
        body = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(body)
    except (anthropic.APIError, json.JSONDecodeError):
        return [], "navigator call failed", 0, 0
    valid = {u for u, _ in links}
    urls = [u for u in data["urls"] if u in valid][:4]
    return urls, data["reason"], resp.usage.input_tokens, resp.usage.output_tokens


def pages_for(org: dict) -> list[str]:
    """Pages whose links the navigator should see: the configured home page and, if different, the site root."""
    home = org.get("home_url") or ""
    pages = [home] if home else []
    if home and site_root(home) not in pages:
        pages.append(site_root(home))
    return pages
