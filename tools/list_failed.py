"""Print the orgs with no extraction: home link, best page the pipeline looked at, and why it failed."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
orgs = yaml.safe_load((ROOT / "config" / "orgs.yaml").read_text(encoding="utf-8"))["orgs"]
best = json.loads((ROOT / "out" / "consolidated.json").read_text(encoding="utf-8"))
rows = []
for o in orgs:
    r = best.get(o["id"])
    if r and r["chosen"]:
        continue
    pages = r["pages"] if r else []
    last = pages[-1] if pages else None
    why = ((last["error"] or last["note"]) if last else (r["discovery"]["status"] if r else "not run"))
    rows.append((o["name"], o.get("home_url") or "(none)", last["url"] if last else "", why.replace("\n", " ")[:170]))
print(len(rows), "organizations without an extraction\n")
for i, (name, home, last, why) in enumerate(rows, 1):
    print(f"{i}. {name}\n   Link in your sheet: {home}")
    if last and last != home:
        print(f"   Last page checked:  {last}")
    print(f"   Why: {why}\n")
