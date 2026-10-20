"""Run discovery for every org and write a coverage report to scratch/coverage.md.

Usage: python tools/coverage.py
Network only; needs no credentials.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voterguide.discover import discover  # noqa: E402


def main() -> int:
    orgs = [o for o in yaml.safe_load((ROOT / "config" / "orgs.yaml").read_text(encoding="utf-8"))["orgs"]
            if o.get("active", True)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(discover, orgs))
    by_name = {o["id"]: o["name"] for o in orgs}

    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    lines = ["# Discovery coverage", "", "| status | count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(counts.items())]
    lines += ["", "| organization | status | kind | discovered page | notes |", "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {by_name[r.org_id]} | {r.status} | {r.kind} | {r.url} | {r.notes} |")
    out = ROOT / "scratch" / "coverage.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:2 + 2 + len(counts)]))
    print(f"\nFull report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
