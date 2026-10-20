import unittest
from datetime import date

from voterguide.suggestions import add_due, drop_suggestions, missing_contest_suggestions, review_rows

ORGS = [{"id": "a", "name": "Org A", "home_url": "https://a.org"}, {"id": "b", "name": "Org B", "home_url": "https://b.org"}]
E = "2026-11-03"


def end(org, key, status="active", conf="high", flags=None):
    return {"election": E, "org_id": org, "contest_key": key, "position": "yes", "candidates": [], "evidence": "q",
            "confidence": conf, "flags": flags or [], "source_url": "https://x", "last_seen": "2026-10-09T00:00:00Z", "status": status}


class SuggestionTests(unittest.TestCase):
    def test_drop_rules(self):
        sources = {"a": {"consecutive_failures": 4, "last_error": "HTTP 403"}, "b": {}}
        rows = drop_suggestions(ORGS, sources, {}, E, date(2026, 11, 3), date(2026, 10, 1))
        self.assertEqual([r[1] for r in rows], ["Org A"])                 # b: 33 days out, not yet a problem
        rows = drop_suggestions(ORGS, {"a": {"page_url": "https://a/x", "status": "ok"}, "b": {}}, {}, E, date(2026, 11, 3), date(2026, 10, 25))
        names = {r[1]: r[2] for r in rows}
        self.assertIn("nothing relevant", names["Org A"])                 # page found, zero endorsements
        self.assertIn("No endorsements page found", names["Org B"])       # 9 days out, no page

    def test_no_drop_when_endorsements_exist(self):
        store = {"k": end("a", "ca-prop-1")}
        rows = drop_suggestions(ORGS[:1], {"a": {"page_url": "https://a/x", "status": "ok"}}, store, E, date(2026, 11, 3), date(2026, 10, 25))
        self.assertEqual(rows, [])

    def test_missing_contests_need_two_orgs_and_local_scope(self):
        cache = {
            "a": {"items": [{"contest_key": "unlisted", "contest_label": "Pinole Measure ZZ, Parks"},
                            {"contest_key": "unlisted", "contest_label": "Richmond City Council District 4"}]},
            "b": {"items": [{"contest_key": "unlisted", "contest_label": "Pinole Measure ZZ - Parks"},
                            {"contest_key": "unlisted", "contest_label": "Richmond City Council District 4"},
                            {"contest_key": "pin-council", "contest_label": "Mayor"}]},
        }
        rows = missing_contest_suggestions(cache, {"a": "Org A", "b": "Org B"})
        self.assertEqual(len(rows), 1)
        self.assertIn("Measure ZZ", rows[0][1])

    def test_add_due(self):
        self.assertTrue(add_due({}, date(2026, 10, 9)))
        self.assertFalse(add_due({"generated_at": "2026-10-01T00:00:00Z"}, date(2026, 10, 9)))
        self.assertTrue(add_due({"generated_at": "2026-09-01T00:00:00Z"}, date(2026, 10, 9)))

    def test_review_rows(self):
        store = {f"k{i}": end("a", f"c{i}") for i in range(30)}
        store["low"] = end("b", "cx", conf="low")
        store["gone"] = end("b", "cy", status="removed")
        rows = review_rows(store, {"a": "Org A", "b": "Org B"}, {}, E, date(2026, 10, 9))
        kinds = [r[0] for r in rows[1:]]
        self.assertEqual(kinds.count("Check: low confidence"), 1)
        self.assertEqual(kinds.count("Sample"), 12)
        self.assertEqual(rows, review_rows(store, {"a": "Org A", "b": "Org B"}, {}, E, date(2026, 10, 10)))   # stable within a week
        self.assertNotEqual(rows[2:], review_rows(store, {"a": "Org A", "b": "Org B"}, {}, E, date(2026, 10, 20))[2:])  # new sample next week


if __name__ == "__main__":
    unittest.main()
