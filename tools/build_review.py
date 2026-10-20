"""Merge extraction runs into a review matrix (contest x organization) as CSV for Excel.

Usage: python tools/build_review.py scratch/run1/extractions.json scratch/run2/extractions.json ...
Later files win for an org when they extracted something. Writes out/review-matrix.csv, out/review-status.csv,
out/consolidated.json. Cells: Yes/No/..., candidate lists as "A > B", a trailing "?" marks low confidence.
"""
import csv
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
orgs = [o for o in yaml.safe_load((ROOT / "config" / "orgs.yaml").read_text(encoding="utf-8"))["orgs"]
        if o.get("active", True)]
registry = yaml.safe_load((ROOT / "config" / "contests" / "2026-11-03.yaml").read_text(encoding="utf-8"))["contests"]

best: dict[str, dict] = {}
for path in sys.argv[1:]:
    for r in json.load(open(path, encoding="utf-8"))["results"]:
        if r["chosen"] or r["org_id"] not in best:
            best[r["org_id"]] = r

POS = {"yes": "Yes", "no": "No", "neutral": "Neutral", "no_position": "No position", "no_endorsement": "No endorsement"}
cells: dict[tuple[str, str], str] = {}
for oid, r in best.items():
    if not r["chosen"]:
        continue
    page = next(p for p in r["pages"] if p["url"] == r["chosen"])
    for it in page["items"]:
        if it["contest_key"] == "unlisted":
            continue
        text = " > ".join(it["candidates"]) if it["position"] == "candidate" else POS[it["position"]]
        if it["confidence"] == "low" or it["flags"]:
            text += " ?"
        cells[(it["contest_key"], oid)] = text

out = ROOT / "out"
out.mkdir(exist_ok=True)
with open(out / "review-matrix.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["Level", "Contest"] + [o["name"] for o in orgs])
    for c in registry:
        row = [c["level"], c["label"]] + [cells.get((c["key"], o["id"]), "") for o in orgs]
        if any(row[2:]):
            w.writerow(row)
with open(out / "review-status.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["Organization", "Extracted", "Items", "Page used", "Why not (if none)"])
    for o in orgs:
        r = best.get(o["id"])
        if r and r["chosen"]:
            page = next(p for p in r["pages"] if p["url"] == r["chosen"])
            w.writerow([o["name"], "yes", len(page["items"]), r["chosen"], ""])
        else:
            why = ""
            if r and r["pages"]:
                last = r["pages"][-1]
                why = (last["error"] or last["note"])[:200]
            w.writerow([o["name"], "no", 0, "", why or (r["discovery"]["status"] if r else "not run")])
(out / "consolidated.json").write_text(json.dumps(best, indent=1), encoding="utf-8")
n = sum(1 for r in best.values() if r["chosen"])
print(f"{n}/{len(orgs)} orgs extracted; {len(cells)} endorsement cells; rows with data: "
      f"{sum(1 for c in registry if any((c['key'], o['id']) in cells for o in orgs))}/{len(registry)} contests")
