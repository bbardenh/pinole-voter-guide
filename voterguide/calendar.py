"""Which elections exist: rule-based statewide generals/primaries plus whatever the county Registrar lists.

Config entries in config/elections.yaml always win (for the tab name). Rules cover the next few cycles so the
tab for the next election appears at day 45 with no manual step; the county dropdown adds special elections
that mention this area (see config/locality.yaml: special_election_keywords).
"""
from __future__ import annotations

from datetime import date, timedelta

from .schedule import Election, general_election_date

MONTHS = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def _first_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def primary_election_date(year: int) -> date:
    """California statewide primary: first Tuesday in March in presidential years; first Tuesday after the
    first Monday in June in other even years."""
    if year % 4 == 0:
        return _first_weekday(year, 3, 1)
    return _first_weekday(year, 6, 0) + timedelta(days=1)


def tab_name(when: date, kind: str, label: str = "") -> str:
    if kind == "general":
        return f"{when.year} {MONTHS[when.month]} General"
    if kind == "primary":
        return f"{when.year} {MONTHS[when.month]} Primary"
    from . import locality

    city = locality.load()["city_name"]
    short = label.replace(f"City of {city} ", f"{city} ").replace("Election", "").replace("  ", " ").strip()
    return f"{when.isoformat()} {short}"[:95]


def rule_elections(today: date, years_ahead: int = 5) -> list[Election]:
    out = []
    for y in range(today.year, today.year + years_ahead + 1):
        if y % 2:
            continue
        for kind, d in (("primary", primary_election_date(y)), ("general", general_election_date(y))):
            out.append(Election(date=d, kind=kind, tab=tab_name(d, kind)))
    return out


def county_elections(keywords: list[str], today: date) -> list[Election]:
    """Future elections the county lists. Statewide generals/primaries always; others only if they mention this area."""
    from .county import list_elections

    out = []
    for e in list_elections():
        if e["date"] < today:
            continue
        name = e["name"]
        low = name.lower()
        if low in ("general election", "statewide general election", "presidential general election"):
            kind = "general"
        elif "primary" in low and ("statewide" in low or "presidential" in low or low.startswith("direct primary")):
            kind = "primary"
        elif any(k.lower() in low for k in keywords):
            kind = "special"
        else:
            continue
        out.append(Election(date=e["date"], kind=kind, tab=tab_name(e["date"], kind, name)))
    return out


def merge(config: list[Election], *others: list[Election]) -> list[Election]:
    """One election per date; config first, then later lists fill the gaps."""
    by_date: dict[date, Election] = {e.date: e for e in config}
    for lst in others:
        for e in lst:
            by_date.setdefault(e.date, e)
    return sorted(by_date.values(), key=lambda e: e.date)


def all_elections(config: list[Election], today: date, keywords: list[str], use_county: bool = True) -> list[Election]:
    county: list[Election] = []
    if use_county:
        try:
            county = county_elections(keywords, today)
        except Exception:   # county site down: rules + config still work
            county = []
    return merge(config, county, rule_elections(today))
