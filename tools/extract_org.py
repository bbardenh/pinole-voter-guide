"""Discover + extract for one or more orgs and print what was found. Costs real API money.

Usage: python tools/extract_org.py <org-id>[,<org-id>...] [--max-pages 3]
Needs ANTHROPIC_API_KEY (in CI it comes from the repo secret).
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voterguide.discover import discover  # noqa: E402
from voterguide.extract import extract  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ids = sys.argv[1].split(",")
    max_pages = int(sys.argv[sys.argv.index("--max-pages") + 1]) if "--max-pages" in sys.argv else 3
    orgs = {o["id"]: o for o in yaml.safe_load((ROOT / "config" / "orgs.yaml").read_text(encoding="utf-8"))["orgs"]}
    registry = yaml.safe_load((ROOT / "config" / "contests" / "2026-11-03.yaml").read_text(encoding="utf-8"))["contests"]
    total_in = total_out = 0
    for oid in ids:
        org = orgs[oid]
        d = discover(org)
        print(f"\n===== {org['name']} ({oid}) discovery={d.status} {d.url}")
        tried = 0
        for score, url, kind in d.candidates or [(0, org.get("home_url") or "", "html")]:
            if not url or tried >= max_pages:
                break
            tried += 1
            r = extract(org, url, registry)
            total_in += r.input_tokens
            total_out += r.output_tokens
            print(f"-- {url} [{kind}] ok={r.ok} endorsement_page={r.is_endorsement_page} "
                  f"election={r.election!r} items={len(r.items)} tokens={r.input_tokens}/{r.output_tokens} "
                  f"model={r.model} {('ERROR ' + r.error) if r.error else ''}")
            if r.note:
                print(f"   note: {r.note}")
            for it in r.items:
                who = ", ".join(it.candidates) if it.candidates else it.position
                print(f"   [{it.confidence:6}] {it.contest_key:32} {who}  {it.flags or ''}")
            if r.ok and r.is_endorsement_page and r.items:
                break
    print(f"\nTOTAL tokens in/out: {total_in}/{total_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
