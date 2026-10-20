"""Suggestions tab (sources to drop / add, possible missing contests) and the Review Queue (cells to eyeball)."""
from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from datetime import date, datetime

import requests

from . import locality

ADD_REFRESH_DAYS = 30
SEARCH_FEE_ESTIMATE = 0.10        # $ assumed for the web searches in one suggestion run
SAMPLE_SIZE = 12
IN_SCOPE = locality.pattern("in_scope_regex")
OTHER_PLACES = locality.pattern("other_places_regex")
CITY = re.compile(rf"\b{re.escape(locality.load()['city_name'])}\b", re.I)


# ---- sources to drop -------------------------------------------------------------------------------------------------

def drop_suggestions(orgs: list[dict], sources: dict, store: dict, election_id: str, election_date: date, today: date) -> list[list[str]]:
    days_out = (election_date - today).days
    rows = []
    for o in orgs:
        s = sources.get(o["id"], {})
        n_active = sum(1 for e in store.values() if e["org_id"] == o["id"] and e["election"] == election_id and e["status"] == "active")
        reason = ""
        if s.get("consecutive_failures", 0) >= 3:
            reason = f"Failing {s['consecutive_failures']} runs in a row: {s.get('last_error', '')[:120]}"
        elif days_out <= 14 and not s.get("page_url"):
            reason = f"No endorsements page found {days_out} days before the election"
        elif s.get("page_url") and n_active == 0 and s.get("status") == "ok":
            reason = "Endorsements page found, but nothing relevant to this guide's contests"
        if reason:
            rows.append(["Drop?", o["name"], reason, o.get("home_url") or "", ""])
    return rows


# ---- contests that orgs mention but the registry lacks -----------------------------------------------------------------

def _norm_label(label: str) -> str:
    return re.sub(r"\W+", " ", label.lower()).strip()


def missing_contest_suggestions(cache: dict, orgs: dict[str, str], min_orgs: int = 2) -> list[list[str]]:
    seen: dict[str, dict] = defaultdict(lambda: {"label": "", "orgs": set()})
    for org_id, c in cache.items():
        for it in c.get("items", []):
            if it.get("contest_key") != "unlisted":
                continue
            label = it.get("contest_label", "")
            if not label or OTHER_PLACES.search(label) and not CITY.search(label):
                continue
            if not IN_SCOPE.search(label):
                continue
            k = _norm_label(label)
            seen[k]["label"] = seen[k]["label"] or label
            seen[k]["orgs"].add(org_id)
    rows = []
    for k, v in sorted(seen.items(), key=lambda kv: -len(kv[1]["orgs"])):
        if len(v["orgs"]) >= min_orgs:
            rows.append(["Add contest?", v["label"], f"Reported by {len(v['orgs'])} organizations but not in the contest list: "
                         + ", ".join(sorted(orgs.get(o, o) for o in v["orgs"]))[:200], "", ""])
    return rows


# ---- sources to add (monthly, web search) ----------------------------------------------------------------------------

def add_due(state: dict, today: date) -> bool:
    last = state.get("generated_at")
    return not last or (today - datetime.strptime(last[:10], "%Y-%m-%d").date()).days >= ADD_REFRESH_DAYS


ADD_SYSTEM = """You help maintain a cross-referenced progressive voter guide for __PLACE__.
It aggregates endorsements from organizations. Use web search to find organizations NOT already in the list that publish
endorsement slates or voter guides covering the given election in __AREA__
(local clubs, unions, tenant and housing groups, environmental groups, community and civil-rights organizations,
progressive newsletters). Rules: only organizations whose endorsements page for that election you actually found by search;
give the exact URL; prefer organizations that cover __CITY__ contests. The guide is PROGRESSIVE: only include organizations
that are progressive or left-of-center in their politics (labor, tenant, racial-justice, environmental, democratic-socialist,
progressive Democratic clubs and similar). Do NOT include centrist, moderate, business-oriented, or conservative groups,
news outlets that only publish editorials, or anything already in the list (match by name or domain).
Return at most 8. When finished, reply with ONLY a JSON array like
[{"name": "...", "url": "...", "why": "one sentence"}] and nothing else (an empty array if none).""".replace("__PLACE__", locality.load()["guide_place"]).replace(
    "__AREA__", locality.load()["area_text"]).replace("__CITY__", locality.load()["city_name"])


