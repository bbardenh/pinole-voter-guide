"""Build the contest registry for an election from official sources, so each new cycle needs no manual work.

Sources: Contra Costa County Elections (local races and candidates, local/regional measures), California Secretary
of State (certified candidate list PDF for federal/state races and judicial retention; qualified-measures page for
statewide propositions). What counts as this guide's area is configured in config/locality.yaml. Existing registry
entries keep their richer labels and manual flags, and a source that cannot be read never shrinks the registry.
"""
from __future__ import annotations

import io
import json
import os
import re
from datetime import date
from pathlib import Path

import requests
import yaml

from . import county, locality

ROOT = Path(__file__).resolve().parent.parent
REG_DIR = ROOT / "config" / "contests"

STATEWIDE = {
    "governor": ("ca-governor", "California Governor"),
    "lieutenant governor": ("ca-lt-governor", "California Lieutenant Governor"),
    "secretary of state": ("ca-secretary-of-state", "California Secretary of State"),
    "controller": ("ca-controller", "California Controller"),
    "treasurer": ("ca-treasurer", "California Treasurer"),
    "attorney general": ("ca-attorney-general", "California Attorney General"),
    "insurance commissioner": ("ca-insurance-commissioner", "California Insurance Commissioner"),
    "superintendent of public instruction": ("ca-superintendent", "California Superintendent of Public Instruction (nonpartisan)"),
    "state superintendent of public instruction": ("ca-superintendent", "California Superintendent of Public Instruction (nonpartisan)"),
    "united states senator": ("us-senate", "U.S. Senate"),
}
PARTIES = (r"Democratic|Republican|Green|Libertarian|Peace and Freedom|American Independent|No Party Preference|"
           r"Non-?Partisan|Party Preference: None")
BAY_COUNTIES = ("Alameda", "Contra Costa", "San Francisco", "San Mateo", "Santa Clara", "Marin", "Solano", "Napa", "Sonoma")
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6}


def _ua() -> str:
    return f"Mozilla/5.0 (compatible; {locality.load()['bot_name']}/0.1)"


def registry_path(when: date) -> Path:
    return REG_DIR / f"{when.isoformat()}.yaml"


def load_registry(when: date) -> list[dict] | None:
    p = registry_path(when)
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8"))["contests"]


def _cap(part: str) -> str:
    """Capitalize the first letter even after a quote or parenthesis: '"christy"' -> '"Christy"'."""
    for i, ch in enumerate(part):
        if ch.isalpha():
            return part[:i] + ch.upper() + part[i + 1:]
    return part


def titlecase_name(name: str, known: dict[str, str] | None = None) -> str:
    """'TRUC "CHRISTY" LAM-JULIAN' -> 'Truc "Christy" Lam-Julian'; prefers a spelling we already have."""
    name = name.strip().rstrip("*").strip()
    key = re.sub(r"\W+", "", name).lower()
    if known and key in known:
        return known[key]
    out = []
    for w in name.split():
        lw = w.lower()
        bare = lw.strip(",.")
        if bare in ("ii", "iii", "iv"):
            out.append(w.upper())
        elif bare in ("jr", "sr"):
            out.append(_cap(lw))
        else:
            w2 = "-".join(_cap(p) for p in lw.split("-"))
            w2 = re.sub(r"^(Mc|O')([a-z])", lambda m: m.group(1) + m.group(2).upper(), w2)
            out.append(w2)
    return " ".join(out)


# ---- county contests ---------------------------------------------------------------------------------------------

def classify_county_contest(code: str, vote_for: int, cfg: dict) -> dict | None:
    """County contest code ('PinoleCouncil', 'EastBayMUD3', 'WestCCUSD Area4') -> registry stub, or None if it
    is not on this area's ballot."""
    code = re.sub(r"\s+", " ", code).strip()
    short = bool(re.search(r"short", code, re.I))
    city, slug = cfg["city_name"], cfg["city_slug"]
    m = re.match(rf"^{re.escape(city)}\s*(?P<office>[A-Za-z]+?)(?:\s*,?\s*(?:Dist(?:rict)?|D)\s*(?P<d>\d+))?(?:\W|short|$)",
                 code, re.I)
    if m:
        office = next((v for k, v in cfg.get("city_offices", {}).items() if k.lower() == m.group("office").lower()), None)
        if not office:
            return None
        key, label = f"{slug}-{office['key']}", f"{city} {office['label']}"
        if m.group("d"):
            key, label = f"{key}-d{m.group('d')}", f"{label} District {m.group('d')}"
        if short:
            key, label = f"{key}-short", f"{label}, Short Term"
        if vote_for > 1:
            label += f" ({vote_for} seats)"
        stub = {"key": key, "level": "local", "type": "race", "label": label}
        if vote_for > 1:
            stub["vote_for"] = vote_for
        return stub
    for d in cfg.get("district_contests", []):
        m = re.match(rf"^{d['code']}", code, re.I)
        if not m:
            continue
        n = int(m.group(1))
        includes = d.get("includes")
        if includes is not None and n not in includes:
            return None
        key, label = d["key"].format(n=n), d["label"].format(n=n)
        if short:
            key, label = f"{key}-short", label[:-1] + ", Short Term)" if label.endswith(")") else label + ", Short Term"
        stub = {"key": key, "level": d["level"], "type": "race", "label": label,
                "coverage": "unverified" if includes is None else "verified"}
        if vote_for > 1:
            stub["vote_for"] = vote_for
        return stub
    return None


