"""Summarize an extractions.json: totals, cost, contest coverage, unlisted contests, flags."""
import collections
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "scratch/run1/extractions.json"
data = json.load(open(path, encoding="utf-8"))
res = data["results"]
ok = [r for r in res if r["chosen"]]
t_in = sum(p["input_tokens"] for r in res for p in r["pages"])
t_out = sum(p["output_tokens"] for r in res for p in r["pages"])
print(f"model={data['model']} orgs={len(res)} extracted={len(ok)} pages_tried={sum(len(r['pages']) for r in res)}")
print(f"tokens in/out {t_in:,}/{t_out:,}  ~${t_in/1e6*4 + t_out/1e6*20:.2f}")
errs = collections.Counter(p["error"][:40] for r in res for p in r["pages"] if p["error"])
print("errors:", dict(errs))

by_contest = collections.defaultdict(list)
unlisted = collections.Counter()
flags = collections.Counter()
for r in ok:
    page = next(p for p in r["pages"] if p["url"] == r["chosen"])
    for it in page["items"]:
        if it["contest_key"] == "unlisted":
            unlisted[it["contest_label"]] += 1
        else:
            by_contest[it["contest_key"]].append(r["name"])
        for f in it["flags"]:
            flags[f] += 1
print("\nflags:", dict(flags))
print("\nmost-covered contests:")
for k, v in sorted(by_contest.items(), key=lambda kv: -len(kv[1]))[:60]:
    print(f"  {len(v):2}  {k}")
print("\nregistry contests with zero endorsements:")
import yaml
reg = [c["key"] for c in yaml.safe_load(open("config/contests/2026-11-03.yaml", encoding="utf-8"))["contests"]]
print("  ", [k for k in reg if k not in by_contest])
print("\nunlisted contests (reported by orgs, not in registry):")
for k, v in unlisted.most_common(40):
    print(f"  {v:2}  {k}")
