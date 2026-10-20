"""Build the voter-guide grid (rows of cells) from registry + stored endorsements. No Google API here."""
from __future__ import annotations

from collections import Counter

from . import locality

POS_TEXT = {"yes": "Yes", "no": "No", "neutral": "Neutral", "no_position": "No position", "no_endorsement": "No endorsement"}


def sections() -> list:
    """(section title, predicate on contest), in sheet order."""
    city = locality.load()["city_name"].upper()
    return [
        (f"LOCAL PROPOSITIONS ({city} & SCHOOL DISTRICT)", lambda c: c["level"] == "local" and c["type"] == "measure"),
        ("COUNTY & REGIONAL PROPOSITIONS", lambda c: c["level"] in ("county", "regional") and c["type"] == "measure"),
        ("STATE PROPOSITIONS", lambda c: c["level"] == "state" and c["type"] == "measure"),
        (f"LOCAL RACES ({city} CITY & SCHOOL BOARD)", lambda c: c["level"] == "local" and c["type"] == "race"),
        ("SPECIAL DISTRICT RACES & MEASURES (TRANSIT, WATER, PARKS, COLLEGE)", lambda c: c["level"] == "special_district"),
        ("COUNTY RACES", lambda c: c["level"] == "county" and c["type"] == "race"),
        ("STATE RACES", lambda c: c["level"] == "state" and c["type"] == "race"),
        ("JUDICIAL RETENTION (YES = RETAIN THE JUSTICE)", lambda c: c["type"] == "retention"),
        ("FEDERAL RACES", lambda c: c["level"] == "federal"),
    ]


C_HEADER = (0.80, 0.86, 0.93)
C_SECTION = (0.90, 0.90, 0.90)
C_LOW = (1.0, 0.93, 0.80)       # low-confidence cell


def cell_text(e: dict) -> str:
    if e["position"] == "candidate":
        names = e["candidates"]
        text = names[0] if len(names) == 1 else "\n".join(f"{i}. {n}" for i, n in enumerate(names, 1))
    else:
        text = POS_TEXT.get(e["position"], e["position"])
    if e.get("confidence") == "low" or e.get("flags") and not all(f.startswith("evidence_unchecked") for f in e["flags"]):
        text += " ?"
    return text


def suggested_vote(contest: dict, entries: list[dict]) -> tuple[str, str]:
    """(cell text, tally note) by rule: measures/retention = majority Yes vs No; races = plurality of first choices."""
    if not entries:
        return "", ""
    if contest["type"] in ("measure", "retention"):
        c = Counter(e["position"] for e in entries)
        yes, no = c["yes"], c["no"]
        tally = ", ".join(f"{n} {POS_TEXT[p]}" for p, n in c.most_common() if p in POS_TEXT)
        if yes == no == 0:
            return "", tally
        if yes == no:
            return f"Split ({yes}-{no})", tally
        return ("Yes" if yes > no else "No"), tally
    seats = int(contest.get("vote_for") or 1)
    if seats > 1:
        return _multi_seat_vote(entries, seats)
    firsts = Counter(e["candidates"][0] for e in entries if e["position"] == "candidate" and e["candidates"])
    if not firsts:
        return "", ""
    tally = ", ".join(f"{n} {name}" for name, n in firsts.most_common())
    top = firsts.most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        tied = [name for name, n in top if n == top[0][1]]
        return "Split: " + " / ".join(tied), tally
    return top[0][0], tally


def _multi_seat_vote(entries: list[dict], seats: int) -> tuple[str, str]:
    """Vote-for-N races: the N candidates endorsed by the most organizations (each org's first N picks count)."""
    counts = Counter(n for e in entries if e["position"] == "candidate" for n in e["candidates"][:seats])
    if not counts:
        return "", ""
    tally = ", ".join(f"{n} {name}" for name, n in counts.most_common())
    ranked = counts.most_common()
    if len(ranked) <= seats:
        return "\n".join(name for name, _ in ranked), tally
    cutoff = ranked[seats - 1][1]
    sure = [name for name, n in ranked if n > cutoff]
    tied = [name for name, n in ranked if n == cutoff]
    if len(sure) + len(tied) == seats:
        return "\n".join(sure + tied), tally
    return "\n".join(sure + [f"Split for {seats - len(sure)} more: " + " / ".join(tied)]), tally


def show_contest(contest: dict, n_entries: int) -> bool:
    """Special-district seats are shown only if they cover this area or some organization has endorsed there."""
    if contest["level"] == "special_district" and contest["type"] == "race" and contest.get("coverage") != "verified":
        return n_entries > 0
    return True


def build_grid(orgs: list[dict], registry: list[dict], endorsements: dict, election: str, title: str,
               updated: str) -> list[list[dict]]:
    """Rows of cell dicts: {v, formula, note, bg, bold}. Row 0 is the header."""
    by_contest: dict[str, dict[str, dict]] = {}
    for e in endorsements.values():
        if e["election"] == election and e["status"] == "active":
            by_contest.setdefault(e["contest_key"], {})[e["org_id"]] = e

    def cell(v="", formula=False, note="", bg=None, bold=False):
        return {"v": v, "formula": formula, "note": note, "bg": bg, "bold": bold}

    header = [cell(f"{title}\nUpdated automatically {updated}. Blank = no published position found; ? = low confidence; "
                   "hover a cell for its source.", bg=C_HEADER, bold=True),
              cell("Suggested Vote", bg=C_HEADER, bold=True)]
    for o in orgs:
        url = (o.get("home_url") or "").replace('"', "")
        name = o["name"].replace('"', '""')
        header.append(cell(f'=HYPERLINK("{url}","{name}")' if url else o["name"], formula=bool(url), bg=C_HEADER, bold=True))
    rows = [header]
    width = len(header)

    for sec_title, pred in sections():
        contests = [c for c in registry if pred(c) and show_contest(c, len(by_contest.get(c["key"], {})))]
        if not contests:
            continue
        rows.append([cell(sec_title, bg=C_SECTION, bold=True)] + [cell(bg=C_SECTION) for _ in range(width - 1)])
        for c in contests:
            ents = by_contest.get(c["key"], {})
            sv, tally = suggested_vote(c, list(ents.values()))
            row = [cell(c["label"], bold=False), cell(sv, note=tally, bold=True)]
            for o in orgs:
                e = ents.get(o["id"])
                if not e:
                    row.append(cell())
                    continue
                note = f"Source: {e['source_url']}\nLast confirmed: {e['last_seen'][:10]}"
                if e.get("evidence"):
                    note += f"\nQuote: \"{e['evidence']}\""
                low = e.get("confidence") == "low" or any(not f.startswith("evidence_unchecked") for f in e.get("flags") or [])
                row.append(cell(cell_text(e), note=note, bg=C_LOW if low else None))
            rows.append(row)
    return rows
