import unittest

from tests.test_county import MEASURES
from voterguide import locality
from voterguide.county import parse_measures
from voterguide.registry_builder import (candidates_from_cert_text, classify_county_contest, classify_measure,
                                         retention_from_cert_text, titlecase_name)

CFG = locality.load()


class CountyContestTests(unittest.TestCase):
    def k(self, code, n=1):
        r = classify_county_contest(code, n, CFG)
        return r["key"] if r else None

    def test_city(self):
        r = classify_county_contest("PinoleCouncil", 3, CFG)
        self.assertEqual((r["key"], r["level"], r["vote_for"]), ("pin-council", "local", 3))
        self.assertEqual(r["label"], "Pinole City Council (3 seats)")
        self.assertEqual(self.k("PinoleTreasurer"), "pin-treasurer")
        self.assertIsNone(self.k("HerculesCouncil"))
        self.assertIsNone(self.k("RichmondMayor"))

    def test_districts_covering_pinole(self):
        self.assertEqual(self.k("EastBayMUD3"), "ebmud-ward-3")
        self.assertIsNone(self.k("EastBayMUD7"))                     # not Pinole
        self.assertEqual(self.k("CCCollege1"), "ccccd-ward-1")
        self.assertIsNone(self.k("CCCollege3"))
        self.assertEqual(self.k("WestCCUSD Area4"), "wccusd-area-4")
        self.assertIsNone(self.k("WestCCUSD Area5"))
        self.assertIsNone(self.k("BART2"))                           # Pinole is BART District 3
        self.assertIsNone(self.k("ACTrans1-Short"))                  # Pinole is outside AC Transit
        self.assertIsNone(self.k("CCCBdEdSchBd2"))
        self.assertIsNone(self.k("AntiochUSD Area2"))

    def test_unknown_coverage_kept_unverified(self):
        r = classify_county_contest("WestCountyWastewater Div5", 1, CFG)
        self.assertEqual((r["key"], r["coverage"]), ("wcwd-div-5", "unverified"))
        self.assertEqual(classify_county_contest("EastBayMUD3", 1, CFG)["coverage"], "verified")


class BuildTests(unittest.TestCase):
    def test_build_end_to_end_offline(self):
        from datetime import date
        from unittest import mock

        from tests.test_county import CANDIDATES
        from voterguide import county
        from voterguide import registry_builder as rb

        prev = [{"key": "ca-prop-1", "level": "state", "type": "measure", "label": "CA Proposition 1, X"}]
        with mock.patch.object(county, "documents", return_value={"candidates": "c", "measures": "m"}), \
                mock.patch.object(county, "pdf_text", side_effect=lambda u: CANDIDATES if u == "c" else MEASURES), \
                mock.patch.object(rb, "sos_cert_text", return_value=CERT):
            got, warns = rb.build(date(2026, 11, 3), prev=prev, use_model=False)
        keys = {c["key"] for c in got}
        self.assertTrue({"pin-council", "ebmud-ward-3", "ccccd-ward-1", "wccusd-measure-v", "reg-measure-rtm",
                         "us-house-d8", "ca-assembly-d14", "ca-prop-1"} <= keys)
        self.assertNotIn("wccusd-area-4", keys)                      # one candidate for one seat: not on the ballot
        self.assertTrue(any("uncontested" in w for w in warns))
        self.assertTrue(any("proposition" in w for w in warns))      # carried over, not dropped


class MeasureTests(unittest.TestCase):
    def test_measures(self):
        got = {m["letter"]: classify_measure(m, CFG) for m in parse_measures(MEASURES)}
        self.assertEqual(got["RTM"]["key"], "reg-measure-rtm")
        self.assertEqual(got["RTM"]["level"], "regional")
        self.assertIsNone(got["P"])                                  # Hercules
        self.assertEqual(got["V"]["key"], "wccusd-measure-v")
        self.assertEqual(got["V"]["label"], "West Contra Costa Unified School District Measure V, Parcel Tax Renewal")
        self.assertEqual(got["Z"]["key"], "pin-measure-z")

    def test_county_measure(self):
        m = {"letter": "X", "title": "Sales Tax", "text": "Shall Contra Costa County enact a half-cent sales tax ..."}
        self.assertEqual(classify_measure(m, CFG)["key"], "county-measure-x")
        m2 = {"letter": "W", "title": "Parcel Tax", "text": "Shall Acalanes Union High School District ..."}
        self.assertIsNone(classify_measure(m2, CFG))


