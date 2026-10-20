"""Per-org detail of an extractions.json: pages tried, outcome, navigator picks."""
import json
import sys

d = json.load(open(sys.argv[1], encoding="utf-8"))
for r in d["results"]:
    nav = r.get("navigator")
    print(f"\n## {r['name']}  chosen={'YES' if r['chosen'] else 'no'}  discovery={r['discovery']['status']}")
    for p in r["pages"]:
        tail = p["error"] or p["note"]
        print(f"   [{p.get('source','?'):9}] ok={p['ok']} end={p['is_endorsement_page']} items={len(p['items'])} "
              f"tok={p['input_tokens']} {p['url'][:95]}")
        if not r["chosen"] and tail:
            print(f"       -> {tail[:150]}")
    if nav:
        print(f"   navigator: {len(nav['urls'])} urls; {nav['reason'][:140]}")