def classify_measure(m: dict, cfg: dict) -> dict | None:
    """County measure {letter, title, text} -> registry stub if it is on this area's ballot, else None."""
    letter, title = m["letter"], re.sub(r"\s+", " ", m["title"]).strip()
    blob = f"{title} {m.get('text', '')}"
    city, slug = cfg["city_name"], cfg["city_slug"]
    fmt = {"l": letter.lower(), "L": letter, "title": title}
    if re.search(rf"\bCity of {re.escape(city)}\b", blob):
        return {"key": f"{slug}-measure-{letter.lower()}", "level": "local", "type": "measure",
                "label": f"City of {city} Measure {letter}, {title}"}
    for j in cfg.get("measure_jurisdictions", []):
        if re.search(j["pattern"], blob, re.I):
            return {"key": j["key"].format(**fmt), "level": j["level"], "type": "measure", "label": j["label"].format(**fmt)}
    if re.search(r"\bCity of [A-Z]", blob) or re.search(r"School District|Unified|Union High|Fire Protection|"
                                                        r"Sanitary|Water District|Recreation and Park", title, re.I):
        return None                                     # another city's or district's measure
    counties = sum(1 for c in BAY_COUNTIES if c in blob)
    if re.search(r"\bregional\b", title, re.I) or counties >= 2:
        return {"key": f"reg-measure-{letter.lower()}", "level": "regional", "type": "measure",
                "label": f"Regional Measure {letter}, {title}"}
    cname = cfg["county_name"]
    if re.search(rf"\b(County of {cname}|{cname} County)\b", blob):
        return {"key": f"county-measure-{letter.lower()}", "level": "county", "type": "measure",
                "label": f"{cname} County Measure {letter}, {title}"}
    return None


# ---- federal and state races (Secretary of State certified candidate list) ----------------------------------------

DISTRICT_OFFICES = [
    (re.compile(r"^United States Representative,? District (\d+)$", re.I), "congressional_districts", "federal",
     "us-house-d{n}", "U.S. House of Representatives (District {n})"),
    (re.compile(r"^(?:State Senator|Member of the State Senate),? District (\d+)$", re.I), "state_senate_districts", "state",
     "ca-senate-d{n}", "California State Senate (District {n})"),
    (re.compile(r"^(?:State Assembly Member|Member of the State Assembly),? District (\d+)$", re.I), "assembly_districts", "state",
     "ca-assembly-d{n}", "California State Assembly (District {n})"),
    (re.compile(r"^(?:Board of Equalization Member|Member,? State Board of Equalization),? District (\d+)$", re.I), "boe_districts",
     "state", "ca-boe-d{n}", "State Board of Equalization (District {n})"),
]
CANDIDATE = re.compile(rf"^(?P<name>[A-Z][A-Za-z.'\"()\- ]+?)\s*\*?\s+(?P<party>{PARTIES})\b")
SECTION_END = re.compile(r"^(Supreme Court|Court of Appeal|Shall |Superior Court|Page \d+ of \d+$)", re.I)


def office_for(line: str, cfg: dict) -> tuple[str, dict | None] | None:
    """Office header -> (marker, stub-or-None). None if the line is not an office header; stub None if it is an office
    outside this area (its candidates are skipped)."""
    low = line.lower()
    if low in STATEWIDE:
        key, label = STATEWIDE[low]
        return low, {"key": key, "level": "federal" if key.startswith("us-") else "state", "type": "race", "label": label}
    for pat, cfg_key, level, key, label in DISTRICT_OFFICES:
        m = pat.match(line)
        if m:
            n = int(m.group(1))
            return line, ({"key": key.format(n=n), "level": level, "type": "race", "label": label.format(n=n)}
                          if n in cfg[cfg_key] else None)
    return None