CERT = """General Election - November 3, 2026
Governor
Xavier Becerra Democratic
Voting Rights Attorney
Steve Hilton Republican
Small Business Owner
United States Representative District 8
John Garamendi* Democratic
Member of Congress
Rudy Recile Republican
Business Owner/Consultant
United States Representative District 12
Lateefah Simon* Democratic
Member of Congress
State Assembly Member District 14
Buffy Wicks* Democratic
Assemblymember/Mom
Mark Rendon Green
Teacher
State Assembly Member District 15
Anamarie Ávila Farías* Democratic
Board of Equalization Member District 2
Sally J. Lieber* Democratic
Incumbent
John Pimentel Democratic
Member, Board of Trustees, San Mateo County Community College District
Page 7 of 41
Supreme Court - For all 58 Counties
"""


class CertListTests(unittest.TestCase):
    def test_area_races_only(self):
        got = {c["key"]: c["candidates"] for c in candidates_from_cert_text(CERT, CFG)}
        self.assertEqual(got["ca-governor"], ["Xavier Becerra", "Steve Hilton"])
        self.assertEqual(got["us-house-d8"], ["John Garamendi", "Rudy Recile"])
        self.assertEqual(got["ca-assembly-d14"], ["Buffy Wicks", "Mark Rendon"])
        self.assertEqual(got["ca-boe-d2"], ["Sally J. Lieber", "John Pimentel"])
        self.assertNotIn("us-house-d12", got)
        self.assertNotIn("ca-assembly-d15", got)


class NameTests(unittest.TestCase):
    def test_titlecase(self):
        self.assertEqual(titlecase_name("XAVIER BECERRA"), "Xavier Becerra")
        self.assertEqual(titlecase_name("DONALD P. (DON) WAGNER"), "Donald P. (Don) Wagner")
        self.assertEqual(titlecase_name('TRUC "CHRISTY" LAM-JULIAN'), 'Truc "Christy" Lam-Julian')
        self.assertEqual(titlecase_name("CLYDE HENRY LEWIS, JR"), "Clyde Henry Lewis, Jr")
        self.assertEqual(titlecase_name("PATRICK O'BRIEN"), "Patrick O'Brien")
        self.assertEqual(titlecase_name("MARY-ANN MCDONALD"), "Mary-Ann McDonald")

    def test_known_spelling_preferred(self):
        self.assertEqual(titlecase_name("JOHN DE LA CRUZ", {"johndelacruz": "John de la Cruz"}), "John de la Cruz")


SOS_TEXT = """
Supreme Court - For all 58 Counties
• For Associate Justice of the Supreme Court
Shall Associate Justice of the Supreme Court KELLI M. EVANS be elected to the
office for the term provided by law?
Court of Appeal - First Appellate District
Alameda, Contra Costa, Del Norte
• For Associate Justice, Court of Appeal, First District, Division One
Shall Associate Justice CHARLES A. SMILEY be elected to the office for the
term provided by law?
Court of Appeal – Second Appellate District
• For Associate Justice, Court of Appeal, Second District, Division One
Shall Associate Justice MICHELLE C. KIM be elected to the office for the term
provided by law?
"""


class RetentionTests(unittest.TestCase):
    def test_retention_parse(self):
        keys = [r["key"] for r in retention_from_cert_text(SOS_TEXT)]
        self.assertEqual(keys, ["ca-supreme-evans", "ca-coa1-d1-smiley"])


if __name__ == "__main__":
    unittest.main()
