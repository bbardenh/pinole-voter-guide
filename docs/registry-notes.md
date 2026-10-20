# Pinole contest list: how it was verified (October 20, 2026)

## Sources

- Contra Costa County Elections, Run for Office page: Candidate Summary List (8/14/26), Candidate Detail List (8/27/26),
  List of Local Ballot Measures, Positions Up for Election (all PDFs).
- California Secretary of State: certified list of candidates, November 3, 2026 (8/27/26); qualified ballot measures.
- City of Pinole: candidate roster (8/18/26), elections page, political representation page (last updated 9/2025).
- District sites: EBMUD ward descriptions, BART districts, EBRPD ward pages, AC Transit wards map, WCCUSD trustee-area
  schools, CCCOE board page, SD7 district page.

## Pinole's districts

| District | Pinole's seat | On the Nov 3, 2026 ballot? |
|---|---|---|
| U.S. House | CD 8 (Prop 50 map) | Yes: Garamendi vs Recile |
| State Assembly | AD 14 | Yes: Wicks vs Rendon |
| State Senate | SD 7 | No (next in 2028) |
| Board of Equalization | District 2 | Yes: Lieber vs Pimentel |
| County Supervisor | D1, part probably D5 | No |
| Pinole City Council | 3 at-large seats | Yes: 5 candidates |
| Pinole City Treasurer | | No |
| WCCUSD | Trustee Area 1 (Tara Hills/Bayview: Area 4) | No (Areas 4, 5 uncontested). Measure V (parcel tax) is on the ballot |
| Contra Costa Community College | Ward 1 (city page's "Ward 2" looks outdated) | Yes: Donoso vs Sasai |
| EBMUD | Split: Wards 1 and 3 | Ward 3 yes: Gray vs Young |
| East Bay Regional Park | Ward 1 | No |
| BART | District 3 | No (only D2 is up) |
| AC Transit | Pinole is outside the district (WestCAT) | No |
| County Board of Education | Area 1 | No |
| West County Wastewater | Serves part of southwest Pinole; division unknown | Unclear; left out (single-candidate divisions are usually appointed) |
| Regional | Measure RTM | Yes |
| Courts | 1st Appellate District | Yes: same retention list as Oakland |

## Open questions (check against a Pinole sample ballot)

- Whether any Pinole precinct is in a contested West County Wastewater division.
- Whether a slice of Pinole sits outside CCCCD Ward 1 or outside Supervisor D1.

## How the automatic rebuild maps county codes

See `district_contests` and `city_offices` in `config/locality.yaml`. Seat numbers listed in `includes` are kept and
shown; others are dropped; `includes: null` keeps every seat as unverified (shown only if an organization endorses).
`tools/compare_registry.py` (or the "Check contest list" workflow) rebuilds from the live PDFs and diffs against the
hand-built list. The county PDF parser was written from the PDFs' extracted text as seen on 10/20/26 and has not yet
been run against the live files from GitHub Actions.