def candidates_from_cert_text(text: str, cfg: dict) -> list[dict]:
    """Federal/state races for this area with their certified candidates, from the SOS certified list text."""
    out: dict[str, dict] = {}
    cur = None
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        hit = office_for(line, cfg)
        if hit:
            cur = hit[1]
            if cur:
                cur = out.setdefault(cur["key"], {**cur, "candidates": []})
            continue
        if SECTION_END.match(line):
            cur = None
            continue
        m = CANDIDATE.match(line)
        if m and cur is not None:
            name = titlecase_name(m.group("name")) if m.group("name").isupper() else m.group("name").strip()
            if name not in cur["candidates"]:
                cur["candidates"].append(name)
    return [c for c in out.values() if 0 < len(c["candidates"]) <= 6]


def sos_cert_text(when: date) -> str:
    from pypdf import PdfReader

    kind = "general" if when.month == 11 else "primary"
    url = f"https://elections.cdn.sos.ca.gov/statewide-elections/{when.year}-{kind}/cert-list-candidates.pdf"
    r = requests.get(url, headers={"User-Agent": _ua()}, timeout=120)
    if r.status_code != 200:
        return ""
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages)


# ---- state propositions & judicial retention (Secretary of State) ------------------------------------------------

def sos_propositions(when: date, client=None) -> list[dict]:
    """Statewide propositions for this election date, read from the SOS qualified-measures page by the model."""
    import anthropic

    from .extract import MODEL, html_to_text

    r = requests.get("https://www.sos.ca.gov/elections/ballot-measures/qualified-ballot-measures", headers={"User-Agent": _ua()},
                     timeout=60)
    r.raise_for_status()
    text = html_to_text(r.text)
    client = client or anthropic.Anthropic()
    schema = {"type": "object", "additionalProperties": False, "required": ["measures"], "properties": {"measures": {
        "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["number", "title"],
                                    "properties": {"number": {"type": "integer"}, "title": {"type": "string"}}}}}}
    resp = client.messages.create(
        model=MODEL, max_tokens=4000,
        system="Extract statewide ballot measures exactly as the page words them. Only measures that are on the ballot for the "
               "stated election date and have been assigned a proposition number. Join multi-part official titles with '; '.",
        messages=[{"role": "user", "content": f"Election date: {when.strftime('%B %-d, %Y') if os.name != 'nt' else when.strftime('%B %d, %Y')}\n\n{text[:60000]}"}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}})
    data = json.loads(next(b.text for b in resp.content if b.type == "text"))
    return sorted(data["measures"], key=lambda x: x["number"])


def retention_from_cert_text(text: str, appellate_district: str = "First") -> list[dict]:
    """Parse 'Shall Associate Justice X be elected...' entries for the Supreme Court and the given appellate district."""
    text = re.sub(r"[ \t]+", " ", text)
    num = ORDINALS.get(appellate_district.lower(), 1)
    nth = {1: "1st", 2: "2nd", 3: "3rd"}.get(num, f"{num}th")
    out = []
    sc = re.search(r"Supreme Court - For all 58 Counties(.*?)(?=Court of Appeal)", text, re.S)
    for m in re.finditer(r"Shall (Associate Justice|Chief Justice) of the Supreme Court ([A-Z][A-Z .'\-]+?) be elected", sc.group(1) if sc else "", re.S):
        out.append(("Supreme Court", m.group(1), m.group(2), None))
    # Entries for other districts can be interleaved at page breaks; keep only those naming this district.
    for m in re.finditer(r"For (Associate Justice|Presiding Justice), Court of Appeal, (\w+) District, Division (\w+)\s+Shall (?:Associate|Presiding) Justice ([A-Z][A-Z .'\-]+?) be elected", text, re.S):
        if m.group(2).lower() == appellate_district.lower():
            out.append(("Court of Appeal", m.group(1), m.group(4), m.group(3)))
    entries = []
    for court, title, name, division in out:
        n = titlecase_name(name.strip())
        last = re.sub(r"[^a-z]", "", n.split()[-1].lower())
        if court == "Supreme Court":
            entries.append({"key": f"ca-supreme-{last}", "level": "state", "type": "retention",
                            "label": f"Retain {title} of the Supreme Court {n}?"})
        else:
            div = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}.get(division, division)
            entries.append({"key": f"ca-coa{num}-d{div}-{last}", "level": "state", "type": "retention",
                            "label": f"Retain {title} {n} (Court of Appeal, {nth} District, Div. {div})?"})
    return entries


# ---- assemble ------------------------------------------------------------------------------------------------------

def _carry_over(contests: dict, prev: list[dict], pred, what: str, warnings: list[str]) -> None:
    """An official source that yielded nothing must never silently shrink the registry: keep what we had."""
    if any(pred(c) for c in contests.values()):
        return
    kept = [c for c in prev if pred(c)]
    for c in kept:
        contests[c["key"]] = c
    if kept:
        warnings.append(f"kept {len(kept)} previous {what} entries")


