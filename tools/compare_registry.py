"""Build the 2026 registry from live official sources (no model) and diff it against the hand-built one.

Run this once (locally or in Actions) to check the Contra Costa PDF parsing against the real files."""
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voterguide import county, locality  # noqa: E402
from voterguide.registry_builder import build, classify_county_contest  # noqa: E402

# Diagnostics: what the county candidate PDF looks like to the parser.
docs = county.documents()
print("county documents:", docs)
if "candidates" in docs:
    text = county.pdf_text(docs["candidates"])
    lines = [ln for ln in text.splitlines() if ln.strip()]
    print(f"\n--- candidate PDF: {len(lines)} lines; first 40 ---")
    print("\n".join(repr(ln) for ln in lines[:40]))
    print("--- lines mentioning the city ---")
    city = locality.load()["city_name"].lower()
    for i, ln in enumerate(lines):
        if city in ln.lower():
            print("\n".join(repr(x) for x in lines[max(0, i - 2):i + 8]))
            break
    parsed = county.parse_candidate_list(text)
    print(f"--- parsed {len(parsed)} contests ---")
    for r in parsed:
        stub = classify_county_contest(r["code"], r["vote_for"], locality.load())
        print(f"  {r['code']!r:40} vote_for={r['vote_for']} cands={len(r['candidates'])} -> {stub['key'] if stub else None}")
    print()

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
