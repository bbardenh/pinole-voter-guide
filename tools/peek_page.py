"""Diagnostic: how does a page look to the pipeline? Prints text length, image candidates, and render result."""
import sys

sys.path.insert(0, ".")
import requests

from voterguide.extract import find_images, html_to_text
from voterguide.render import render_html

for url in sys.argv[1:]:
    print("=====", url)
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30, allow_redirects=True)
    print("plain:", r.status_code, r.url, len(r.text), "chars html;", len(html_to_text(r.text)), "chars text")
    print("  img candidates:", find_images(r.text, r.url)[:8])
    print("  <img> tags:", r.text.count("<img"), " background-image:", r.text.count("background-image"), " iframe:", r.text.count("<iframe"))
    rr = render_html(url)
    if rr is None:
        print("rendered: None (playwright missing/failed)")
    else:
        print("rendered:", rr[0], rr[1], len(rr[2]), "chars html;", len(html_to_text(rr[2])), "chars text")
        print("  img candidates:", find_images(rr[2], rr[1])[:8])
    print("  text sample:", html_to_text(r.text)[:300].replace("\n", " | "))
