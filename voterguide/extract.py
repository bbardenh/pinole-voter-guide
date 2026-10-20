"""Extract endorsements from a fetched page with the Claude API.

Guardrails: output is schema-constrained; every item must carry a verbatim quote, and the
quote is checked against the page text so an invented endorsement cannot pass as high
confidence; contest keys are validated against the registry.
"""
from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

from . import locality
from .discover import TIMEOUT, UA, frame_target
from .render import render_html

MODEL = os.environ.get("VG_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("VG_EFFORT", "medium")
USE_FALLBACKS = os.environ.get("VG_FALLBACKS", "1") != "0"
MAX_CHARS = 600_000          # ~150k tokens; beyond this we flag instead of silently cutting
MAX_PDF_BYTES = 30 * 1024 * 1024

POSITIONS = ["yes", "no", "neutral", "no_position", "no_endorsement", "candidate"]
CONFIDENCE = ["high", "medium", "low"]

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["page", "endorsements"],
    "properties": {
        "page": {
            "type": "object",
            "additionalProperties": False,
            "required": ["is_endorsement_page", "election", "covers_this_area", "note"],
            "properties": {
                "is_endorsement_page": {"type": "boolean"},
                "election": {"type": "string"},
                "covers_this_area": {"type": "boolean"},
                "note": {"type": "string"},
            },
        },
        "endorsements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["contest_key", "contest_label", "position", "candidates", "evidence", "confidence"],
                "properties": {
                    "contest_key": {"type": "string"},
                    "contest_label": {"type": "string"},
                    "position": {"type": "string", "enum": POSITIONS},
                    "candidates": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "string", "enum": CONFIDENCE},
                },
            },
        },
    },
}

SYSTEM = """You extract voter-guide endorsements from one web page or PDF published by one organization.

Rules:
- Report only what the source explicitly says. Never infer an endorsement from the organization's general politics, and never fill gaps from background knowledge.
- Scope: the November 3, 2026 general election, as it affects __AREA__ voters. Ignore other elections, other years, other states and other cities' races. covers_this_area is true if the source covers any contest on that ballot (statewide propositions count).
- For judicial retention questions ("Retain Justice X?") yes = retain, no = do not retain; many guides give one blanket recommendation for all justices - report it for each justice named in the registry only if the source clearly applies it to them.
- For ballot measures use position yes / no / neutral / no_position / no_endorsement. For candidate races use position "candidate" and list candidate names in the order endorsed (rank 1 first); use [] for candidates on measures.
- contest_key must be one of the registry keys provided. If the source covers a contest that is not in the registry, use contest_key "unlisted" and give the contest as the source names it in contest_label.
- evidence must be a short VERBATIM quote (max 200 characters) copied from the source that supports the item. If you cannot quote it, do not report the item.
- confidence: high = explicit and unambiguous; medium = clear but terse or indirect; low = ambiguous, partially legible, or stale-looking.
- is_endorsement_page is true only if the source actually lists this organization's endorsements or recommendations for the 2026 cycle. A home page, news post, event page or older-cycle guide is false, and endorsements is [].
- If the source says endorsements are not yet announced, return is_endorsement_page false and explain in note.""".replace(
    "__AREA__", locality.load()["area_text"])


@dataclass
class Item:
    contest_key: str
    contest_label: str
    position: str
    candidates: list[str]
    evidence: str
    confidence: str
    flags: list[str] = field(default_factory=list)


