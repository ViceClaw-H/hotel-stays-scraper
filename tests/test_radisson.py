"""Offline tests for the Radisson parser and harvester. Run:  python -m unittest discover -s tests -v

They use a small fixture assembled from values seen in a real response, and a fake fetcher. They check
the behaviours that matter for 'no fabrication': a missing price gives NO row; nothing is defaulted.
"""
import copy
import datetime
import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import radisson_harvester as rh                      # noqa: E402
from engine.extractors import radisson as rp                       # noqa: E402
from engine.schema import create_full_schema                       # noqa: E402

FX = os.path.join(ROOT, "tests", "fixtures")
OBSERVED = "2026-12-10"


def future_date(days=40):
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


def load_stays(date):
    raw = open(os.path.join(FX, "radisson_stays_by_rooms_sample.json"), encoding="utf-8").read().replace(OBSERVED, date)
    d = json.loads(raw)
    d.pop("_comment", None)
    return d


def load_rooms():
    return json.load(open(os.path.join(FX, "radisson_rooms_sample.json"), encoding="utf-8"))


NAMES = rp.room_names(load_rooms())


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.d = future_date()

    def rows(self, resp):
        return {r.room_name: r for r in rp.parse_stay_response(self.d, resp, NAMES)}

    def test_cheapest_member_room_only_and_points_of_same_rate(self):
        # v9f rate rule (user, 2026-11-03): member rate (free to join) is the reference whenever
        # the night offers one -- both rooms in the fixture have a cheaper member rate than public.
        r = self.rows(load_stays(self.d))
        self.assertEqual(set(r), {"Standard Room", "Junior Suite"})
        std = r["Standard Room"]
        self.assertEqual((std.cash_rate, std.currency, std.points_required), (141.75, "EUR", 56504))
        self.assertIn("member rate", std.notes)
        suite = r["Junior Suite"]
        self.assertEqual((suite.cash_rate, suite.points_required), (252.25, 99008))

    def test_public_rate_when_no_member_rate_qualifies(self):
        resp = load_stays(self.d)
        for g in resp["rooms"]["BSTD------"]["groups"]:
            g["staysMember"] = []     # no member rate offered this group
        std = self.rows(resp)["Standard Room"]
        self.assertEqual((std.cash_rate, std.points_required), (165.0, 65771))   # falls back to public
        self.assertIn("public rate", std.notes)

    def test_breakfast_included_rates_are_never_used(self):
        r = self.rows(load_stays(self.d))
        self.assertNotIn(203.0, [x.cash_rate for x in r.values()])    # breakfast included (public)
        self.assertNotIn(232.0, [x.cash_rate for x in r.values()])    # breakfast included (public, flexible)

    def test_restricted_member_rate_without_room_only_flag_is_not_used(self):
        # a staysMember entry that isn't mealPlan RO / breakfastIncluded False must never qualify,
        # even though it is tagged memberOnly -- same room-only discipline as the public pool.
        resp = load_stays(self.d)
        for g in resp["rooms"]["BSTD------"]["groups"]:
            for s in g["staysMember"]:
                s["mealPlan"] = "BB"
                s["breakfastIncluded"] = True
        std = self.rows(resp)["Standard Room"]
        self.assertEqual(std.cash_rate, 165.0)    # member rate no longer qualifies -> falls back to public

    def test_no_qualifying_rate_means_no_row(self):
        resp = load_stays(self.d)
        for g in resp["rooms"]["JJST------"]["groups"]:
            g["staysPublic"] = [s for s in g["staysPublic"] if s["mealPlan"] != "RO"]
            g["staysMember"] = [s for s in g["staysMember"] if s["mealPlan"] != "RO"]
        r = self.rows(resp)
        self.assertEqual(set(r), {"Standard Room"})          # suite has no RO rate in either pool -> no row

    def test_price_not_tax_inclusive_is_skipped(self):
        # member pool cleared so this exercises the public-pool path specifically (member-pool
        # fabrication checks have their own tests below)
        resp = load_stays(self.d)
        for g in resp["rooms"]["BSTD------"]["groups"]:
            g["staysMember"] = []
            for s in g["staysPublic"]:
                s["nights"][0]["pricing"]["price"]["isTaxInclusive"] = False
        self.assertNotIn("Standard Room", self.rows(resp))

    def test_night_must_match_requested_date(self):
        resp = load_stays(future_date(41))                              # server priced another night
        self.assertEqual(self.rows(resp), {})

    def test_missing_or_zero_price_gives_no_row(self):
        resp = load_stays(self.d)
        for g in resp["rooms"]["BSTD------"]["groups"]:
            g["staysMember"] = []
            for s in g["staysPublic"]:
                s["nights"][0]["pricing"]["price"]["amount"] = 0
        self.assertNotIn("Standard Room", self.rows(resp))

    def test_points_only_when_redeemable_and_no_extra_cash(self):
        resp = load_stays(self.d)
        for g in resp["rooms"]["BSTD------"]["groups"]:
            g["staysMember"] = []     # member rate would otherwise be the one actually chosen
        s = next(x for g in resp["rooms"]["BSTD------"]["groups"] for x in g["staysPublic"] if x["code"] == "P_PP01" and x["mealPlan"] == "RO")
        s["redeemable"] = False
        self.assertIsNone(self.rows(resp)["Standard Room"].points_required)
        s["redeemable"] = True
        s["nights"][0]["pricing"]["cashWithPoints"]["extraCashAmount"] = 12.5
        self.assertIsNone(self.rows(resp)["Standard Room"].points_required)

    def test_member_points_only_when_redeemable_and_no_extra_cash(self):
        # same "no fabrication" discipline must hold for the member pool, since it's preferred
        resp = load_stays(self.d)
        s = next(x for g in resp["rooms"]["BSTD------"]["groups"] for x in g["staysMember"] if x["code"] == "P_PP01RR")
        s["redeemable"] = False
        self.assertIsNone(self.rows(resp)["Standard Room"].points_required)
        s["redeemable"] = True
        s["nights"][0]["pricing"]["cashWithPoints"]["extraCashAmount"] = 12.5
        self.assertIsNone(self.rows(resp)["Standard Room"].points_required)

    def test_unknown_room_name_is_labelled_unknown_not_guessed(self):
        rows = rp.parse_stay_response(self.d, load_stays(self.d), {})
        self.assertTrue(all(r.room_name.startswith("UNKNOWN") for r in rows))

    def test_garbage_responses_give_no_rows(self):
        for bad in (None, {}, {"rooms": []}, {"rooms": {"X": 5}}, "text"):
            self.assertEqual(rp.parse_stay_response(self.d, bad, NAMES), [])


