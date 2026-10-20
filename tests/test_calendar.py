import unittest
from datetime import date

from voterguide.calendar import merge, primary_election_date, rule_elections, tab_name
from voterguide.schedule import Election


class CalendarTests(unittest.TestCase):
    def test_primary_dates(self):
        self.assertEqual(primary_election_date(2026), date(2026, 6, 2))     # matches the county's 06/02/2026
        self.assertEqual(primary_election_date(2024), date(2024, 3, 5))     # matches 03/05/2024
        self.assertEqual(primary_election_date(2028), date(2028, 3, 7))
        self.assertEqual(primary_election_date(2022), date(2022, 6, 7))     # matches 06/07/2022
        self.assertEqual(primary_election_date(2030), date(2030, 6, 4))

    def test_tab_names(self):
        self.assertEqual(tab_name(date(2026, 11, 3), "general"), "2026 November General")
        self.assertEqual(tab_name(date(2028, 3, 7), "primary"), "2028 March Primary")
        self.assertEqual(tab_name(date(2027, 4, 13), "special", "City of Pinole Special Municipal Election"),
                         "2027-04-13 Pinole Special Municipal")

    def test_rule_elections_include_next_cycles(self):
        e = rule_elections(date(2026, 10, 9))
        dates = {x.date for x in e}
        self.assertIn(date(2026, 11, 3), dates)
        self.assertIn(date(2028, 3, 7), dates)
        self.assertIn(date(2028, 11, 7), dates)
        self.assertNotIn(date(2027, 11, 2), dates)           # odd years have no statewide election

    def test_config_wins_on_same_date(self):
        cfg = [Election(date(2026, 11, 3), "general", "2026 November General")]
        other = [Election(date(2026, 11, 3), "general", "Something Else"), Election(date(2028, 3, 7), "primary", "2028 March Primary")]
        m = merge(cfg, other)
        self.assertEqual([e.tab for e in m], ["2026 November General", "2028 March Primary"])


if __name__ == "__main__":
    unittest.main()
