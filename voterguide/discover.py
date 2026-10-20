"""Find each organization's current endorsements page, starting from its home page."""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from . import locality
from .render import render_html

UA = f"Mozilla/5.0 (compatible; {locality.load()['bot_name']}/0.1)"
TIMEOUT = 20
SOCIAL_HOSTS = ("facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
                "youtube.com", "tiktok.com", "drive.google.com", "docs.google.com")
CYCLE_YEAR = "2026"

# (regex, weight) applied to anchor text + path
LINK_SIGNALS = [
    (r"endorse", 6), (r"voter[-\s_]?guide|voters[-\s_]?guide", 6), (r"slate", 4),
    (r"ballot", 3), (r"election", 2), (r"vote|voting", 1), (r"recommend", 3),
    (CYCLE_YEAR, 4),
    (r"20(1\d|2[0-5])", -4),   # stale-cycle years
    (r"general", 3),
    (r"primary", -6),                                   # June primary, not November
    (r"past|archive|previous|history", -6),
    (r"event|phonebank|calendar|rsvp|webinar", -5),
    (r"legislative|wrap-?up|newsletter|press", -4),
    (r"(^|[/-])(nv|nevada|az|ny|tx)([/-]|$)", -8),      # other states
    (r"(^|/)sf-|/san-francisco-", -3),
]
# Current-cycle endorsements pages mention these; each distinct hit scores.
PAGE_SIGNALS = [CYCLE_YEAR, r"endors|recommend", r"measure|proposition|prop\.? \d|governor|mayor|council|school board",
                locality.load()["page_signal_regex"], locality.load()["measure_signal_regex"]]
OTHER_STATE = re.compile(r"nevada|arizona|new york|texas", re.IGNORECASE)
BAY_AREA = locality.pattern("area_regex")
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


@dataclass
class Fetched:
    url: str
    final_url: str = ""
    status: int = 0
    content_type: str = ""
    text: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error

    @property
    def is_pdf(self) -> bool:
        return "pdf" in self.content_type.lower() or self.final_url.lower().split("?")[0].endswith(".pdf")


@dataclass
class Discovery:
    org_id: str
    status: str            # found | no_home_url | home_unreachable | no_candidates | no_current_content
    url: str = ""
    kind: str = ""         # html | pdf | gdoc
    score: int = 0
    tried: list[str] = field(default_factory=list)
    candidates: list[tuple[int, str, str]] = field(default_factory=list)   # (score, url, kind), best first
    notes: str = ""


def _visible_len(html: str) -> int:
    return len(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))


def frame_target(html: str, base_url: str) -> str | None:
    """Old-style framesets / full-page iframes just embed another site; return the embedded URL."""
    if _visible_len(html) >= 300:
        return None
    m = re.search(r"<i?frame[^>]+src=[\"']([^\"']+)[\"']", html, re.IGNORECASE)
    if not m:
        return None
    target = urljoin(base_url, m.group(1))
    return target if urlparse(target).scheme in ("http", "https") else None


def fetch(url: str, session: requests.Session | None = None, _depth: int = 0) -> Fetched:
    """Plain HTTP first; fall back to a headless browser if blocked (403/429/503) or the page is JS-empty."""
    s = session or requests
    try:
        r = s.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, allow_redirects=True)
        ctype = r.headers.get("Content-Type", "")
        f = Fetched(url, r.url, r.status_code, ctype, "" if "pdf" in ctype.lower() else r.text)
    except requests.RequestException as e:
        f = Fetched(url, error=f"{type(e).__name__}: {e}"[:200])
    is_html = "html" in f.content_type.lower() or not f.content_type
    if f.status == 200 and is_html and f.text and _depth < 1:
        target = frame_target(f.text, f.final_url or url)
        if target and target != url:
            return fetch(target, session, _depth=_depth + 1)
    needs_render = (f.status in (202, 403, 429, 503) or bool(f.error)
                    or (f.status == 200 and is_html and not f.is_pdf and _visible_len(f.text) < 300))
    if needs_render:
        rendered = render_html(url)
        if rendered and rendered[0] == 200 and rendered[2]:
            return Fetched(url, rendered[1], 200, "text/html; rendered", rendered[2])
    return f


def google_export_url(url: str) -> tuple[str, str] | None:
    """Public Google Docs/Drive links -> a directly fetchable URL (kind, url)."""
    m = re.search(r"docs\.google\.com/document/d/([\w-]+)", url)
    if m:
        return "gdoc", f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt"
    m = re.search(r"drive\.google\.com/file/d/([\w-]+)", url)
    if m:
        return "gdrive", f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return None


def site_root(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}/"


def candidate_links(base_url: str, html: str) -> list[tuple[int, str]]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).netloc.removeprefix("www.")
    seen: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        p = urlparse(href)
        if p.scheme not in ("http", "https") or any(h in p.netloc for h in SOCIAL_HOSTS):
            continue
        same_site = p.netloc.removeprefix("www.").endswith(base_host)
        if not same_site and not href.lower().split("?")[0].endswith(".pdf"):
            continue
        blob = f"{a.get_text(' ', strip=True)} {p.path}".lower()
        if not plausible(href, blob):
            continue
        score = sum(w for rx, w in LINK_SIGNALS if re.search(rx, blob))
        if score > 0:
            seen[href] = max(seen.get(href, 0), score)
    return sorted(((s, u) for u, s in seen.items()), reverse=True)


