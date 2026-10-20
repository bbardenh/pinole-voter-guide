import unittest
from datetime import date, timedelta

from voterguide.schedule import Election, general_election_date, run_mode, tabs_to_create

GEN26 = Election(date(2026, 11, 3), "general", "2026 November General")


class ScheduleTests(unittest.TestCase):
    def test_general_dates(self):
        self.assertEqual(general_election_date(2026), date(2026, 11, 3))
        self.assertEqual(general_election_date(2028), date(2028, 11, 7))
        self.assertEqual(general_election_date(2024), date(2024, 11, 5))

    def test_nothing_before_45_days(self):
        # 46+ days out: skip every day, even Mondays
        for back in range(46, 120):
            self.assertEqual(run_mode(GEN26.date - timedelta(days=back), [GEN26]), "skip", back)

    def test_weekly_between_45_and_31_days(self):
        d = GEN26.date - timedelta(days=45)           # 2026-09-19, a Saturday
        for back in range(45, 30, -1):
            day = GEN26.date - timedelta(days=back)
            expected = "weekly" if day.weekday() == 0 else "skip"
            self.assertEqual(run_mode(day, [GEN26]), expected, str(day))
        self.assertEqual(run_mode(date(2026, 9, 21), [GEN26]), "weekly")   # Monday, 43 days out

    def test_daily_last_30_days(self):
        for back in range(30, -1, -1):
            self.assertEqual(run_mode(GEN26.date - timedelta(days=back), [GEN26]), "daily", back)

    def test_stops_after_election(self):
        self.assertEqual(run_mode(date(2026, 11, 4), [GEN26]), "skip")
        self.assertEqual(run_mode(date(2026, 12, 7), [GEN26]), "skip")      # a Monday, still skip

    def test_multiple_elections_use_nearest(self):
        primary = Election(date(2028, 3, 7), "primary", "2028 March Primary")
        self.assertEqual(run_mode(date(2027, 1, 4), [GEN26, primary]), "skip")
        self.assertEqual(run_mode(date(2028, 2, 20), [GEN26, primary]), "daily")

    def test_tab_creation_at_45_days(self):
        self.assertEqual(tabs_to_create(date(2026, 9, 19), [GEN26], set()), [GEN26])        # day 45
        self.assertEqual(tabs_to_create(date(2026, 9, 18), [GEN26], set()), [])             # day 46
        self.assertEqual(tabs_to_create(date(2026, 10, 8), [GEN26], {GEN26.tab}), [])       # exists
        self.assertEqual(tabs_to_create(date(2026, 11, 4), [GEN26], set()), [])             # past


if __name__ == "__main__":
    unittest.main()