class FakeFetcher:
    def __init__(self, stays_status=200, hotel_status=200, code="DEUWEBCK"):
        self.stays_status, self.hotel_status, self.code, self.calls = stays_status, hotel_status, code, []

    def hotel_info(self, slug):
        return {"status": self.hotel_status, "code": self.code if self.hotel_status == 200 else None,
                "ld": {"name": "Radisson Blu Schwarzer Bock Hotel, Wiesbaden",
                       "address": {"addressLocality": "Wiesbaden", "addressCountry": "DE"}}}

    def rooms(self, code):
        return {"status": 200, "text": json.dumps(load_rooms())}

    def stays(self, code, check_in, check_out, adults=2):
        self.calls.append(check_in)
        if self.stays_status != 200:
            return {"status": self.stays_status, "text": '{"title":"error"}'}
        return {"status": 200, "text": json.dumps(load_stays(check_in))}


class HarvestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = sqlite3.connect(os.path.join(self.tmp.name, "t.db"))
        create_full_schema(self.db)
        rh.ingest_radisson_roster(self.db, ["radisson-blu-wiesbaden-schwarzer-bock"])
        self.hid = "rad_radisson_blu_wiesbaden_schwarzer_bock"

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def run_h(self, fetcher, dates):
        return rh.harvest_hotel(fetcher, self.db, self.hid, "radisson-blu-wiesbaden-schwarzer-bock", dates,
                                workspace_dir=self.tmp.name, sleep=lambda s: None)

    def test_writes_rows_evidence_and_real_hotel_facts(self):
        dates = [future_date(30), future_date(60)]
        r = self.run_h(FakeFetcher(), dates)
        self.assertEqual(r["written"], 4)                               # 2 rooms x 2 dates
        n = self.db.execute("SELECT COUNT(*), MIN(cash_rate), MAX(points_required) FROM rate_records").fetchone()
        self.assertEqual(n, (4, 141.75, 99008))      # member rate (cheaper than public) on both rooms
        ev = self.db.execute("SELECT evidence_file FROM evidence_registry").fetchone()[0]
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, ev)))
        city, country, ccy = self.db.execute("SELECT city, country, currency FROM hotels WHERE id=?", (self.hid,)).fetchone()
        self.assertEqual((city, country, ccy), ("Wiesbaden", "DE", "EUR"))   # read from the site, not guessed

    def test_roster_does_not_guess_city_or_currency(self):
        db2 = sqlite3.connect(":memory:")
        create_full_schema(db2)
        rh.ingest_radisson_roster(db2, ["some-hotel"])
        self.assertEqual(db2.execute("SELECT city, country, currency FROM hotels").fetchone(), ("Unknown", "Unknown", "Unknown"))

    def test_server_errors_write_nothing_and_stop_early(self):
        f = FakeFetcher(stays_status=500)
        r = self.run_h(f, [future_date(i) for i in range(20, 60, 5)])
        self.assertEqual(r["written"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM rate_records").fetchone()[0], 0)
        self.assertEqual(len(f.calls), rh.MAX_CONSECUTIVE_FAILURES)    # did not hammer the site

    def test_blocked_site_raises(self):
        with self.assertRaises(rh.Blocked):
            self.run_h(FakeFetcher(stays_status=403), [future_date(30)])

    def test_hotel_without_code_is_skipped(self):
        r = self.run_h(FakeFetcher(hotel_status=404), [future_date(30)])
        self.assertEqual(r["written"], 0)
        self.assertIn("no hotel code", r["skipped_reason"])

    def test_evidence_replays_to_the_same_rows(self):
        d = future_date(30)
        self.run_h(FakeFetcher(), [d])
        ev = self.db.execute("SELECT evidence_file FROM evidence_registry").fetchone()[0]
        replay = rp.parse_evidence(open(os.path.join(self.tmp.name, ev), "rb").read())
        stored = self.db.execute("SELECT stay_date, cash_rate, points_required, room_name FROM rate_records ORDER BY room_name").fetchall()
        self.assertEqual(sorted((r.stay_date, r.cash_rate, r.points_required, r.room_name) for r in replay), sorted(stored))


class DateTests(unittest.TestCase):
    def test_choose_dates(self):
        t = datetime.date(2026, 11, 2)
        d = rh.choose_dates(12, 330, today=t)
        self.assertEqual((d[0], d[-1], len(d)), ("2026-11-03", (t + datetime.timedelta(days=330)).isoformat(), 12))
        self.assertEqual(d, sorted(set(d)))
        self.assertEqual(rh.choose_dates(1, 330, today=t), ["2026-11-03"])


if __name__ == "__main__":
    unittest.main()
