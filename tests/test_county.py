import unittest
from datetime import date

from voterguide.county import (document_date, document_mentions, find_documents, parse_candidate_list,
                               parse_election_slug, parse_measures)

# Layout of the county's "Candidate Summary List" PDF as pypdf extracts it (Nov 3, 2026 edition).
CANDIDATES = """November 3 2026 General Election - 11/3/2026
Contests: 3111 to 7886 -
Candidate List
Contest Party Date/Time Qualified
CCCBdEdSchBd2 Vote for 1
SARAH BUTLER 8/ 6/2026 8:24:00 AM
PAMELA WEST 7/27/2026 4:09:00 PM
CCCollege1 Vote for 1
RAQUEL DONOSO 8/ 7/2026 2:01:00 PM
CAMERON SASAI 8/ 6/2026 12:28:00 PM
EastBayMUD3 Vote for 1
DON GRAY 8/ 7/2026 6:28:00 PM
MARGUERITE YOUNG 8/ 7/2026 6:27:00 PM
Page 3 of 9
November 3 2026 General Election - 11/3/2026
PinoleCouncil Vote for 3
TRUC "CHRISTY" LAM-JULIAN 7/22/2026 4:15:00 PM
LIBBY DUARTE 7/23/2026 4:06:00 PM
GABRIEL SANDOVAL 7/27/2026 4:19:00 PM
MATTHEW "MATT" AVERY 8/ 4/2026 9:49:00 AM
TINA BROWN 8/ 6/2026 12:11:00 PM
JOHN DOE (not qualified) 8/ 7/2026 1:00:00 PM
WestCCUSD Area4 Vote for 1
DEMETRIO GONZALEZ HOY 7/14/2026 4:26:00 PM
"""

MEASURES = """Contra Costa County Elections
November 3, 2026 General Election
MEASURE RTM
Regional Transit Measure
Majority Overall Required to pass
Alameda, Contra Costa, San Francisco, San Mateo, Santa Clara
Shall the measure to prevent major service cuts ... be adopted?
MEASUREP
Sales Tax
Shall the City of Hercules enact a one-cent sales tax ...
MEASURE V
Parcel Tax Renewal
55%
Shall West Contra Costa Unified School District renew its parcel tax ...
MEASURE Z
Library Services
Shall the City of Pinole adopt ...
"""

DOCS_HTML = """<ul>
<li><a href="/wp-content/uploads/8-14-26_candidatelist_summary_final.pdf">Candidate Summary List</a></li>
<li><a href="https://www.contracostavote.gov/wp-content/uploads/8-27-26_candidatelist_detail_final.pdf">Candidate Detail List</a></li>
<li><a href="/wp-content/uploads/26Nov03_Measure-Wording-List-1.pdf">List of Local Ballot Measures</a></li>
</ul>"""


class CountyParseTests(unittest.TestCase):
    def test_election_slug(self):
        self.assertEqual(parse_election_slug("november-3-2026-general-election"), (date(2026, 11, 3), "General Election"))
        self.assertEqual(parse_election_slug("https://x/election/june-2-2026-statewide-direct-primary-election/")[0],
                         date(2026, 6, 2))
        self.assertEqual(parse_election_slug("candidates-campaigns-measures"), (None, ""))

    def test_candidate_list(self):
        got = parse_candidate_list(CANDIDATES)
        self.assertEqual([c["code"] for c in got], ["CCCBdEdSchBd2", "CCCollege1", "EastBayMUD3", "PinoleCouncil", "WestCCUSD Area4"])
        council = next(c for c in got if c["code"] == "PinoleCouncil")
        self.assertEqual(council["vote_for"], 3)
        self.assertEqual(len(council["candidates"]), 5)              # the not-qualified filer is dropped
        self.assertEqual(council["candidates"][0], 'TRUC "CHRISTY" LAM-JULIAN')

    def test_document_date(self):
        self.assertEqual(document_date(CANDIDATES), date(2026, 11, 3))
        self.assertTrue(document_mentions(MEASURES, date(2026, 11, 3)))
        self.assertFalse(document_mentions(MEASURES, date(2028, 3, 7)))

    def test_measures(self):
        ms = parse_measures(MEASURES)
        self.assertEqual([m["letter"] for m in ms], ["RTM", "P", "V", "Z"])
        self.assertEqual(ms[0]["title"], "Regional Transit Measure")
        self.assertIn("City of Hercules", ms[1]["text"])

    def test_find_documents(self):
        docs = find_documents(DOCS_HTML, "https://www.contracostavote.gov/elections/x/")
        self.assertEqual(docs["candidates"], "https://www.contracostavote.gov/wp-content/uploads/8-14-26_candidatelist_summary_final.pdf")
        self.assertTrue(docs["measures"].endswith("26Nov03_Measure-Wording-List-1.pdf"))


if __name__ == "__main__":
    unittest.main()
