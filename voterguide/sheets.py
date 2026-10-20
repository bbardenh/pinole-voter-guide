"""Write the grid, change log and source health to Google Sheets via a service account."""
from __future__ import annotations

import json
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GREEN, RED = {"red": 0.80, "green": 0.92, "blue": 0.80}, {"red": 0.96, "green": 0.80, "blue": 0.80}


def get_service():
    raw = os.environ.get("GOOGLE_SA_KEY")
    if raw:
        creds = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    else:
        import google.auth

        creds, _ = google.auth.default(scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _rgb(t):
    return {"red": t[0], "green": t[1], "blue": t[2]}


def _meta(svc, sid):
    return svc.spreadsheets().get(spreadsheetId=sid, fields="sheets(properties,conditionalFormats)").execute()["sheets"]


def ensure_sheet(svc, sid: str, title: str, rows: int, cols: int) -> dict:
    """Return the sheet's {sheetId, conditionalFormats} creating/resizing it as needed."""
    sheets = _meta(svc, sid)
    found = next((s for s in sheets if s["properties"]["title"] == title), None)
    if found is None:
        res = svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [{"addSheet": {"properties": {
            "title": title, "gridProperties": {"rowCount": max(rows, 50), "columnCount": max(cols, 8)}}}}]}).execute(num_retries=3)
        return {"sheetId": res["replies"][0]["addSheet"]["properties"]["sheetId"], "cf": 0}
    grid = found["properties"]["gridProperties"]
    sheet_id = found["properties"]["sheetId"]
    if grid["rowCount"] < rows or grid["columnCount"] < cols:
        svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"rowCount": max(rows, grid["rowCount"]),
                                                                    "columnCount": max(cols, grid["columnCount"])}},
            "fields": "gridProperties(rowCount,columnCount)"}}]}).execute(num_retries=3)
    return {"sheetId": sheet_id, "cf": len(found.get("conditionalFormats", []))}


def write_grid(svc, sid: str, title: str, rows: list[list[dict]]) -> None:
    """Overwrite a tab's content, formatting and notes with the grid (formulas allowed)."""
    nrows, ncols = len(rows), max(len(r) for r in rows)
    info = ensure_sheet(svc, sid, title, nrows + 5, ncols + 1)
    sheet_id = info["sheetId"]

    row_data = []
    for r in rows:
        cells = []
        for c in r:
            cv = {"userEnteredValue": ({"formulaValue": c["v"]} if c["formula"] else {"stringValue": c["v"]}) if c["v"] != "" else {},
                  "note": c["note"] or "",
                  "userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP",
                                        "textFormat": {"bold": bool(c["bold"])},
                                        "backgroundColor": _rgb(c["bg"]) if c["bg"] else {"red": 1, "green": 1, "blue": 1}}}
            cells.append(cv)
        cells += [{"userEnteredValue": {}, "note": ""}] * (ncols - len(cells))
        row_data.append({"values": cells})

    reqs = [{"updateCells": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": nrows,
                                       "startColumnIndex": 0, "endColumnIndex": ncols},
                             "rows": row_data, "fields": "userEnteredValue,note,userEnteredFormat"}}]
    reqs += [{"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}} for _ in range(info["cf"])]
    rng = {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": nrows, "startColumnIndex": 1, "endColumnIndex": ncols}
    for text, color in (("Yes", GREEN), ("No", RED)):
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {"ranges": [rng], "booleanRule": {
            "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": text}]}, "format": {"backgroundColor": color}}}}})
    reqs += [
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "index": 0}, "fields": "index"}},   # newest election first
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 2}},
                                   "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 380}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
                                       "properties": {"pixelSize": 130}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": ncols},
                                       "properties": {"pixelSize": 125}, "fields": "pixelSize"}},
    ]
    svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": reqs}).execute(num_retries=3)


def write_table(svc, sid: str, title: str, values: list[list[str]]) -> None:
    """Plain table tab (Change Log, Source Health): clear and rewrite, header bold, frozen."""
    ncols = max(len(r) for r in values)
    info = ensure_sheet(svc, sid, title, len(values) + 5, ncols + 1)
    svc.spreadsheets().values().clear(spreadsheetId=sid, range=f"'{title}'").execute(num_retries=3)
    svc.spreadsheets().values().update(spreadsheetId=sid, range=f"'{title}'!A1", valueInputOption="USER_ENTERED",
                                       body={"values": values}).execute(num_retries=3)
    svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [
        {"repeatCell": {"range": {"sheetId": info["sheetId"], "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": _rgb((0.80, 0.86, 0.93))}},
                        "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
        {"updateSheetProperties": {"properties": {"sheetId": info["sheetId"], "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}},
    ]}).execute(num_retries=3)


def changelog_table(events: list[dict], org_names: dict[str, str], contest_labels: dict[str, str], limit: int = 3000) -> list[list[str]]:
    def fmt(v):
        if not v:
            return ""
        return v["position"].replace("_", " ") if v["position"] != "candidate" else " > ".join(v["candidates"])

    rows = [["Time (UTC)", "Election", "Organization", "Contest", "Event", "Old", "New", "Source", "Note"]]
    for e in sorted(events, key=lambda x: x["ts"], reverse=True)[:limit]:
        rows.append([e["ts"].replace("T", " ").replace("Z", ""), e["election"], org_names.get(e["org_id"], e["org_id"]),
                     contest_labels.get(e["contest_key"], e["contest_key"]), e["type"], fmt(e.get("old")), fmt(e.get("new")),
                     e.get("source_url", ""), e.get("note", "")])
    return rows


def health_table(orgs: list[dict], sources: dict, budget: dict) -> list[list[str]]:
    rows = [["Organization", "Status", "Endorsements page", "Last checked", "Last good read", "Last content change",
             "Consecutive failures", "Last error"]]
    for o in orgs:
        s = sources.get(o["id"], {})
        rows.append([o["name"], s.get("status", "not yet checked"), s.get("page_url") or "", s.get("last_checked", ""),
                     s.get("last_ok", ""), s.get("last_change", ""), str(s.get("consecutive_failures", 0)), s.get("last_error", "")])
    rows += [[], ["API spend this month", f"${budget.get('spent_usd', 0):.2f} of ${budget.get('cap_usd', 0):.2f}",
                  f"{budget.get('calls', 0)} model calls ({budget.get('month', '')})"]]
    return rows
