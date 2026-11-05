"""Offline tests for the GHA parser and harvester (python -m unittest discover -s tests -v)."""
import datetime
import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import gha_harvester as gh        # noqa: E402
from engine.extractors import gha as gp         # noqa: E402
from engine.schema import create_full_schema    # noqa: E402

FX = os.path.join(ROOT, "tests", "fixtures", "gha_rooms_rates_sample.json")


def sample():
    with open(FX, encoding="utf-8") as f:
        d = json.load(f)
    d.pop("_comment", None)
    return d


def future(days=40):
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


class ParserTests(unittest.TestCase):
    def rows(self, resp):
        return {r.room_name: r for r in gp.parse_stay_response(future(), resp)}

    # v9f rate rule (user, 2026-11-03): MEMBER rate first (GHA DISCOVERY is free), public rate only as fallback.
    def test_member_rate_is_stored_with_taxes_and_fees(self):
        r = self.rows(sample())
        self.assertEqual(set(r), {"Deluxe Room King", "Premier Room King", "Presidential Suite"})
        k = r["Deluxe Room King"]
        self.assertEqual((k.cash_rate, k.currency, k.points_required), (3009.88, "AED", None))
        self.assertIn("member rate", k.notes)
        self.assertEqual(r["Presidential Suite"].cash_rate, 33634.88)

    def test_public_discount_does_not_replace_member_rate(self):
        prices = [x.cash_rate for x in self.rows(sample()).values()]
        self.assertNotIn(2660.4, prices)       # public advance-purchase plan: not the member rate

    def test_no_member_rate_falls_back_to_public_daily(self):
        resp = sample()
        resp["rooms"][0]["rates"] = [x for x in resp["rooms"][0]["rates"] if x.get("memberRate") is False]
        row = self.rows(resp)["Deluxe Room King"]
        self.assertEqual(row.cash_rate, 3129.88)
        self.assertIn("no member rate offered", row.notes)

    def test_no_member_and_no_daily_falls_back_to_cheapest_public_and_says_so(self):
        # measured live 2026-11-03: Rotana/Anantara hotels have public rates but no code DAILY
        resp = sample()
        resp["rooms"][0]["rates"] = [x for x in resp["rooms"][0]["rates"]
                                     if x.get("memberRate") is False and x["rateCode"] != "DAILY"]
        row = self.rows(resp)["Deluxe Room King"]
        self.assertEqual(row.cash_rate, 2660.4)
        self.assertIn("no DAILY rate offered", row.notes)

    def test_bad_numbers_give_no_row(self):
        for bad in (None, "", "abc", "0", "-5", True):
            resp = sample()
            for x in resp["rooms"][0]["rates"]:
                x["amountWithTaxesFees"] = bad
            self.assertNotIn("Deluxe Room King", self.rows(resp), msg=f"value {bad!r}")

    def test_total_below_pre_tax_price_is_rejected(self):
        resp = sample()
        for x in resp["rooms"][0]["rates"]:
            x["amountWithTaxesFees"] = "100"
        self.assertNotIn("Deluxe Room King", self.rows(resp))

    def test_missing_currency_gives_no_row(self):
        resp = sample()
        for x in resp["rooms"][0]["rates"]:
            x.pop("currency")
        self.assertNotIn("Deluxe Room King", self.rows(resp))

    def test_garbage(self):
        for bad in (None, {}, {"rooms": {}}, {"rooms": [1, "x", {}]}, "t"):
            self.assertEqual(gp.parse_stay_response(future(), bad), [])


class FakeFetcher:
    def __init__(self, status=200, ids=True):
        self.status, self.ids, self.calls = status, ids, []

    def hotel_info(self, path):
        page = {"name": "Kempinski The Boulevard Dubai", "city": "Dubai", "country": "United Arab Emirates",
                "hotelCode": "KIDXB10", "brandCode": "KI", "chainId": "21630" if self.ids else None, "hotelId": "45437" if self.ids else None}
        return {"status": 200, "page": page}

    def rates(self, ids, check_in, check_out, adults=2):
        self.calls.append(check_in)
        if self.status != 200:
            return {"status": self.status, "text": "{}"}
        return {"status": 200, "text": json.dumps(sample())}


class HarvestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = sqlite3.connect(os.path.join(self.tmp.name, "t.db"))
        create_full_schema(self.db)
        self.db.execute("INSERT INTO hotels (id, brand, name, city, country, currency, loyalty_model, track_points, official_url) "
                        "VALUES ('gha_k', 'GHA', 'x', 'Unknown', 'Unknown', 'Unknown', 'CASH_REBATE', 0, 'https://www.ghadiscovery.com/kempinski/kempinski-the-boulevard-dubai')")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def run_h(self, f, dates):
        return gh.harvest_hotel(f, self.db, "gha_k", "kempinski/kempinski-the-boulevard-dubai", dates,
                                workspace_dir=self.tmp.name, sleep=lambda s: None)

    def test_rows_evidence_and_facts(self):
        r = self.run_h(FakeFetcher(), [future(30), future(60)])
        self.assertEqual(r["written"], 6)
        self.assertEqual(self.db.execute("SELECT COUNT(*), MIN(cash_rate) FROM rate_records").fetchone(), (6, 3009.88))   # v9f: member rate first
        ev = self.db.execute("SELECT evidence_file FROM evidence_registry").fetchone()[0]
        self.assertTrue(ev.endswith(".json.gz") and os.path.exists(os.path.join(self.tmp.name, ev)))
        self.assertEqual(self.db.execute("SELECT city, country, currency FROM hotels").fetchone(), ("Dubai", "United Arab Emirates", "AED"))

    def test_evidence_replays_to_same_rows(self):
        self.run_h(FakeFetcher(), [future(30)])
        ev = self.db.execute("SELECT evidence_file FROM evidence_registry").fetchone()[0]
        with open(os.path.join(self.tmp.name, ev), "rb") as f:
            replay = gp.parse_evidence(f.read())
        stored = self.db.execute("SELECT stay_date, cash_rate, points_required, room_name FROM rate_records").fetchall()
        self.assertEqual(sorted((r.stay_date, r.cash_rate, r.points_required, r.room_name) for r in replay), sorted(stored))

    def test_non_synxis_hotel_is_skipped_not_guessed(self):
        r = self.run_h(FakeFetcher(ids=False), [future(30)])
        self.assertEqual(r["written"], 0)
        self.assertIn("not on GHA's SynXis", r["skipped_reason"])

    def test_errors_write_nothing_and_stop(self):
        f = FakeFetcher(status=500)
        r = self.run_h(f, [future(i) for i in range(20, 70, 5)])
        self.assertEqual(r["written"], 0)
        self.assertEqual(len(f.calls), gh.MAX_CONSECUTIVE_FAILURES)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM rate_records").fetchone()[0], 0)

    def test_blocked(self):
        with self.assertRaises(gh.Blocked):
            self.run_h(FakeFetcher(status=429), [future(30)])

    def test_page_path(self):
        self.assertEqual(gh.page_path("https://www.ghadiscovery.com/kempinski/kempinski-the-boulevard-dubai"), "kempinski/kempinski-the-boulevard-dubai")
        self.assertIsNone(gh.page_path("https://www.ghadiscovery.com/only-one"))


if __name__ == "__main__":
    unittest.main()
