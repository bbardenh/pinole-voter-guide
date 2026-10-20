"""Print the voter-guide grid from saved state as text: contest | suggested vote | how many orgs."""
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voterguide.grid import build_grid  # noqa: E402

store = json.loads((ROOT / "state" / "2026-11-03" / "endorsements.json").read_text(encoding="utf-8"))
orgs = [o for o in yaml.safe_load((ROOT / "config" / "orgs.yaml").read_text(encoding="utf-8"))["orgs"] if o.get("active", True)]
reg = yaml.safe_load((ROOT / "config" / "contests" / "2026-11-03.yaml").read_text(encoding="utf-8"))["contests"]
g = build_grid(orgs, reg, store, "2026-11-03", "T", "d")
active = [e for e in store.values() if e["status"] == "active"]
low = [e for e in active if e["confidence"] == "low" or any(not f.startswith("evidence_unchecked") for f in e["flags"])]
print(f"grid {len(g)} rows x {len(g[0])} cols; {len(active)} active endorsements, {len(low)} low-confidence/flagged\n")
for r in g[1:]:
    v = [c["v"] for c in r]
    n = sum(1 for x in v[2:] if x)
    if not v[1] and not n and v[0].isupper():
        print(f"\n== {v[0]}")
    else:
        print(f"  {v[0][:70]:70} | {v[1][:24]:24} | {n:2}")
