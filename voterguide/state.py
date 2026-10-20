"""JSON state kept in the repo (state/), committed back by the workflow so runs are stateless.

Per-election files (sources, endorsements, extractions) live in state/<election-date>/ so a new cycle never reuses
a previous cycle's cached results. Global files (budget, suggestions, changelog) live in state/.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent / "state"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dir(sub: str) -> Path:
    return STATE_DIR / sub if sub else STATE_DIR


def load(name: str, default, sub: str = ""):
    p = _dir(sub) / name
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def save(name: str, data, sub: str = "") -> None:
    d = _dir(sub)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def append_events(events: list[dict]) -> None:
    """changelog.jsonl: one JSON object per line, append-only."""
    if not events:
        return
    STATE_DIR.mkdir(exist_ok=True)
    with open(STATE_DIR / "changelog.jsonl", "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")


def read_events() -> list[dict]:
    p = STATE_DIR / "changelog.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