CORE = re.compile(r"endorse|voters?[-\s_]?guide|slate|ballot|recommend|election", re.IGNORECASE)
STALE = re.compile(r"20(1\d|2[0-5])")
ASSET = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js|ico|mp4)(\?|$)|/wp-content/uploads/(?!.*\.pdf)", re.IGNORECASE)


def plausible(href: str, blob: str) -> bool:
    """Hard filters: must look election-related, not an asset, not an old cycle."""
    if ASSET.search(href) or not CORE.search(blob):
        return False
    return not (STALE.search(href) and CYCLE_YEAR not in href)


def page_score(f: Fetched) -> int:
    if not f.ok or f.is_pdf:
        return 0
    text = BeautifulSoup(f.text, "html.parser").get_text(" ", strip=True).lower()
    if OTHER_STATE.search(text) and not BAY_AREA.search(text):
        return 0
    return sum(3 for rx in PAGE_SIGNALS if re.search(rx, text))


def sitemap_links(root: str, session: requests.Session | None = None, limit: int = 2000) -> list[tuple[int, str]]:
    """Fallback when the home page has no useful links: score URLs listed in sitemap.xml."""
    urls: list[str] = []
    pending, seen = [root + "sitemap.xml"], set()
    while pending and len(urls) < limit and len(seen) < 6:
        sm = pending.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        f = fetch(sm, session)
        if not f.ok:
            continue
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", f.text):
            (pending if loc.endswith(".xml") else urls).append(loc)
    scored = []
    for u in urls:
        blob = urlparse(u).path.lower()
        if not plausible(u, blob):
            continue
        s = sum(w for rx, w in LINK_SIGNALS if re.search(rx, blob))
        if s > 0:
            scored.append((s, u))
    return sorted(scored, reverse=True)


def discover(org: dict, session: requests.Session | None = None, max_try: int = 6) -> Discovery:
    d = Discovery(org_id=org["id"], status="no_home_url")
    home = org.get("home_url")
    if not home:
        d.notes = "no home_url configured"
        return d

    # Google Docs/Drive: nothing to crawl, the file itself is the source.
    g = google_export_url(home)
    if g:
        kind, url = g
        f = fetch(url, session)
        d.tried.append(url)
        if not f.ok:
            d.status, d.notes = "home_unreachable", f.error or f"HTTP {f.status} (file not public?)"
            return d
        d.url, d.kind = home, kind
        d.status = "found" if re.search(CYCLE_YEAR, f.text) else "no_current_content"
        if d.status != "found":
            d.notes = f"file readable but never mentions {CYCLE_YEAR}"
        return d

    page = fetch(home, session)
    if not page.ok:
        d.status, d.notes = "home_unreachable", page.error or f"HTTP {page.status}"
        return d
    base = page.final_url or home

    cands: dict[str, int] = {u: s for s, u in candidate_links(base, page.text)}
    root = site_root(base)
    if root != base:  # deep home_url: also look at the site root
        r = fetch(root, session)
        if r.ok:
            for s, u in candidate_links(r.final_url or root, r.text):
                cands.setdefault(u, s)
    seed = org.get("seed_url")
    if seed and not google_export_url(seed) and not any(h in seed for h in SOCIAL_HOSTS):
        cands.setdefault(seed.replace("2020", CYCLE_YEAR), 5)   # last cycle's URL with this year
    if not any(s >= 6 for s in cands.values()):   # nothing convincing on the pages: try the sitemap
        for s, u in sitemap_links(root, session)[:max_try]:
            cands.setdefault(u, s)
    ranked = sorted(((s, u) for u, s in cands.items()), reverse=True)[:max_try]
    d.notes = "" if ranked else "no endorsement-like links found"

    scored: dict[str, tuple[int, str]] = {}
    scored[base] = (page_score(page) * 2, "html")   # the home page itself counts
    for link_score, url in ranked:
        d.tried.append(url)
        f = fetch(url, session)
        if not f.ok:
            continue
        scored[f.final_url or url] = (link_score, "pdf") if f.is_pdf else (page_score(f) * 2 + link_score, "html")
    d.candidates = sorted(((sc_, u_, k_) for u_, (sc_, k_) in scored.items()), reverse=True)
    url, (sc, kind) = max(scored.items(), key=lambda kv: kv[1][0])
    d.url, d.score, d.kind = url, sc, kind
    is_home = url.rstrip("/") in (base.rstrip("/"), root.rstrip("/")) and kind == "html"
    if sc >= 12 and is_home and org.get("home_kind") != "deep":
        d.status, d.notes = "home_page_only", "no dedicated endorsements page found; home page mentions the cycle"
    elif sc >= 12 or (kind == "pdf" and sc >= 8):
        d.status = "found"
    else:
        d.status = "no_candidates" if not ranked else "no_current_content"
        d.notes = (d.notes + " best candidate lacks current-cycle endorsement content").strip()
    return d
