"""Contra Costa County Elections Division: elections list, local races, candidates and local measures.

The county publishes no API. For the current election, its "Run for Office" page links PDFs by link text:
"Candidate Summary List" (contest code lines like "PinoleCouncil Vote for 3", then one line per candidate) and
"List of Local Ballot Measures" (blocks starting "MEASURE X"). File names change with every update, so they are
found by link text, and each PDF's first line is checked against the election date. Federal and state candidates
are not in these PDFs; registry_builder reads them from the Secretary of State's certified list.
"""
from __future__ import annotations

import io
import re
import time
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from . import locality

BASE = "https://www.contracostavote.gov"
DOCS_PAGE = f"{BASE}/elections/candidates-campaigns-measures/run-for-office/run-for-office/"
ELECTIONS_PAGE = f"{BASE}/upcoming-elections/"
DOC_LINKS = {
    "candidates": re.compile(r"candidate\s+summary\s+list", re.I),
    "measures": re.compile(r"list\s+of\s+local\s+ballot\s+measures|measure\s+wording\s+list", re.I),
    "positions": re.compile(r"positions\s+up\s+for\s+election", re.I),
}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def _headers() -> dict:
    return {"User-Agent": f"Mozilla/5.0 (compatible; {locality.load()['bot_name']}/0.1)"}


def _get(url: str, **kw) -> requests.Response:
    for attempt in range(3):
        try:
            return requests.get(url, headers={**_headers(), **kw.pop("headers", {})}, timeout=60, **kw)
        except requests.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"cannot reach {url}")


def pdf_text(url: str) -> str:
    from pypdf import PdfReader

    r = _get(url)
    r.raise_for_status()
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages)


# ---- elections ---------------------------------------------------------------------------------------------------

def parse_election_slug(slug: str) -> tuple[date | None, str]:
    """'november-3-2026-general-election' -> (date(2026, 11, 3), 'General Election')."""
    m = re.match(r"([a-z]+)-(\d{1,2})-(\d{4})-(.+)$", slug.strip("/").split("/")[-1])
    if not m or m.group(1) not in MONTHS:
        return None, ""
    when = date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
    return when, " ".join(w.capitalize() for w in m.group(4).split("-"))


def list_elections() -> list[dict]:
    """Elections linked from the county's Upcoming Elections page: [{id, date, name}]."""
    html = _get(ELECTIONS_PAGE).text
    out, seen = [], set()
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        m = re.search(r"/election/([a-z0-9-]+)/?", a["href"])
        if not m or m.group(1) in seen:
            continue
        when, name = parse_election_slug(m.group(1))
        if when:
            seen.add(m.group(1))
            out.append({"id": m.group(1), "date": when, "name": name})
    return out


# ---- documents for the current election --------------------------------------------------------------------------

def find_documents(html: str, base: str = DOCS_PAGE) -> dict[str, str]:
    """Link text -> absolute PDF URL for the candidate list, measures list and positions list."""
    out: dict[str, str] = {}
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        for kind, pat in DOC_LINKS.items():
            if kind not in out and pat.search(text):
                out[kind] = urljoin(base, a["href"])
    return out


def documents() -> dict[str, str]:
    return find_documents(_get(DOCS_PAGE).text)


def document_date(text: str) -> date | None:
    """First m/d/yyyy in the PDF header ('November 3 2026 General Election - 11/3/2026')."""
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text[:400])
    return date(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None


def document_mentions(text: str, when: date) -> bool:
    """Measures list has no numeric date; accept 'November 3, 2026' / 'Nov 3 2026' / '26Nov03'-style mentions."""
    head = re.sub(r"\s+", " ", text[:1500]).lower()
    month = when.strftime("%B").lower()
    return bool(re.search(rf"{month[:3]}\w*\.? {when.day},? {when.year}", head)) or document_date(text) == when


# ---- candidate summary list -------------------------------------------------------------------------------------

CONTEST_LINE = re.compile(r"^(?P<code>\S.*?)\s+Vote for (?P<n>\d+)\s*$", re.I)
CANDIDATE_LINE = re.compile(r"^(?P<name>\S.*?)\s+\d{1,2}/\s?\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*[AP]M\b", re.I)
NOT_QUALIFIED = re.compile(r"\(?\s*not\s+qualified\s*\)?|\bwithdrawn\b", re.I)


def parse_candidate_list(text: str) -> list[dict]:
    """[{code, vote_for, candidates: [NAME, ...]}] in document order. Page headers between entries are ignored."""
    out: list[dict] = []
    cur = None
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        m = CONTEST_LINE.match(line)
        if m:
            cur = {"code": m.group("code").strip(), "vote_for": int(m.group("n")), "candidates": []}
            out.append(cur)
            continue
        m = CANDIDATE_LINE.match(line)
        if m and cur is not None and not NOT_QUALIFIED.search(line):
            cur["candidates"].append(m.group("name").strip())
    return out


def candidate_contests(url: str, when: date) -> list[dict]:
    text = pdf_text(url)
    got = document_date(text)
    if got != when:
        raise RuntimeError(f"county candidate list is for {got}, not {when}")
    return parse_candidate_list(text)


# ---- local measures ---------------------------------------------------------------------------------------------

MEASURE_LINE = re.compile(r"^MEASURE\s*(?P<l>[A-Z]{1,3})\b\.?\s*(?P<rest>.*)$")


def parse_measures(text: str) -> list[dict]:
    """[{letter, title, text}]: one block per 'MEASURE X' line; title = rest of that line or the next line."""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    starts = [(i, MEASURE_LINE.match(ln)) for i, ln in enumerate(lines)]
    starts = [(i, m) for i, m in starts if m]
    out = []
    for n, (i, m) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        body = [ln for ln in lines[i + 1:end] if ln]
        title = m.group("rest").strip(" -:") or (body[0] if body else "")
        out.append({"letter": m.group("l"), "title": title, "text": " ".join(body)})
    return out


def measures(url: str, when: date) -> list[dict]:
    text = pdf_text(url)
    if not document_mentions(text, when) and document_date(text) not in (None, when):
        raise RuntimeError(f"county measures list does not look like the {when} election")
    return parse_measures(text)

