"""Discover + extract for every org; write out/extractions.json and print a summary table.

Usage: python tools/extract_all.py [--workers 4] [--max-pages 3] [--only id1,id2]
Needs ANTHROPIC_API_KEY. Costs real money (see the printed total).
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voterguide.discover import discover  # noqa: E402
from voterguide.extract import MODEL, extract  # noqa: E402
from voterguide.navigate import choose_links, pages_for as navigate_pages  # noqa: E402

PRICE_IN, PRICE_OUT = 4.00, 20.00   # claude-opus-5-5, $ per 1M tokens


def arg(name: str, default: str) -> str:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def process(org: dict, registry: list[dict], max_pages: int) -> dict:
    d = discover(org)
    rec = {"org_id": org["id"], "name": org["name"], "discovery": {
        "status": d.status, "url": d.url, "kind": d.kind, "score": d.score, "notes": d.notes},
        "pages": [], "chosen": None}
    cands = d.candidates or ([(0, org["home_url"], "html")] if org.get("home_url") else [])
    if org.get("hint_url"):   # owner-supplied page: try it first
        cands = [(99, org["hint_url"], "html")] + [c for c in cands if c[1] != org["hint_url"]]
    tried: set[str] = set()

    def attempt(url: str, source: str) -> bool:
        tried.add(url)
        r = extract(org, url, registry)
        page = asdict(r)
        page["source"] = source
        rec["pages"].append(page)
        if r.ok and r.is_endorsement_page and r.items:
            rec["chosen"] = url
            return True
        return False

    for _, url, _kind in cands[:max_pages]:
        if attempt(url, "rules"):
            return rec
    # Rules did not land on an endorsement page: let the model pick from the links on the site.
    if org.get("home_url"):
        urls, reason, t_in, t_out = choose_links(org, navigate_pages(org), exclude=tried)
        rec["navigator"] = {"urls": urls, "reason": reason, "input_tokens": t_in, "output_tokens": t_out}
        for url in urls[:max_pages]:
            if attempt(url, "navigator"):
                return rec
        # Second hop: a page that says it links to the 2026 endorsements (but lists none) is worth following.
        hop_pages = [p["url"] for p in rec["pages"]
                     if not p["items"] and re.search(r"2026", p["note"]) and re.search(r"endors|voter guide|recommend", p["note"], re.I)
                     and re.search(r"link", p["note"], re.I)][:2]
        if hop_pages:
            urls2, reason2, t_in2, t_out2 = choose_links(org, hop_pages, exclude=tried)
            rec["navigator"]["hop"] = {"from": hop_pages, "urls": urls2, "reason": reason2}
            rec["navigator"]["input_tokens"] += t_in2
            rec["navigator"]["output_tokens"] += t_out2
            for url in urls2[:2]:
                if attempt(url, "hop"):
                    return rec
    return rec


def main() -> int:
    workers, max_pages = int(arg("--workers", "4")), int(arg("--max-pages", "3"))
    only = set(arg("--only", "").split(",")) - {""}
    orgs = yaml.safe_load((ROOT / "config" / "orgs.yaml").read_text(encoding="utf-8"))["orgs"]
    orgs = [o for o in orgs if o.get("active", True)]
    if only:
        orgs = [o for o in orgs if o["id"] in only]
    registry = yaml.safe_load((ROOT / "config" / "contests" / "2026-11-03.yaml").read_text(encoding="utf-8"))["contests"]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda o: process(o, registry, max_pages), orgs))

    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "extractions.json").write_text(json.dumps(
        {"run_at": datetime.now(timezone.utc).isoformat(), "model": MODEL, "results": results}, indent=1), encoding="utf-8")

    t_in = sum(p["input_tokens"] for r in results for p in r["pages"]) + sum(r.get("navigator", {}).get("input_tokens", 0) for r in results)
    t_out = sum(p["output_tokens"] for r in results for p in r["pages"]) + sum(r.get("navigator", {}).get("output_tokens", 0) for r in results)
    lines = ["| organization | result | items (hi/med/low) | flagged | page |", "|---|---|---|---|---|"]
    n_ok = 0
    for r in results:
        chosen = next((p for p in r["pages"] if p["url"] == r["chosen"]), None)
        if chosen:
            n_ok += 1
            its = chosen["items"]
            c = {k: sum(1 for i in its if i["confidence"] == k) for k in ("high", "medium", "low")}
            flagged = sum(1 for i in its if i["flags"])
            lines.append(f"| {r['name']} | OK | {len(its)} ({c['high']}/{c['medium']}/{c['low']}) | {flagged} | {r['chosen']} |")
        else:
            why = (r["pages"][-1]["error"] or r["pages"][-1]["note"] or "no endorsement page") if r["pages"] else r["discovery"]["status"]
            lines.append(f"| {r['name']} | none ({r['discovery']['status']}) | 0 | 0 | {why[:90]} |")
    cost = t_in / 1e6 * PRICE_IN + t_out / 1e6 * PRICE_OUT
    lines += ["", f"orgs with endorsements extracted: {n_ok}/{len(results)}",
              f"tokens in/out: {t_in:,}/{t_out:,}  ->  approx ${cost:.2f} at {MODEL} list prices"]
    print("\n".join(lines))
    summary = Path(__import__("os").environ.get("GITHUB_STEP_SUMMARY", out / "summary.md"))
    with open(summary, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
