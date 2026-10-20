import unittest
from datetime import datetime, timedelta

from voterguide.budget import Budget, cost
from voterguide.reconcile import has_pending_misses, reconcile

E, ORG = "2026-11-03", "spur"
T0 = datetime(2026, 10, 10, 12, 0, 0)


def item(key="ca-prop-1", pos="yes", cands=None):
    return {"contest_key": key, "position": pos, "candidates": cands or [], "evidence": "x", "confidence": "high", "flags": []}


def types(events):
    return [e["type"] for e in events]


class ReconcileTests(unittest.TestCase):
    def test_add_confirm_change(self):
        store = {}
        self.assertEqual(types(reconcile(E, ORG, [item()], store, T0, True)), ["added"])
        self.assertEqual(types(reconcile(E, ORG, [item()], store, T0 + timedelta(days=1), True)), [])
        ev = reconcile(E, ORG, [item(pos="no")], store, T0 + timedelta(days=2), True)
        self.assertEqual(types(ev), ["changed"])
        self.assertEqual(ev[0]["old"]["position"], "yes")
        self.assertEqual(ev[0]["new"]["position"], "no")

    def test_candidate_order_change_is_a_change(self):
        store = {}
        reconcile(E, ORG, [item("oak-mayor", "candidate", ["A", "B"])], store, T0, True)
        ev = reconcile(E, ORG, [item("oak-mayor", "candidate", ["B", "A"])], store, T0, True)
        self.assertEqual(types(ev), ["changed"])

    def test_removal_needs_three_misses_and_seven_days(self):
        store = {}
        reconcile(E, ORG, [item()], store, T0, True)
        k = next(iter(store))
        # miss 1 (day 1): logged as missing
        self.assertEqual(types(reconcile(E, ORG, [], store, T0 + timedelta(days=1), True)), ["missing"])
        # miss 2 (day 2), miss 3 (day 3): three misses but only 2 days -> still active
        reconcile(E, ORG, [], store, T0 + timedelta(days=2), True)
        ev = reconcile(E, ORG, [], store, T0 + timedelta(days=3), True)
        self.assertEqual(store[k]["status"], "active")
        self.assertNotIn("removed", types(ev))
        # day 8 (7 days after first miss, 4th miss) -> removed
        ev = reconcile(E, ORG, [], store, T0 + timedelta(days=8), True)
        self.assertEqual(types(ev), ["removed"])
        self.assertEqual(store[k]["status"], "removed")

    def test_two_misses_after_a_week_not_enough(self):
        store = {}
        reconcile(E, ORG, [item()], store, T0, True)
        reconcile(E, ORG, [], store, T0 + timedelta(days=1), True)
        reconcile(E, ORG, [], store, T0 + timedelta(days=9), True)
        self.assertEqual(next(iter(store.values()))["status"], "active")

    def test_reappearing_resets_counters(self):
        store = {}
        reconcile(E, ORG, [item()], store, T0, True)
        reconcile(E, ORG, [], store, T0 + timedelta(days=1), True)
        reconcile(E, ORG, [item()], store, T0 + timedelta(days=2), True)
        v = next(iter(store.values()))
        self.assertEqual((v["missing_runs"], v["first_missing"]), (0, None))
        reconcile(E, ORG, [], store, T0 + timedelta(days=3), True)
        self.assertEqual(next(iter(store.values()))["missing_runs"], 1)

    def test_cached_runs_never_count_as_misses(self):
        store = {}
        reconcile(E, ORG, [item()], store, T0, True)
        for d in range(1, 30):
            reconcile(E, ORG, [], store, T0 + timedelta(days=d), False)
        v = next(iter(store.values()))
        self.assertEqual((v["status"], v["missing_runs"]), ("active", 0))

    def test_pending_misses_forces_recheck(self):
        store = {}
        reconcile(E, ORG, [item()], store, T0, True)
        self.assertFalse(has_pending_misses(E, ORG, store))
        reconcile(E, ORG, [], store, T0 + timedelta(days=1), True)
        self.assertTrue(has_pending_misses(E, ORG, store))

    def test_readd_after_removal(self):
        store = {}
        reconcile(E, ORG, [item()], store, T0, True)
        for d in (1, 2, 3, 9):
            reconcile(E, ORG, [], store, T0 + timedelta(days=d), True)
        ev = reconcile(E, ORG, [item()], store, T0 + timedelta(days=10), True)
        self.assertEqual(types(ev), ["re-added"])

    def test_unlisted_and_other_orgs_untouched(self):
        store = {}
        reconcile(E, "other", [item()], store, T0, True)
        reconcile(E, ORG, [item("unlisted")], store, T0, True)
        self.assertEqual(len(store), 1)
        reconcile(E, ORG, [], store, T0 + timedelta(days=1), True)    # other org's endorsement unaffected
        self.assertEqual(next(iter(store.values()))["missing_runs"], 0)


class RunContractTests(unittest.TestCase):
    def test_run_style_now_works_across_runs(self):
        """run.py passes naive-UTC `now`; a second run must be able to subtract stored timestamps."""
        from datetime import timezone

        now1 = datetime.now(timezone.utc).replace(tzinfo=None)
        store = {}
        reconcile(E, ORG, [item()], store, now1, True)
        reconcile(E, ORG, [], store, now1 + timedelta(days=1), True)    # parses first_missing and subtracts
        reconcile(E, ORG, [], store, now1 + timedelta(days=9), True)
        self.assertEqual(next(iter(store.values()))["missing_runs"], 2)

    def test_pipeline_nav_interval_arithmetic(self):
        now = datetime.now(__import__("datetime").timezone.utc).replace(tzinfo=None)
        last = (now - timedelta(days=40)).strftime("%Y-%m-%d")
        self.assertGreaterEqual((now - datetime.strptime(last, "%Y-%m-%d")).days, 30)


class BudgetTests(unittest.TestCase):
    def test_cost_opus(self):
        self.assertAlmostEqual(cost("claude-opus-5-5", 1_000_000, 100_000), 4.0 + 2.0)

    def test_cap_blocks_calls(self):
        b = Budget(cap=1.0)
        self.assertTrue(b.allow("claude-opus-5-5", 10_000))
        b.charge("claude-opus-5-5", 200_000, 10_000)   # $1.00
        self.assertFalse(b.allow("claude-opus-5-5", 10_000))

    def test_month_rollover_resets(self):
        s = {"month": "2026-09", "spent_usd": 19.9, "calls": 5, "alerted": True}
        b = Budget(s, now=datetime(2026, 10, 1))
        self.assertEqual((b.spent, b.alerted), (0.0, False))
        b2 = Budget({"month": "2026-10", "spent_usd": 12.5, "calls": 3}, now=datetime(2026, 10, 20))
        self.assertEqual(b2.spent, 12.5)
        self.assertAlmostEqual(b2.remaining, 7.5)


if __name__ == "__main__":
    unittest.main()