def find_additions(current: list[dict], election_name: str, client=None) -> tuple[list[dict], int, int]:
    """Return (suggestions, input_tokens, output_tokens). Uses the API's web search tool; verifies each URL loads."""
    import anthropic

    from .extract import MODEL

    client = client or anthropic.Anthropic()
    listing = "\n".join(f"- {o['name']} ({o.get('home_url') or ''})" for o in current)
    messages = [{"role": "user", "content": f"Election: {election_name}\n\nOrganizations already in the guide:\n{listing}"}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}]
    t_in = t_out = 0
    text = ""
    for _ in range(4):                                  # server-side tools can pause a turn; continue up to 3 times
        resp = client.messages.create(model=MODEL, max_tokens=8000, system=ADD_SYSTEM, tools=tools, messages=messages)
        t_in += resp.usage.input_tokens
        t_out += resp.usage.output_tokens
        text = "".join(b.text for b in resp.content if b.type == "text")
        if resp.stop_reason != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": resp.content}]
    m = re.search(r"\[.*\]", text, re.S)
    try:
        items = json.loads(m.group(0)) if m else []
    except json.JSONDecodeError:
        items = []
    have = {re.sub(r"\W+", "", o["name"]).lower() for o in current}
    out = []
    for it in items:
        if not isinstance(it, dict) or not it.get("name") or not it.get("url"):
            continue
        if re.sub(r"\W+", "", it["name"]).lower() in have:
            continue
        try:
            ok = requests.get(it["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=20).status_code == 200
        except requests.RequestException:
            ok = False
        if not ok:
            continue                       # only suggest pages that actually load
        if re.search(r"\b(centrist|moderate|business-oriented|conservative)\b", it.get("why", ""), re.I):
            continue                       # the model's own description says it is not progressive
        out.append({"name": it["name"], "url": it["url"], "why": it.get("why", ""), "link_ok": ok})
    return out, t_in, t_out


def add_rows(state: dict) -> list[list[str]]:
    return [["Add source?", s["name"], s["why"] + ("" if s.get("link_ok") else " (link did not load when checked)"), s["url"],
             state.get("generated_at", "")[:10]] for s in state.get("items", [])]


def suggestions_table(drop: list[list[str]], missing: list[list[str]], add: list[list[str]]) -> list[list[str]]:
    rows = [["Type", "Organization / contest", "Why", "Link", "Found on"]] + drop + missing + add
    if len(rows) == 1:
        rows.append(["", "No suggestions right now.", "", "", ""])
    return rows


# ---- review queue ------------------------------------------------------------------------------------------------------

def review_rows(store: dict, org_names: dict[str, str], labels: dict[str, str], election_id: str, today: date,
                sample_size: int = SAMPLE_SIZE) -> list[list[str]]:
    """Every low-confidence/flagged cell, plus a weekly-rotating random sample of the rest, with links to check."""
    active = [e for e in store.values() if e["election"] == election_id and e["status"] == "active"]

    def flagged(e):
        return e.get("confidence") == "low" or any(not f.startswith("evidence_unchecked") for f in e.get("flags") or [])

    def row(kind, e):
        val = " > ".join(e["candidates"]) if e["position"] == "candidate" else e["position"].replace("_", " ")
        return [kind, org_names.get(e["org_id"], e["org_id"]), labels.get(e["contest_key"], e["contest_key"]), val,
                e.get("evidence", ""), e.get("source_url", ""), e.get("last_seen", "")[:10],
                ", ".join(e.get("flags") or []) or e.get("confidence", "")]

    rows = [row("Check: low confidence", e) for e in active if flagged(e)]
    rest = sorted((e for e in active if not flagged(e)), key=lambda e: (e["org_id"], e["contest_key"]))
    iso = today.isocalendar()
    rng = random.Random(f"{iso[0]}-{iso[1]}")                 # same sample all week, new one next week
    rows += [row("Sample", e) for e in rng.sample(rest, min(sample_size, len(rest)))]
    return [["Why", "Organization", "Contest", "Recorded as", "Quote from source", "Source", "Last confirmed", "Flags / confidence"]] + rows
