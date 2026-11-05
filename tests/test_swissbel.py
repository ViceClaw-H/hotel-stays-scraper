"""Offline tests for the Swiss-Belhotel parser/harvester. Run:  python -m unittest discover -s tests -v

Fixture values were observed live (see tests/fixtures/swissbel_observed.json). The point of these tests: the script must
NEVER add or guess a tax, must keep the server's responses verbatim as evidence, and must write NOTHING when the hotel's own
tax endpoint says taxes are charged on top, fails, or disagrees between rates.
"""
import copy
import datetime
import gzip
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import swissbel_harvester as sbh        # noqa: E402
from engine.extractors import swissbel as sbp         # noqa: E402
from engine.honesty_audit import audit_rows, verdict  # noqa: E402
from engine.schema import create_full_schema          # noqa: E402

FX = json.load(open(os.path.join(ROOT, "tests", "fixtures", "swissbel_observed.json"), encoding="utf-8"))


def fut(n):
    return (datetime.date.today() + datetime.timedelta(days=n)).isoformat()


def calendar(n=3, base=None):
    """real observed numbers (Ambon, IDR), re-dated into the future; pass base=[...] for another currency's scale"""
    base = (base or [591736, 674380, 580000])[:n]
    return {fut(i + 2): {"min_rate": v, "min_los": 1, "cta": False, "ctd": False} for i, v in enumerate(base)}


def probe(resp, status=200, room="r1", rate="t1"):
    return {"room_id": room, "rate_id": rate, "check_in": fut(2), "check_out": fut(3), "status": status, "response": resp}


def evidence(cur, cal, probes):
    return sbh.build_evidence("swiss_x", "pid", cur, "https://example/calendar", cal, probes, harvested_at="2026-11-02T00:00:00Z")


class ParserTests(unittest.TestCase):
    def test_price_is_final_when_server_reports_no_extra_tax(self):
        cal = calendar()
        rows = sbp.parse_evidence(evidence(FX["currency_aud"], cal, [probe(FX["taxes_included_gst"]), probe(FX["taxes_included_gst"], room="r2", rate="t2")]))
        self.assertEqual(len(rows), 3)
        self.assertEqual([r.cash_rate for r in rows], [591736.0, 674380.0, 580000.0])      # exactly the server's number
        self.assertTrue(all(r.currency == "AUD" for r in rows))
        self.assertTrue(all(r.room_name.startswith("UNKNOWN") for r in rows))

    def test_excluded_taxes_with_official_cost_produces_all_in_row_for_matching_date(self):
        cal = calendar()
        # probe has check_in = fut(2). min_rate for fut(2) is 591736.
        # FX["taxes_excluded_idr"] has service-charge: 75165.3, vat: 82681.83 (sum: 157847.13)
        rows = sbp.parse_evidence(evidence(FX["currency_idr"], cal, [probe(FX["taxes_excluded_idr"])]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].stay_date, fut(2))
        self.assertEqual(rows[0].cash_rate, 749583.13)
        self.assertEqual(rows[0].currency, "IDR")
        self.assertIn("service-charge", rows[0].notes)
        self.assertIn("vat", rows[0].notes)

    def test_excluded_taxes_without_numeric_cost_gives_no_rows(self):
        bad_tax = {"included": [], "excluded": [{"name": "service-charge"}], "to_be_paid_later": []}
        rows = sbp.parse_evidence(evidence(FX["currency_idr"], calendar(), [probe(bad_tax)]))
        self.assertEqual(rows, [])

    def test_failed_or_missing_probe_means_no_rows(self):
        self.assertEqual(sbp.parse_evidence(evidence(FX["currency_idr"], calendar(), [probe(None, status=404)])), [])
        self.assertEqual(sbp.parse_evidence(evidence(FX["currency_idr"], calendar(), [])), [])

    def test_probes_that_disagree_mean_no_rows(self):
        ev = evidence(FX["currency_idr"], calendar(), [probe(FX["taxes_included_gst"]), probe(FX["taxes_excluded_idr"], room="r2", rate="t2")])
        self.assertEqual(sbp.parse_evidence(ev), [])

    def test_payable_later_charges_mean_no_rows(self):
        tx = copy.deepcopy(FX["taxes_included_gst"]); tx["to_be_paid_later"] = [{"name": "city-tax", "cost": 3}]
        self.assertEqual(sbp.parse_evidence(evidence(FX["currency_aud"], calendar(), [probe(tx)])), [])

    def test_no_currency_means_no_rows(self):
        self.assertEqual(sbp.parse_evidence(evidence(None, calendar(), [probe(FX["taxes_included_gst"])])), [])
        self.assertEqual(sbp.parse_evidence(evidence({"code": "dollars"}, calendar(), [probe(FX["taxes_included_gst"])])), [])

    def test_zero_or_missing_price_gives_no_row(self):
        cal = {fut(2): {"min_rate": 0}, fut(3): {"min_rate": None}, fut(4): {"min_rate": 500}, "not-a-date": {"min_rate": 9}}
        rows = sbp.parse_evidence(evidence(FX["currency_aud"], cal, [probe(FX["taxes_included_gst"])]))
        self.assertEqual([(r.stay_date, r.cash_rate) for r in rows], [(fut(4), 500.0)])

    def test_legacy_evidence_still_replays(self):
        legacy = json.dumps({fut(2): {"min_rate": 100, "all_in_rate": 120.0}}).encode()
        self.assertEqual([r.cash_rate for r in sbp.parse_evidence(legacy)], [120.0])

    def test_unknown_version_is_rejected(self):
        doc = json.loads(gzip.decompress(evidence(FX["currency_aud"], calendar(), [probe(FX["taxes_included_gst"])])))
        doc["version"] = 99
        with self.assertRaises(ValueError):
            sbp.parse_evidence(json.dumps(doc).encode())


class HarvestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = sqlite3.connect(os.path.join(self.tmp.name, "t.db"))
        create_full_schema(self.db)
        self.prop = {"id": "pid-1", "name": "Swiss-Belhotel Test"}

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def fake(self, currency, tax, cal=None, detail_ok=True):
        cal = calendar() if cal is None else cal
        detail = {"default_currency": currency, "rooms": [{"id": "r1"}, {"id": "r2"}], "rates": [{"id": "t1"}, {"id": "t2"}]} if detail_ok else {}

        def get_json(url):
            if "/taxes" in url:
                return 200, tax
            if "/calendar" in url:
                return 200, cal
            if url.rstrip("/").endswith("/properties/pid-1"):
                return 200, detail
            return 404, None
        return get_json

    def run_h(self, get_json):
        with mock.patch.object(sbh, "get_json", get_json):
            return sbh.harvest_property(self.db, self.prop, 30, workspace_dir=self.tmp.name, sleep=lambda s: None)

    def test_final_price_hotel_writes_server_numbers_and_verbatim_evidence(self):
        cal = calendar(base=[776, 812, 790])                                  # Sydney scale (776 AUD observed)
        r = self.run_h(self.fake(FX["currency_aud"], FX["taxes_included_gst"], cal))
        self.assertEqual((r["written"], r["reason"]), (3, None))
        got = self.db.execute("SELECT stay_date, cash_rate, raw_currency, tax_inclusive FROM rate_records ORDER BY stay_date").fetchall()
        self.assertEqual(got, [(d, float(v["min_rate"]), "AUD", 1) for d, v in sorted(cal.items())])
        ev_rel = self.db.execute("SELECT evidence_file FROM rate_records LIMIT 1").fetchone()[0]
        doc = json.loads(gzip.decompress(open(os.path.join(self.tmp.name, ev_rel), "rb").read()))
        self.assertEqual(doc["calendar_response"], cal)                       # verbatim: nothing added to the server's answer
        self.assertEqual(len(doc["tax_probes"]), 2)
        self.assertEqual(verdict(audit_rows(self.db, self.tmp.name)), "PASS" if not any(
            f.level == "WARN" for f in audit_rows(self.db, self.tmp.name)) else "WARN")
        self.assertEqual(self.db.execute("SELECT currency FROM hotels").fetchone()[0], "AUD")

    def test_taxes_on_top_writes_all_in_rows_with_server_cost(self):
        r = self.run_h(self.fake(FX["currency_idr"], FX["taxes_excluded_idr"]))
        self.assertEqual(r["written"], 3)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM rate_records").fetchone()[0], 3)
        row = self.db.execute("SELECT cash_rate, raw_currency FROM rate_records ORDER BY stay_date LIMIT 1").fetchone()
        self.assertEqual(row, (749583.13, "IDR"))

    def test_taxes_with_missing_cost_fails_closed_zero_rows(self):
        bad_tax = {"included": [], "excluded": [{"name": "vat"}], "to_be_paid_later": []}
        r = self.run_h(self.fake(FX["currency_idr"], bad_tax))
        self.assertEqual(r["written"], 0)
        self.assertIn("cost", r["reason"].lower())

    def test_no_currency_in_detail_means_zero_rows(self):
        r = self.run_h(self.fake(None, FX["taxes_included_gst"], detail_ok=False))
        self.assertEqual(r["written"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM rate_records").fetchone()[0], 0)

    def test_roster_never_guesses_city_country_currency(self):
        sbh.match_or_register_hotel(self.db, {"name": "Brand New Swiss Hotel"})
        self.assertEqual(self.db.execute("SELECT city, country, currency FROM hotels").fetchone(), ("Unknown", "Unknown", "Unknown"))


if __name__ == "__main__":
    unittest.main()
