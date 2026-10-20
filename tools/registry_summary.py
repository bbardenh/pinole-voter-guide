import collections
import sys

import yaml

p = sys.argv[1] if len(sys.argv) > 1 else "config/contests/2026-11-03.yaml"
c = yaml.safe_load(open(p, encoding="utf-8"))["contests"]
print(p, len(c), "contests")
print(" by type :", dict(collections.Counter(x["type"] for x in c)))
print(" by level:", dict(collections.Counter(x["level"] for x in c)))
print(" props   :", sorted(int(x["key"].split("-")[-1]) for x in c if x["key"].startswith("ca-prop-")))
print(" retention:", [x["key"] for x in c if x["type"] == "retention"])
print(" measures:", [x["key"] for x in c if x["type"] == "measure" and not x["key"].startswith("ca-prop-")])
