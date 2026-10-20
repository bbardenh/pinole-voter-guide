import unittest

from voterguide.grid import build_grid, cell_text, show_contest, suggested_vote

M = {"key": "ca-prop-1", "level": "state", "type": "measure", "label": "Prop 1"}
R = {"key": "pin-treasurer", "level": "local", "type": "race", "label": "Pinole City Treasurer"}
C3 = {"key": "pin-council", "level": "local", "type": "race", "label": "Pinole City Council (3 seats)", "vote_for": 3}


def e(pos, cands=None, conf="high", flags=None):
    return {"position": pos, "candidates": cands or [], "confidence": conf, "flags": flags or []}


class GridTests(unittest.TestCase):
    def test_measure_majority(self):
        self.assertEqual(suggested_vote(M, [e("yes"), e("yes"), e("no")])[0], "Yes")
        self.assertEqual(suggested_vote(M, [e("no"), e("no"), e("yes")])[0], "No")
        self.assertEqual(suggested_vote(M, [e("yes"), e("no")])[0], "Split (1-1)")
        self.assertEqual(suggested_vote(M, [e("neutral"), e("no_position")])[0], "")
        self.assertEqual(suggested_vote(M, [])[0], "")

    def test_race_plurality_first_choice(self):
        ents = [e("candidate", ["Lee"]), e("candidate", ["Lee", "X"]), e("candidate", ["X", "Lee"])]
        self.assertEqual(suggested_vote(R, ents)[0], "Lee")
        tie = [e("candidate", ["A"]), e("candidate", ["B"])]
        self.assertEqual(suggested_vote(R, tie)[0], "Split: A / B")

    def test_multi_seat_top_n(self):
        ents = [e("candidate", ["A", "B", "C"]), e("candidate", ["A", "B", "D"]), e("candidate", ["A", "C"])]
        self.assertEqual(suggested_vote(C3, ents)[0], "A\nB\nC")
        tie = [e("candidate", ["A", "B", "C"]), e("candidate", ["A", "B", "D"])]
        self.assertEqual(suggested_vote(C3, tie)[0], "A\nB\nSplit for 1 more: C / D")

    def test_cell_text(self):
        self.assertEqual(cell_text(e("yes")), "Yes")
        self.assertEqual(cell_text(e("candidate", ["A", "B"])), "1. A\n2. B")
        self.assertEqual(cell_text(e("no", conf="low")), "No ?")
        self.assertEqual(cell_text(e("yes", flags=["evidence_unchecked_image"])), "Yes")   # unverifiable != suspicious

    def test_special_district_visibility(self):
        sd = {"key": "wcwd-div-5", "level": "special_district", "type": "race", "label": "WCWD 5"}
        self.assertFalse(show_contest(sd, 0))
        self.assertTrue(show_contest(sd, 1))
        self.assertTrue(show_contest({**sd, "coverage": "verified"}, 0))
        self.assertTrue(show_contest({**sd, "type": "measure"}, 0))           # district measures always show

    def test_build_grid_shape_and_sections(self):
        orgs = [{"id": "a", "name": "Org A", "home_url": "https://a.org/"}, {"id": "b", "name": "Org B", "home_url": ""}]
        reg = [M, R]
        store = {"k1": {"election": "E", "org_id": "a", "contest_key": "ca-prop-1", "position": "yes", "candidates": [],
                        "confidence": "high", "flags": [], "evidence": "Yes on 1", "source_url": "https://a.org/x",
                        "status": "active", "last_seen": "2026-10-10T00:00:00Z"}}
        g = build_grid(orgs, reg, store, "E", "Title", "2026-10-10")
        self.assertEqual(len(g[0]), 4)                       # contest, suggested, 2 orgs
        self.assertTrue(g[0][2]["formula"] and g[0][2]["v"].startswith("=HYPERLINK("))
        self.assertFalse(g[0][3]["formula"])                  # org without a URL
        labels = [r[0]["v"] for r in g[1:]]
        self.assertIn("STATE PROPOSITIONS", labels)
        self.assertIn("LOCAL RACES (PINOLE CITY & SCHOOL BOARD)", labels)
        prop_row = next(r for r in g if r[0]["v"] == "Prop 1")
        self.assertEqual((prop_row[1]["v"], prop_row[2]["v"], prop_row[3]["v"]), ("Yes", "Yes", ""))
        self.assertIn("https://a.org/x", prop_row[2]["note"])
        for r in g:
            self.assertEqual(len(r), 4)

    def test_removed_endorsements_not_shown(self):
        orgs = [{"id": "a", "name": "A", "home_url": ""}]
        store = {"k": {"election": "E", "org_id": "a", "contest_key": "ca-prop-1", "position": "yes", "candidates": [],
                       "confidence": "high", "flags": [], "evidence": "", "source_url": "", "status": "removed",
                       "last_seen": "2026-10-10T00:00:00Z"}}
        g = build_grid(orgs, [M], store, "E", "T", "d")
        row = next(r for r in g if r[0]["v"] == "Prop 1")
        self.assertEqual((row[1]["v"], row[2]["v"]), ("", ""))


if __name__ == "__main__":
    unittest.main()
