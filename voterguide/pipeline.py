"""Per-organization processing: find the endorsements page, skip the model when nothing changed."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .budget import Budget
from .discover import discover
from .extract import Extraction, Source, extract, fetch_source
from .navigate import choose_links, pages_for
from .reconcile import has_pending_misses

BLOCKED = ("budget_blocked", "api_down")
NAV_RECHECK_DAYS = 30        # re-run the (paid) link finder for a source with no known page at most this often
MAX_PAGES = 3


@dataclass
class Outcome:
    org_id: str
    status: str = "not_published"   # ok | cached | not_published | failing | budget_blocked
    items: list[dict] = field(default_factory=list)
    fresh: bool = False             # items came from a new successful extraction
    page_url: str = ""
    error: str = ""
    spent: float = 0.0
    analyzed: int = 0               # pages the model actually judged (endorsement page or not)
    errors: int = 0                 # pages that could not be fetched or analyzed
    notes: list[str] = field(default_factory=list)


class Context:
    def __init__(self, registry: list[dict], budget: Budget, election: str, store: dict, now: datetime,
                 force_fresh: bool = False):
        self.registry, self.budget, self.election, self.store, self.now = registry, budget, election, store, now
        self.force_fresh = force_fresh
        self.budget_blocked = False
        self.fatal = ""             # set when the API account is unusable (credit exhausted, bad key)

    def blocked_status(self) -> str:
        return "api_down" if self.fatal else "budget_blocked"

    def recheck(self, org_id: str) -> bool:
        return self.force_fresh or has_pending_misses(self.election, org_id, self.store)

    def extract(self, org: dict, url: str, src: Source, out: Outcome) -> Extraction | None:
        """Extract with the budget check; None means the monthly cap blocked the call."""
        from .extract import MODEL

        if self.fatal:
            return None
        if not self.budget.allow(MODEL, src.estimated_tokens()):
            self.budget_blocked = True
            return None
        r = extract(org, url, self.registry, source=src)
        out.spent += self.budget.charge(r.model or MODEL, r.input_tokens, r.output_tokens)
        if r.fatal:
            self.fatal = r.error
        return r


def _ok_page(r: Extraction) -> bool:
    return r.ok and r.is_endorsement_page and bool(r.items)


def _items(r: Extraction) -> list[dict]:
    return [asdict(i) for i in r.items]


def _try_url(org: dict, url: str, st: dict, ctx: Context, out: Outcome, cache: dict) -> bool:
    """Probe one candidate page; True if it is an endorsement page (and `out`/`cache` are filled)."""
    src = fetch_source(url)
    if src.error:
        out.errors += 1
        out.notes.append(f"{url}: {src.error}")
        return False
    fp = src.fingerprint()
    probe = st.setdefault("probes", {}).get(url)
    if probe and probe["fp"] == fp and probe["result"] == "no_endorsements":
        out.analyzed += 1
        return False                          # unchanged and previously judged "no endorsements": free skip
    r = ctx.extract(org, url, src, out)
    if r is None:
        out.status = ctx.blocked_status()
        return False
    if not r.ok:                              # API/parse failure: do not remember it, retry next run
        out.errors += 1
        out.notes.append(f"{url}: {r.error}")
        return False
    out.analyzed += 1
    result = "endorsement_page" if _ok_page(r) else "no_endorsements"
    st["probes"][url] = {"fp": fp, "result": result, "checked": ctx.now.strftime("%Y-%m-%d"), "note": (r.note or r.error)[:300]}
    if result != "endorsement_page":
        return False
    st["page_url"] = url
    out.page_url, out.items, out.fresh, out.status = url, _items(r), True, "ok"
    cache.update({"fp": fp, "url": url, "items": out.items, "extracted_at": ctx.now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return True


def process_org(org: dict, st: dict, cache: dict, ctx: Context) -> Outcome:
    """st = this org's source-health state (mutated); cache = its last accepted extraction (mutated)."""
    out = Outcome(org_id=org["id"])
    page = st.get("page_url")
    st["last_checked"] = ctx.now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1) the known endorsements page
    if page:
        src = fetch_source(page)
        if src.error:
            out.status, out.error, out.page_url = "failing", src.error, page
            out.items = cache.get("items", [])
            return out
        fp = src.fingerprint()
        if cache.get("fp") == fp and not ctx.recheck(org["id"]):
            out.status, out.page_url, out.items = "cached", page, cache.get("items", [])
            return out
        r = ctx.extract(org, page, src, out)
        if r is None:
            out.status, out.page_url, out.items = ctx.blocked_status(), page, cache.get("items", [])
            return out
        if _ok_page(r):
            out.status, out.page_url, out.items, out.fresh = "ok", page, _items(r), True
            if cache.get("fp") != fp:
                st["last_change"] = st["last_checked"]
            cache.update({"fp": fp, "url": page, "items": out.items, "extracted_at": st["last_checked"]})
            return out
        if not r.ok:
            out.status, out.error, out.page_url = "failing", r.error, page
            out.items = cache.get("items", [])
            return out
        out.notes.append(f"{page} no longer looks like an endorsement page; searching again")
        st["page_url"] = None     # fall through to discovery; cached items are kept untouched

    # 2) look for the page (free fetches; the model is called only for new/changed candidates)
    d = discover(org)
    cands = [u for _, u, _ in d.candidates]
    if org.get("hint_url"):
        cands = [org["hint_url"]] + [u for u in cands if u != org["hint_url"]]
    if not cands and org.get("home_url"):
        cands = [org["home_url"]]
    tried: set[str] = set()
    for url in cands[:MAX_PAGES]:
        tried.add(url)
        if _try_url(org, url, st, ctx, out, cache):
            return out
        if out.status in BLOCKED:
            return out

    # 3) model-guided link finding: only for a never-searched source, a changed home page, or monthly
    home = org.get("home_url")
    if home:
        hsrc = fetch_source(home)
        if hsrc.error and not tried:
            out.status, out.error = "failing", hsrc.error
            return out
        home_fp = hsrc.fingerprint() if not hsrc.error else ""
        last_nav = st.get("last_nav")
        due = (not last_nav or home_fp != st.get("home_fp")
               or (ctx.now - datetime.strptime(last_nav, "%Y-%m-%d")).days >= NAV_RECHECK_DAYS)
        if due:
            from .extract import MODEL

            st["home_fp"], st["last_nav"] = home_fp, ctx.now.strftime("%Y-%m-%d")
            if ctx.budget.allow(MODEL, 8000):
                urls, reason, t_in, t_out = choose_links(org, pages_for(org), exclude=tried)
                out.spent += ctx.budget.charge(MODEL, t_in, t_out)
                if reason == "navigator call failed":
                    out.errors += 1
                    out.notes.append("link finder call failed")
                    st["last_nav"] = None          # retry next run
                for url in urls[:MAX_PAGES]:
                    if _try_url(org, url, st, ctx, out, cache):
                        return out
                    if out.status in BLOCKED:
                        return out
            else:
                ctx.budget_blocked = True
                out.status = "budget_blocked"
                return out
    # 4) second hop: a probed page that says it links to the 2026 endorsements (but lists none)
    if _hop(org, st, ctx, out, cache, tried):
        return out
    if out.status in BLOCKED:
        return out
    if out.analyzed == 0 and out.errors > 0:      # nothing could be judged: that is a failure, not "nothing published"
        out.status, out.error = "failing", out.notes[0] if out.notes else "could not read any page"
    else:
        out.status = "not_published"
    return out


def _hop(org: dict, st: dict, ctx: Context, out: Outcome, cache: dict, tried: set[str]) -> bool:
    from .extract import MODEL

    hopped = st.setdefault("hopped", {})
    pages = [u for u, p in st.get("probes", {}).items()
             if p["result"] == "no_endorsements" and hopped.get(u) != p["fp"]
             and re.search(r"2026", p.get("note", "")) and re.search(r"endors|voter guide|recommend", p["note"], re.I)
             and re.search(r"link", p["note"], re.I)][:2]
    if not pages:
        return False
    for u in pages:
        hopped[u] = st["probes"][u]["fp"]
    if not ctx.budget.allow(MODEL, 8000):
        ctx.budget_blocked = True
        out.status = "budget_blocked"
        return False
    urls, _reason, t_in, t_out = choose_links(org, pages, exclude=tried | set(st["probes"]))
    out.spent += ctx.budget.charge(MODEL, t_in, t_out)
    for url in urls[:2]:
        if _try_url(org, url, st, ctx, out, cache):
            return True
        if out.status in BLOCKED:
            return False
    return False