@dataclass
class Extraction:
    org_id: str
    url: str
    ok: bool = False
    is_endorsement_page: bool = False
    election: str = ""
    note: str = ""
    items: list[Item] = field(default_factory=list)
    error: str = ""
    fatal: bool = False          # account-level problem (credit, auth): retrying other pages is pointless
    truncated: bool = False
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def _norm(s: str) -> str:
    s = (s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-").replace(" ", " "))
    return re.sub(r"\s+", " ", s).strip().lower()


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return "\n".join(line for line in soup.get_text("\n", strip=True).splitlines() if line.strip())


def direct_url(url: str) -> str:
    """Google Drive/Docs viewer links -> directly downloadable/exportable URLs."""
    m = re.search(r"drive\.google\.com/file/d/([\w-]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    m = re.search(r"docs\.google\.com/document/d/([\w-]+)", url)
    if m:
        return f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt"
    return url


IMG_SKIP = re.compile(r"logo|icon|avatar|sprite|favicon|spacer|pixel|badge|emoji|\.svg", re.IGNORECASE)
IMG_EXT = re.compile(r"\.(png|jpe?g|webp|gif)(\?|$)", re.IGNORECASE)
MIN_IMAGE_BYTES, MAX_IMAGE_BYTES, MAX_IMAGES = 30_000, 5_000_000, 8
TEXT_ENOUGH = 1500    # pages with less visible text than this are also checked for images


def _sniff_image(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def find_images(html: str, base_url: str) -> list[str]:
    """Candidate content images on a page (img/srcset/lazy attrs, links to images, og:image), in page order."""
    from urllib.parse import urljoin

    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    def add(u: str | None) -> None:
        if not u or u.startswith("data:"):
            return
        full = urljoin(base_url, u.strip())
        if full not in urls and not IMG_SKIP.search(full.split("?")[0]):
            urls.append(full)

    for img in soup.find_all("img"):
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:   # take the largest candidate
            add(srcset.split(",")[-1].strip().split(" ")[0])
        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            add(img.get(attr))
    for a in soup.find_all("a", href=True):
        if IMG_EXT.search(a["href"]):
            add(a["href"])
    og = soup.find("meta", property="og:image")
    if og:
        add(og.get("content"))
    return urls


def download_images(urls: list[str]) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for u in urls:
        if len(out) >= MAX_IMAGES:
            break
        try:
            r = requests.get(u, headers={"User-Agent": UA}, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code != 200 or not (MIN_IMAGE_BYTES <= len(r.content) <= MAX_IMAGE_BYTES):
            continue
        mt = _sniff_image(r.content)
        if mt:
            out.append((mt, r.content))
    return out


def load_source(url: str, _depth: int = 0) -> tuple[str, bytes | None, list[tuple[str, bytes]], str]:
    """Return (text, pdf_bytes, images, error). A PDF comes back alone; otherwise text, plus content images
    when the page has little text. Falls back to a headless browser when the site blocks plain HTTP or the
    page is JS-rendered."""
    url = direct_url(url)
    r = None
    err = ""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as e:
        err = f"{type(e).__name__}: {e}"[:200]
    html, base = "", url
    if r is not None and r.status_code == 200:
        ctype = r.headers.get("Content-Type", "").lower()
        if "pdf" in ctype or r.url.lower().split("?")[0].endswith(".pdf") or r.content[:5] == b"%PDF-":
            if len(r.content) > MAX_PDF_BYTES:
                return "", None, [], "PDF larger than 30 MB"
            return "", r.content, [], ""
        mt = _sniff_image(r.content)
        if mt:   # the URL is itself an image (a posted slate graphic)
            return "", None, [(mt, r.content)] if MIN_IMAGE_BYTES <= len(r.content) <= MAX_IMAGE_BYTES else [], ""
        if "text/plain" in ctype:
            return r.text, None, [], ""
        html, base = r.text, r.url
        target = frame_target(html, base)
        if target and target != url and _depth < 1:   # page is just a frame around another site
            return load_source(target, _depth + 1)
        text = html_to_text(html)
        if len(text) >= TEXT_ENOUGH:
            return text, None, [], ""
        err = "page text nearly empty"
    elif r is not None:
        err = f"HTTP {r.status_code}"      # 202/403/429/503 are often bot challenges: the browser fallback below retries

    rendered = render_html(url)
    if rendered and rendered[0] == 200:
        r_text = html_to_text(rendered[2])
        if len(r_text) > len(html_to_text(html) if html else ""):
            html, base = rendered[2], rendered[1]
    text = html_to_text(html) if html else ""
    if len(text) >= TEXT_ENOUGH:
        return text, None, [], ""
    # Little text: the endorsements may be pictures. Read them with vision.
    images = download_images(find_images(html, base)) if html else []
    if images:
        return text, None, images, ""
    if len(text) >= 100:
        return text, None, [], ""
    return "", None, [], err or "empty page"


RELEVANT = re.compile(
    r"endors|recommend|vot(e|ing)|measure|propos|\bprop\b|council|mayor|governor|district|school|ballot|"
    r"candidate|yes on|no on|2026|\bbart\b|ac transit|ebmud|trustee|judge|justice", re.IGNORECASE)


@dataclass
class Source:
    """A fetched page: free to obtain, and its fingerprint tells us whether it changed since last time."""
    url: str
    text: str = ""
    pdf: bytes | None = None
    images: list = field(default_factory=list)
    error: str = ""

    def fingerprint(self) -> str:
        import hashlib

        h = hashlib.sha256()
        lines = [_norm(l) for l in self.text.splitlines() if l.strip()]
        if len(self.text) > 8000:   # big pages: ignore unrelated chatter (news feeds, footers) that changes daily
            lines = [l for l in lines if RELEVANT.search(l)]
        h.update("\n".join(lines).encode("utf-8"))
        for _mt, data in self.images:
            h.update(hashlib.sha256(data).digest())
        if self.pdf:
            h.update(hashlib.sha256(self.pdf).digest())
        return h.hexdigest()[:16]

    def estimated_tokens(self) -> int:
        return len(self.text) // 4 + 1500 * len(self.images) + (len(self.pdf) // 40 if self.pdf else 0) + 3000


def fetch_source(url: str) -> Source:
    text, pdf, images, err = load_source(url)
    return Source(url=url, text=text, pdf=pdf, images=images, error=err)


def _registry_block(registry: list[dict]) -> str:
    lines = []
    for c in registry:
        cands = f" [candidates: {'; '.join(c['candidates'])}]" if c.get("candidates") else ""
        lines.append(f"- {c['key']}: {c['label']}{cands}")
    return "\n".join(lines)


def extract(org: dict, url: str, registry: list[dict], client=None, source: Source | None = None) -> Extraction:
    import anthropic

    out = Extraction(org_id=org["id"], url=url, model=MODEL)
    try:
        client = client or anthropic.Anthropic()
    except TypeError:
        out.error = "ANTHROPIC_API_KEY is not set"
        return out
    source = source or fetch_source(url)
    if source.error:
        out.error = source.error
        return out
    text, pdf, images = source.text, source.pdf, source.images

    header = (f"Organization: {org['name']}\nSource URL: {url}\n\n"
              f"Contest registry (use these keys):\n{_registry_block(registry)}\n\nSource follows.\n")
    if pdf is not None:
        content = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.standard_b64encode(pdf).decode()}},
            {"type": "text", "text": header},
        ]
        page_text = ""
    else:
        if len(text) > MAX_CHARS:
            out.truncated = True
            text = text[:MAX_CHARS]
        content = [{"type": "image", "source": {"type": "base64", "media_type": mt,
                                                "data": base64.standard_b64encode(data).decode()}}
                   for mt, data in images]
        note = ("\n(The source's endorsements may appear only inside the images above; read any text in them.)\n"
                if images else "")
        content.append({"type": "text", "text": header + note + "\n" + text})
        page_text = text
    unverifiable = pdf is not None or bool(images)   # quotes cannot be checked against page text

    kwargs = dict(
        model=MODEL, max_tokens=16000, system=SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        if USE_FALLBACKS:
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            resp = client.messages.create(**kwargs)
    except anthropic.APIStatusError as e:
        out.error = f"API {e.status_code}: {e.message}"[:300]
        out.fatal = e.status_code in (401, 403) or "credit balance" in str(e.message).lower()
        return out
    except anthropic.APIConnectionError as e:
        out.error = f"connection: {e}"[:300]
        return out

    out.model = resp.model
    out.input_tokens, out.output_tokens = resp.usage.input_tokens, resp.usage.output_tokens
    if resp.stop_reason in ("refusal", "max_tokens"):
        out.error = f"stop_reason={resp.stop_reason}"
        return out
    body = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        out.error = f"bad JSON from model: {e}"
        return out

    page = data["page"]
    out.is_endorsement_page = bool(page["is_endorsement_page"])
    out.election, out.note = page["election"], page["note"]
    keys = {c["key"] for c in registry}
    norm_page = _norm(page_text)
    for raw in data["endorsements"]:
        item = Item(**raw)
        if item.contest_key not in keys and item.contest_key != "unlisted":
            item.flags.append("unknown_contest_key")
            item.contest_key = "unlisted"
        if item.position == "candidate" and not item.candidates:
            item.flags.append("candidate_position_without_names")
        if not unverifiable and _norm(item.evidence) not in norm_page:
            item.flags.append("evidence_not_found_in_page")
        elif unverifiable:
            item.flags.append("evidence_unchecked_image" if images else "evidence_unchecked_pdf")
        if item.flags and item.confidence == "high" and not any(f.startswith("evidence_unchecked") for f in item.flags):
            item.confidence = "low"
        out.items.append(item)
    if out.truncated:
        out.note = (out.note + " [page truncated at 600k chars]").strip()
    out.ok = True
    return out
