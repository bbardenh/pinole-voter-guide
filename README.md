# Pinole progressive voter guide updater

Keeps a Google Sheet, "Cross-Referenced Progressive Voter Guide (Pinole, Contra Costa County, California)", up to date
from the endorsement pages of ~30 organizations. Runs on GitHub Actions; state lives in `state/` (committed by the bot).

Adapted in October 2026 from the Oakland guide. Everything place-specific is in `config/locality.yaml`, so the same
code could be pointed at another Contra Costa city by editing that file and `config/orgs.yaml`.

## How it runs

A daily trigger (14:17 UTC) calls `python -m voterguide.run`, which decides whether today is a run day
(`voterguide/schedule.py`): nothing until 45 days before an election; weekly (Mondays) until day 31; daily from day 30
through election day; then quiet again until the next election.

**Elections** come from `config/elections.yaml`, California's statewide generals/primaries (rules in
`voterguide/calendar.py`) and the Contra Costa Elections "Upcoming Elections" page (specials whose name mentions one of
`special_election_keywords`). The county's election names rarely say which city a special is for, so add Pinole
specials to `config/elections.yaml` by hand. At day 45 the new election's tab and contest list are created automatically.

**Contest list** (`config/contests/<date>.yaml`) is built by `voterguide/registry_builder.py` and refreshed every 14 days:
- Local races and candidates: the county's "Candidate Summary List" PDF (found by link text on the county's Run for
  Office page, so renamed files are fine). Contest codes like `PinoleCouncil` and `EastBayMUD3` are matched against
  `config/locality.yaml`: city offices by prefix, district seats by the seat numbers that include Pinole. Seats with no
  more candidates than seats are left out (they're filled by appointment and don't appear on the ballot).
- Local and regional measures: the county's "List of Local Ballot Measures" PDF, matched by jurisdiction text
  (City of Pinole, West Contra Costa Unified, regional, countywide).
- Federal/state races and judicial retention: the Secretary of State's certified candidate list PDF, filtered to
  Pinole's districts (CD 8, AD 14, SD 7, BOE 2, 1st Appellate District).
- Statewide propositions: the Secretary of State's qualified-measures page (read by the model).
If an official source can't be read, previous entries are kept, never silently dropped.

**Each source**: fetch its known endorsements page (free) -> unchanged content fingerprint = reuse cached result ($0);
otherwise the Claude API re-reads it. Sources with no page yet are probed for free; the link finder runs at most
monthly. Pages that are images/PDFs, behind frames, JS-rendered or bot-challenged are handled (vision, headless browser).

Endorsements are removed only after being absent from 3 consecutive fresh readings AND 7 days; failed fetches, cached
runs, and pages that stopped looking like endorsement pages never count (`voterguide/reconcile.py`).

Monthly API cap: $20 (`VG_BUDGET_CAP`, `state/budget.json`). At the cap the run stops calling the model and opens an issue.

Alerts are GitHub issues (emailed to the repo owner): a source failing 3 runs in a row, the budget cap, an unusable API
key/credit, or a contest list that could not be built. An API outage aborts the run and never overwrites the sheet.

A monthly heartbeat commit (`state/heartbeat.txt`) stops GitHub from disabling the schedule during quiet months.

## Sheet tabs (written by the bot; created automatically in a blank sheet)

- `<election tab>` (e.g. "2026 November General") - the matrix; Suggested Vote by majority (measures), plurality of
  first choices (single-seat races) or the most-endorsed N candidates (vote-for-N races like City Council); hover a
  cell for source, date and quote; "?" = low confidence.
- `Change Log` - every added / changed / missing / removed endorsement.
- `Source Health` - per-organization status, page, last good read, failures, plus this month's API spend.
- `Suggestions` - sources that may be worth dropping, contests several organizations mention that the contest list
  lacks, and (monthly, via web search) progressive organizations to consider adding.
- `Review Queue` - every low-confidence cell plus a weekly-rotating random sample, each with its quote and source link.

## Files

- `config/locality.yaml` - the place: city, districts, which ward/area numbers include Pinole, text patterns.
- `config/orgs.yaml` - sources (`active: false` = retired; `hint_url` = page to try first).
- `config/contests/<date>.yaml` - contest list per election (auto-generated; 2026-11-03 was hand-checked).
  `docs/registry-notes.md` - how Pinole's districts were verified.
- `config/elections.yaml` - elections to always include. `.github/workflows/update.yml` - the run.

## Setting up your copy

1. Create a GitHub repository and push this folder to it (`git init`, `git add .`, `git commit`, `git push`).
2. Create a blank Google Sheet. Create a Google Cloud service account, download its JSON key, and share the sheet with
   the service account's email as Editor.
3. In the repo's Settings -> Secrets and variables -> Actions: secrets `ANTHROPIC_API_KEY` and `GOOGLE_SA_KEY` (the whole
   JSON key), variable `SHEET_ID` (the long ID in the sheet's URL).
4. Actions -> "Check contest list" -> Run workflow, to confirm the county PDFs parse.
5. Actions -> "Update voter guide" -> Run workflow with `tab_suffix` = " (preview)" for a first look, then without.

## Common tasks

- Manual run: Actions -> "Update voter guide" -> Run workflow (`tab_suffix` = " (preview)" writes a preview tab;
  `dry_run` = no writes; `rebuild_registry`; `fresh` = ignore the page cache).
- Retire/add a source: edit `config/orgs.yaml`. Model: `VG_MODEL` (default claude-opus-5-5).
- Delete an obsolete tab: Actions -> "Sheet admin" (only allow-listed tab names; see `tools/sheet_admin.py`).
- Tests: `python -m unittest discover -s tests -t .`
# pinole-voter-guide
