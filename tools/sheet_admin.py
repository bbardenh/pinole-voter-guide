"""One-off sheet maintenance run from CI with the service account.

Usage: python tools/sheet_admin.py delete-tab "<exact tab title>"
Only tabs on the allow-list can be deleted (so a typo can never remove a live tab).
"""
import os
import sys

sys.path.insert(0, ".")
from voterguide.sheets import get_service  # noqa: E402

ALLOW_DELETE = {
    "2026 Progressive Voter Guide",          # superseded by "2026 November General" (owner approved 2026-10-09)
    "2026 November General (preview)",       # preview tab replaced by the live tab
}


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "delete-tab":
        print(__doc__)
        return 2
    title, sid = sys.argv[2], os.environ["SHEET_ID"]
    if title not in ALLOW_DELETE:
        print(f"refusing: {title!r} is not on the allow-list")
        return 1
    svc = get_service()
    sheets = svc.spreadsheets().get(spreadsheetId=sid, fields="sheets.properties").execute()["sheets"]
    titles = [s["properties"]["title"] for s in sheets]
    target = next((s["properties"] for s in sheets if s["properties"]["title"] == title), None)
    print("tabs before:", titles)
    if target is None:
        print("nothing to delete (tab not found)")
        return 0
    if len(sheets) <= 1:
        print("refusing: it is the only tab")
        return 1
    svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [{"deleteSheet": {"sheetId": target["sheetId"]}}]}).execute(num_retries=3)
    after = [s["properties"]["title"] for s in svc.spreadsheets().get(spreadsheetId=sid, fields="sheets.properties").execute()["sheets"]]
    print("deleted:", title, "| tabs after:", after)
    return 0


if __name__ == "__main__":
    sys.exit(main())
