"""Download official ballot documents into scratch/official/ and extract their text.

Output (all under scratch/official/, git-ignored):  <name>.pdf  and  <name>.txt
Run:  python tools/fetch_official.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from voterguide import county, locality  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "scratch" / "official"
UA = f"Mozilla/5.0 (compatible; {locality.load()['bot_name']}/0.1)"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sources = {"sos-cert-list-candidates": "https://elections.cdn.sos.ca.gov/statewide-elections/2026-general/cert-list-candidates.pdf"}
    sources.update({f"county-{kind}": url for kind, url in county.documents().items()})
    for name, url in sources.items():
        r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
        print(f"{name}: HTTP {r.status_code}, {len(r.content)} bytes")
        if r.status_code != 200:
            continue
        pdf = OUT / f"{name}.pdf"
        pdf.write_bytes(r.content)
        reader = PdfReader(str(pdf))
        text = "\n\n=====PAGE=====\n".join((p.extract_text() or "") for p in reader.pages)
        (OUT / f"{name}.txt").write_text(text, encoding="utf-8")
        print(f"  {len(reader.pages)} pages -> {name}.txt ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
