"""Decides what a scheduled run should do. One daily trigger calls this.

Nothing runs until 45 days before an election. From day 45 to day 31 the pipeline runs weekly
(Mondays); from day 30 through election day it runs daily; after the election it stops.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

ACTIVE_WINDOW_DAYS = 45    # nothing runs (and no tab is created) before this
DAILY_WINDOW_DAYS = 30     # daily runs from here through election day
WEEKLY_WEEKDAY = 0         # Monday


@dataclass(frozen=True)
class Election:
    date: date
    kind: str
    tab: str


def general_election_date(year: int) -> date:
    """First Tuesday after the first Monday in November."""
    d = date(year, 11, 1)
    first_monday = d + timedelta(days=(0 - d.weekday()) % 7)
    return first_monday + timedelta(days=1)


def run_mode(today: date, elections: list[Election]) -> str:
    """'daily' within 30 days of an election (election day included), 'weekly' on Mondays 31-45 days out,
    otherwise 'skip'."""
    days = [(e.date - today).days for e in elections if (e.date - today).days >= 0]
    if not days:
        return "skip"
    nearest = min(days)
    if nearest <= DAILY_WINDOW_DAYS:
        return "daily"
    if nearest <= ACTIVE_WINDOW_DAYS and today.weekday() == WEEKLY_WEEKDAY:
        return "weekly"
    return "skip"


def tabs_to_create(today: date, elections: list[Election], existing_tabs: set[str]) -> list[Election]:
    """Elections inside the 45-day active window (and not yet held) that have no tab yet."""
    return [
        e for e in elections
        if e.tab not in existing_tabs and 0 <= (e.date - today).days <= ACTIVE_WINDOW_DAYS
    ]