def build(when: date, prev: list[dict] | None = None, cfg: dict | None = None, use_model: bool = True) -> tuple[list[dict], list[str]]:
    """Return (contests, warnings). `prev` supplies preferred labels/candidate spellings and manual flags."""
    cfg = cfg or locality.load()
    prev = prev or []
    prev_by_key = {c["key"]: c for c in prev}
    known_names = {re.sub(r"\W+", "", n).lower(): n for c in prev for n in c.get("candidates", [])}
    warnings: list[str] = []
    contests: dict[str, dict] = {}

    docs = county.documents()
    if "candidates" not in docs:
        raise RuntimeError("the county has not posted a candidate list yet")
    uncontested = []
    for race in county.candidate_contests(docs["candidates"], when):      # raises if the list is for another election
        stub = classify_county_contest(race["code"], race["vote_for"], cfg)
        if stub and len(race["candidates"]) <= race["vote_for"]:
            uncontested.append(stub["label"])     # local seats with no contest are filled by appointment, not on the ballot
            continue
        if stub:
            stub["candidates"] = [titlecase_name(n, known_names) for n in race["candidates"]]
            stub["verification"] = "official"
            contests[stub["key"]] = stub
    if uncontested:
        warnings.append("left out as uncontested (usually appointed in lieu of election): " + "; ".join(uncontested))
    try:
        local_measures = county.measures(docs["measures"], when) if "measures" in docs else []
    except Exception as e:   # noqa: BLE001
        local_measures = []
        warnings.append(f"county measures list could not be read: {e}")
    for m in local_measures:
        stub = classify_measure(m, cfg)
        if stub:
            stub["verification"] = "official"
            contests[stub["key"]] = stub

    cert = ""
    try:
        cert = sos_cert_text(when)
    except Exception as e:   # noqa: BLE001
        warnings.append(f"state certified candidate list could not be read: {e}")
    for c in candidates_from_cert_text(cert, cfg):
        c["candidates"] = [known_names.get(re.sub(r"\W+", "", n).lower(), n) for n in c["candidates"]]
        c["verification"] = "official"
        contests[c["key"]] = c
    if cert and when.month == 11 and when.year % 2 == 0:              # retention appears on November general ballots
        for r in retention_from_cert_text(cert, cfg.get("appellate_district", "First")):
            r["verification"] = "official"
            contests[r["key"]] = r

    if use_model:
        try:
            for p in sos_propositions(when):
                contests[f"ca-prop-{p['number']}"] = {"key": f"ca-prop-{p['number']}", "level": "state", "type": "measure",
                                                       "label": f"CA Proposition {p['number']}, {p['title']}", "verification": "official"}
        except Exception as e:   # noqa: BLE001
            warnings.append(f"state propositions could not be read: {e}")

    _carry_over(contests, prev, lambda c: c["type"] == "race" and c["level"] in ("local", "county", "special_district"),
                "local race", warnings)
    _carry_over(contests, prev, lambda c: c["type"] == "measure" and c["level"] != "state", "local measure", warnings)
    _carry_over(contests, prev, lambda c: c["type"] == "race" and c["level"] in ("federal", "state"), "federal/state race", warnings)
    _carry_over(contests, prev, lambda c: c["type"] == "retention", "judicial retention", warnings)
    _carry_over(contests, prev, lambda c: c["key"].startswith("ca-prop-"), "proposition", warnings)

    # merge with previous: keep richer labels and manual flags
    for key, c in contests.items():
        p = prev_by_key.get(key)
        if p:
            if p.get("label") and c["type"] == "measure" and c["level"] != "state":
                c["label"] = p["label"]
            for flag in ("coverage", "candidates_flag", "rcv", "vote_for"):
                if flag in p:
                    c.setdefault(flag, p[flag])
    order = {"federal": 0, "state": 1, "regional": 2, "county": 3, "local": 4, "special_district": 5}
    ordered = sorted(contests.values(), key=lambda c: (order.get(c["level"], 9), c["type"] != "measure", c["key"]))
    return ordered, warnings


def save(when: date, contests: list[dict], election_name: str) -> Path:
    REG_DIR.mkdir(parents=True, exist_ok=True)
    p = registry_path(when)
    lines = [f"# Contest registry for {election_name} ({when.isoformat()}), AUTO-GENERATED from official sources by",
             f"# voterguide/registry_builder.py ({locality.load()['county_name']} County Elections + California Secretary of State).",
             "# Edit flags freely; a rebuild keeps labels/flags for existing keys.", f'election: "{election_name}"', "contests:"]
    for c in contests:
        lines.append("  - {" + ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in c.items()) + "}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p
