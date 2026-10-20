"""Compare a fresh extraction with stored endorsements and decide what changed.

Removal rule: an endorsement is removed only after it has been absent from MISS_RUNS consecutive *fresh,
successful* extractions of that organization's endorsements page AND at least MISS_DAYS days have passed since
it was first missed. A failed fetch, a page that no longer looks like an endorsement page, or a cached
(unchanged-page) run never counts as a miss.
"""
from __future__ import annotations

from datetime import datetime

MISS_RUNS = 3
MISS_DAYS = 7


def _ts(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def key_for(election: str, org_id: str, contest_key: str) -> str:
    return f"{election}|{org_id}|{contest_key}"


def value_of(item: dict) -> dict:
    return {"position": item["position"], "candidates": list(item.get("candidates") or [])}


def reconcile(election: str, org_id: str, items: list[dict], store: dict, now: datetime,
              fresh: bool, source_url: str = "") -> list[dict]:
    """Update `store` (endorsements dict) in place; return change-log events.

    items: extraction items (contest_key, position, candidates, evidence, confidence, flags).
    fresh: True only when `items` came from a new, successful extraction of an endorsement page.
    """
    events: list[dict] = []
    ts = _ts(now)
    seen: set[str] = set()

    for it in items:
        if it["contest_key"] == "unlisted":
            continue
        k = key_for(election, org_id, it["contest_key"])
        seen.add(k)
        new_val = value_of(it)
        meta = {"confidence": it.get("confidence", ""), "flags": list(it.get("flags") or []),
                "evidence": it.get("evidence", ""), "source_url": source_url}
        cur = store.get(k)
        if cur is None or cur["status"] == "removed":
            store[k] = {"election": election, "org_id": org_id, "contest_key": it["contest_key"], **new_val, **meta,
                        "status": "active", "first_seen": ts, "last_seen": ts, "missing_runs": 0, "first_missing": None}
            events.append({"ts": ts, "election": election, "org_id": org_id, "contest_key": it["contest_key"],
                           "type": "added" if cur is None else "re-added", "old": None, "new": new_val, "source_url": source_url})
        else:
            if value_of(cur) != new_val:
                events.append({"ts": ts, "election": election, "org_id": org_id, "contest_key": it["contest_key"],
                               "type": "changed", "old": value_of(cur), "new": new_val, "source_url": source_url})
            cur.update(new_val)
            cur.update(meta)
            cur["last_seen"], cur["missing_runs"], cur["first_missing"] = ts, 0, None

    if not fresh:
        return events   # cached/unchanged runs never advance the miss counters

    for k, cur in store.items():
        if cur["org_id"] != org_id or cur["election"] != election or cur["status"] != "active" or k in seen:
            continue
        cur["missing_runs"] += 1
        if cur["first_missing"] is None:
            cur["first_missing"] = ts
            events.append({"ts": ts, "election": election, "org_id": org_id, "contest_key": cur["contest_key"],
                           "type": "missing", "old": value_of(cur), "new": None, "source_url": source_url,
                           "note": f"not on the page; removal after {MISS_RUNS} runs and {MISS_DAYS} days"})
        days = (now - datetime.strptime(cur["first_missing"], "%Y-%m-%dT%H:%M:%SZ")).total_seconds() / 86400
        if cur["missing_runs"] >= MISS_RUNS and days >= MISS_DAYS:
            cur["status"] = "removed"
            events.append({"ts": ts, "election": election, "org_id": org_id, "contest_key": cur["contest_key"],
                           "type": "removed", "old": value_of(cur), "new": None, "source_url": source_url,
                           "note": f"missing in {cur['missing_runs']} consecutive runs over {days:.0f} days"})
    return events


def has_pending_misses(election: str, org_id: str, store: dict) -> bool:
    """True if some active endorsement of this org is currently missing: the next run must re-extract
    (not reuse the cache) so a one-off model miss cannot cause a removal."""
    return any(v["org_id"] == org_id and v["election"] == election and v["status"] == "active" and v["missing_runs"] > 0
               for v in store.values())
