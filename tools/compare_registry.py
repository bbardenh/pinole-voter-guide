"""Build the 2026 registry from live official sources (no model) and diff it against the hand-built one.

Run this once (locally or in Actions) to check the Contra Costa PDF parsing against the real files."""
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voterguide.registry_builder import build  # noqa: E402

old = yaml.safe_load((ROOT / "config" / "contests" / "2026-11-03.yaml").read_text(encoding="utf-8"))["contests"]
new, warnings = build(date(2026, 11, 3), prev=old, use_model=False)
ok = {c["key"]: c for c in old}
nk = {c["key"]: c for c in new}
print("warnings:", warnings)
print(f"hand-built {len(old)} | auto-built {len(new)} (propositions excluded here: no model)")
only_old = sorted(k for k in ok if k not in nk and not k.startswith("ca-prop-"))
only_new = sorted(k for k in nk if k not in ok)
print("\nin hand-built only:", only_old)
print("in auto-built only:", only_new)
diffs = []
for k in sorted(set(ok) & set(nk)):
    a, b = ok[k], nk[k]
    if a.get("candidates", []) != b.get("candidates", []):
        diffs.append((k, "candidates", a.get("candidates"), b.get("candidates")))
    if a["level"] != b["level"] or a["type"] != b["type"]:
        diffs.append((k, "level/type", (a["level"], a["type"]), (b["level"], b["type"])))
    if a["label"] != b["label"]:
        diffs.append((k, "label", a["label"], b["label"]))
print(f"\n{len(diffs)} differences among shared keys:")
for d in diffs[:30]:
    print("  ", d)
