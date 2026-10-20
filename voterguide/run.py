"""Scheduled entry point:  python -m voterguide.run [--force] [--dry-run] [--no-sheet] [--only id,id] [--tab-suffix S]

Decides from the date whether to run at all (nothing before 45 days; weekly to day 31; daily last 30 days),
processes each active source (reusing cached results for unchanged pages), reconciles endorsements, writes
state/, and updates the Google Sheet (election tab, Change Log, Source Health, Suggestions, Review Queue).
Failures never delete endorsements. A new election's registry and tab are created automatically at day 45.
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from . import locality, registry_builder, suggestions
from . import state as st_mod
from .budget import DEFAULT_CAP, Budget
from .calendar import all_elections
from .pipeline import Context, process_org
from .reconcile import reconcile
from .schedule import Election, run_mode

ROOT = Path(__file__).resolve().parent.parent
FAILURE_ALERT_AFTER = 3
WORKERS = 3
REGISTRY_REFRESH_DAYS = 14


def load_config():
    orgs_all = yaml.safe_load((ROOT / "config" / "orgs.yaml").read_text(encoding="utf-8"))["orgs"]
    cfg_elections = [Election(date=e["date"] if isinstance(e["date"], date) else date.fromisoformat(str(e["date"])),
                              kind=e["kind"], tab=e["tab"])
                     for e in yaml.safe_load((ROOT / "config" / "elections.yaml").read_text(encoding="utf-8"))["elections"]]
    return [o for o in orgs_all if o.get("active", True)], cfg_elections, locality.load()


def sheet_title(election: Election) -> str:
    when = election.date.strftime("%B %d, %Y").replace(" 0", " ")
    label = {"general": "General Election", "primary": "Primary Election"}.get(election.kind, election.tab)
    return f"{when} {label} - Cross-Referenced Progressive Voter Guide ({locality.load()['guide_place']})"


def ensure_registry(election: Election, budget: Budget, now: datetime, alerts: list[str], force_rebuild: bool, dry_run: bool):
    """Load this election's contest registry, (re)building it from official sources when missing or older than 14 days."""
    from .extract import MODEL

    built = st_mod.load("registry_built.json", {})
    eid = election.date.isoformat()
    existing = registry_builder.load_registry(election.date)
    last = built.get(eid)
    stale = (not last) or (now.date() - date.fromisoformat(last)).days >= REGISTRY_REFRESH_DAYS
    if existing is not None and not (stale or force_rebuild):
        return existing
    if dry_run and existing is not None:
        return existing
    try:
        contests, warns = registry_builder.build(election.date, prev=existing)
    except Exception as e:   # noqa: BLE001 - county/SOS down or election not published yet
        if existing is not None:
            print(f"registry refresh failed ({e}); using the existing one")
            return existing
        alerts.append(f"**Could not build the contest list for {election.tab}** ({e}). The run was skipped; it retries tomorrow.")
        return None
    budget.charge(MODEL, 25000, 1500)                         # the proposition lookup uses one model call
    if not dry_run:
        registry_builder.save(election.date, contests, election.tab)
        built[eid] = now.date().isoformat()
        st_mod.save("registry_built.json", built)
    if existing is None:
        alerts.append(f"New contest list built automatically for **{election.tab}**: {len(contests)} contests from the county elections office "
                      f"and Secretary of State. Worth a quick look at config/contests/{eid}.yaml. "
                      + ("; ".join(warns) if warns else ""))
    elif warns:
        print("registry warnings:", "; ".join(warns))
    return contests


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="run even if the schedule says skip")
    ap.add_argument("--dry-run", action="store_true", help="no state saved, no sheet written")
    ap.add_argument("--no-sheet", action="store_true", help="save state but do not write the sheet")
    ap.add_argument("--only", default="", help="comma-separated org ids")
    ap.add_argument("--sheet-id", default=os.environ.get("SHEET_ID", ""))
    ap.add_argument("--tab-suffix", default="", help='e.g. " (preview)" to write a separate preview tab')
    ap.add_argument("--fresh", action="store_true", help="ignore page-change cache (re-extract everything)")
    ap.add_argument("--rebuild-registry", action="store_true", help="rebuild the contest list from official sources now")
    ap.add_argument("--offline-calendar", action="store_true", help="do not consult the county for the election calendar")
    args = ap.parse_args(argv)

    # Naive UTC everywhere: state timestamps are parsed as naive, so mixing in an aware datetime would crash.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now.date()
    orgs, cfg_elections, place = load_config()
    elections = all_elections(cfg_elections, today, place["special_election_keywords"], use_county=not args.offline_calendar)
    mode = run_mode(today, elections)
    if mode == "skip" and not args.force:
        print(f"{today}: outside the active window (45 days before an election); nothing to do.")
        return 0
    upcoming = sorted((e for e in elections if e.date >= today), key=lambda e: e.date)
    election = upcoming[0] if upcoming else sorted(elections, key=lambda e: e.date)[-1]
    election_id = election.date.isoformat()
    only = {x for x in args.only.split(",") if x}
    all_orgs = list(orgs)
    if only:
        orgs = [o for o in orgs if o["id"] in only]
    print(f"{today} mode={mode if mode != 'skip' else 'forced'} election={election.tab} ({election_id}) sources={len(orgs)}")

    alerts: list[str] = []
    budget = Budget(st_mod.load("budget.json", {}), cap=float(os.environ.get("VG_BUDGET_CAP", DEFAULT_CAP)), now=now)
    registry = ensure_registry(election, budget, now, alerts, args.rebuild_registry, args.dry_run)
    if registry is None:
        _write_alerts(alerts)
        return 1

    sources = st_mod.load("sources.json", {}, sub=election_id)
    store = st_mod.load("endorsements.json", {}, sub=election_id)
    cache = st_mod.load("extractions.json", {}, sub=election_id)
    ctx = Context(registry, budget, election_id, store, now, force_fresh=args.fresh)

    for o in orgs:
        sources.setdefault(o["id"], {})
        cache.setdefault(o["id"], {})

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        outcomes = list(ex.map(lambda o: process_org(o, sources[o["id"]], cache[o["id"]], ctx), orgs))

    events: list[dict] = []
    names = {o["id"]: o["name"] for o in all_orgs}
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    for out in outcomes:
        s = sources[out.org_id]
        s["page_url"] = out.page_url or s.get("page_url")
        if out.status in ("ok", "cached"):
            s.update(status="ok", consecutive_failures=0, last_ok=stamp, last_error="", alerted=False)
            events += reconcile(election_id, out.org_id, out.items, store, now, fresh=out.fresh, source_url=out.page_url)
        elif out.status == "not_published":
            s.update(status="no endorsements published yet", consecutive_failures=0, last_ok=stamp, last_error="", alerted=False)
        elif out.status == "failing":
            s["consecutive_failures"] = s.get("consecutive_failures", 0) + 1
            s.update(status="failing", last_error=out.error[:200])
            if s["consecutive_failures"] >= FAILURE_ALERT_AFTER and not s.get("alerted"):
                s["alerted"] = True
                alerts.append(f"**{names[out.org_id]}** has failed {s['consecutive_failures']} runs in a row: {out.error[:150]} "
                              f"({s.get('page_url') or 'no page known'})")
        elif out.status == "budget_blocked":
            s["status"] = "skipped: monthly API budget reached"
        elif out.status == "api_down":
            s["status"] = "skipped: Anthropic API unavailable"

    if ctx.fatal:
        alerts.append(f"**Anthropic API unusable**: {ctx.fatal[:200]}. If it mentions the credit balance, add credit at "
                      f"https://console.anthropic.com/settings/billing. The sheet was NOT updated this run; existing data is untouched.")
    if ctx.budget_blocked and not budget.alerted:
        budget.alerted = True
        alerts.append(f"**Monthly API budget reached** (${budget.spent:.2f} of ${budget.cap:.2f}); remaining pages were skipped "
                      f"and will resume next month or when the cap is raised (VG_BUDGET_CAP).")

    counts, ev_counts = {}, {}
    for out in outcomes:
        counts[out.status] = counts.get(out.status, 0) + 1
    for e in events:
        ev_counts[e["type"]] = ev_counts.get(e["type"], 0) + 1
    print("sources:", counts, "| events:", ev_counts, f"| spent this run ${sum(o.spent for o in outcomes):.2f}",
          f"| month ${budget.spent:.2f}/${budget.cap:.2f}")
    for out in outcomes:      # one line per source so every outcome is visible in the log
        detail = out.error or "; ".join(out.notes[:2])
        print(f"  [{out.status:14}] {names[out.org_id][:40]:40} items={len(out.items):3} ${out.spent:.2f} "
              f"{(out.page_url or '')[:70]} {detail[:160]}")

    if args.dry_run:
        print("dry run: nothing saved or written.")
        return 0

    # --- monthly suggestions of sources to add (paid web search; only inside the active window and under budget)
    from .extract import MODEL

    sug_state = st_mod.load("suggestions.json", {})
    if not ctx.fatal and not only and suggestions.add_due(sug_state, today) and budget.allow(MODEL, 40000):
        try:
            items, t_in, t_out = suggestions.find_additions(all_orgs, election.tab)
            budget.charge(MODEL, t_in, t_out)
            budget.spent += suggestions.SEARCH_FEE_ESTIMATE
            sug_state = {"generated_at": stamp, "items": items}
            st_mod.save("suggestions.json", sug_state)
            print(f"suggestions: {len(items)} organizations proposed")
        except Exception as e:   # noqa: BLE001 - suggestions are optional; never fail the run
            print(f"suggestions skipped: {type(e).__name__}: {e}")

    st_mod.save("sources.json", sources, sub=election_id)
    st_mod.save("endorsements.json", store, sub=election_id)
    st_mod.save("extractions.json", cache, sub=election_id)
    st_mod.save("budget.json", budget.to_state())
    st_mod.append_events(events)
    _write_alerts(alerts)

    if ctx.fatal:
        print("API unusable: sheet not updated.")
        return 1
    if not args.no_sheet and args.sheet_id:
        from . import sheets
        from .grid import build_grid

        svc = sheets.get_service()
        tab = election.tab + args.tab_suffix
        sheets.write_grid(svc, args.sheet_id, tab, build_grid(all_orgs, registry, store, election_id, sheet_title(election), today.isoformat()))
        labels = {c["key"]: c["label"] for c in registry}
        org_names = {o["id"]: o["name"] for o in all_orgs}
        sheets.write_table(svc, args.sheet_id, "Change Log", sheets.changelog_table(st_mod.read_events(), org_names, labels))
        sheets.write_table(svc, args.sheet_id, "Source Health", sheets.health_table(all_orgs, sources, budget.to_state()))
        sheets.write_table(svc, args.sheet_id, "Suggestions", suggestions.suggestions_table(
            suggestions.drop_suggestions(all_orgs, sources, store, election_id, election.date, today),
            suggestions.missing_contest_suggestions(cache, org_names), suggestions.add_rows(sug_state)))
        sheets.write_table(svc, args.sheet_id, "Review Queue", suggestions.review_rows(store, org_names, labels, election_id, today))
        print(f"sheet updated: tab '{tab}', Change Log, Source Health, Suggestions, Review Queue")
    return 0


def _write_alerts(alerts: list[str]) -> None:
    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    f = out_dir / "alerts.md"
    if alerts:
        f.write_text("\n".join(f"- {a}" for a in alerts) + "\n", encoding="utf-8")
        print("ALERTS:\n" + f.read_text(encoding="utf-8"))
    elif f.exists():
        f.unlink()


if __name__ == "__main__":
    sys.exit(main())
