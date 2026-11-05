"""v9f regression tests for the defects measured in the 2026-11-03 test run (python -m unittest discover -s tests -v).

Each test names the live observation it guards against. All offline: no network, no browser.
"""
import os
import sqlite3
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.extractors import gha as gp            # noqa: E402
from engine.extractors import shangrila as sp      # noqa: E402


class _Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._body


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post(self, *a, **k):
        self.calls += 1
        return self.responses.pop(0) if self.responses else _Resp(429)


class AccorRateLimitCircuitBreakerTests(unittest.TestCase):
    """User standard (updated 2026-11-04): Apigee 429 exponential backoff does not recover in-session.
    If HTTP 429 is detected, the scraper stops immediately (circuit breaker) to protect IP reputation."""

    def setUp(self):
        from crawlers import accor_fast_harvester as af
        self.af = af
        self.waits = []
        self.p = mock.patch.object(af.time, "sleep", lambda s: self.waits.append(s))
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def ok(self):
        return _Resp(200, {"data": {"hotelOffers": {"calendar": []}}})

    def test_stops_immediately_on_429_without_retrying_or_pausing(self):
        s = _Session([_Resp(429)])
        f = self.af.Faucet(sleep=lambda x: self.waits.append(x))
        with self.assertRaises(self.af.AccorRateLimitError):
            self.af.harvest_accor_hotel(s, "0338", "q", total_days_target=14, faucet=f)
        self.assertEqual(len(self.waits), 0)  # Immediately raised, no waiting 60s/120s!

    def test_on_429_raises_rate_limit_error(self):
        f = self.af.Faucet(sleep=lambda x: None)
        with self.assertRaises(self.af.AccorRateLimitError):
            f.on_429(None)

    def test_workers_share_the_ip_rate(self):
        self.assertEqual(self.af.Faucet(workers=2).min_interval, 2 * self.af.Faucet.BASE_INTERVAL)

    def test_default_drip_is_below_v9e_rate(self):
        self.assertGreaterEqual(self.af.Faucet.BASE_INTERVAL, 1.35)

    def test_all_requests_failing_is_not_reported_as_success(self):
        res = self.af.harvest_accor_hotel(_Session([_Resp(500)] * 50), "x", "q", total_days_target=28,
                                          faucet=self.af.Faucet(sleep=lambda x: None))
        self.assertEqual(res["ok_responses"], 0)
        self.assertTrue(res["failed_chunks"])


class ShangrilaMemberRateTests(unittest.TestCase):
    """v9f rate rule (user, 2026-11-03): the Shangri-La Circle MEMBER rate (free) is stored; public only as fallback."""

    def payload(self, rates):
        return {"status": 0, "data": {"hotelDetail": {"rooms": [
            {"name": "Deluxe Room", "roomRate": {"canBook": True, "productRates": rates}}]}}}

    def rate(self, code, amount, member=False, cat="standard"):
        r = {"rateCode": code, "rateName": f"{code} rate", "rateCategory": cat,
             "originPrice": {"moneyWithTax": {"amount": amount, "currency": "AUD"}}}
        if member:
            r["slcMemberRate"] = True
        return r

    def test_member_rate_is_chosen(self):
        row, why, *_ = sp.choose_row(self.payload([self.rate("SCZBAR", 294, member=True),
                                                   self.rate("BAR", 320)]), "2027-05-08", "u")
        self.assertIsNotNone(row, why)
        self.assertEqual(row.cash_rate, 294)
        self.assertIn("member rate", row.notes)

    def test_member_rate_preferred_even_if_a_public_plan_is_cheaper(self):
        row, *_ = sp.choose_row(self.payload([self.rate("SCZBAR", 300, member=True),
                                              self.rate("PROMO", 280)]), "2027-05-08", "u")
        self.assertEqual(row.cash_rate, 300)

    def test_public_rate_when_no_member_rate(self):
        row, *_ = sp.choose_row(self.payload([self.rate("BAR", 320), self.rate("FLEX", 340)]), "2027-05-08", "u")
        self.assertEqual(row.cash_rate, 320)
        self.assertNotIn("member rate", row.notes)

    def test_member_detection(self):
        self.assertTrue(sp.is_member_rate({"gcExclusive": True}))
        self.assertTrue(sp.is_member_rate({"rateName": "Members Online Exclusive Rate (King)"}))
        self.assertFalse(sp.is_member_rate({"rateName": "Best Flexible Rate"}))


class GhaRestrictedRateTests(unittest.TestCase):
    """Live 2026-11-03: 12 GHA rows used 'UAE Resident Rate Including Breakfast (LOCALBB)'."""

    def resp(self, rates):
        return {"rooms": [{"roomName": "Guest Room", "rates": rates}]}

    def rate(self, code, name, total, member=False):
        return {"rateCode": code, "rateName": name, "memberRate": member, "amountWithTaxesFees": total,
                "price": total * 0.8, "currency": "AED"}

    def test_resident_rate_is_excluded(self):
        rows = gp.parse_stay_response("2027-09-29", self.resp([
            self.rate("LOCALBB", "UAE Resident Rate Including Breakfast", 500),
            self.rate("RAFL", "Prepay Rate", 694.69)]))
        self.assertEqual([r.cash_rate for r in rows], [694.69])

    def test_restricted_member_plan_is_also_excluded(self):
        rows = gp.parse_stay_response("2027-09-29", self.resp([
            self.rate("LOCALBB", "UAE Resident Rate Including Breakfast", 450, member=True),
            self.rate("RAFL", "Prepay Rate", 694.69)]))
        self.assertEqual([r.cash_rate for r in rows], [694.69])

    def test_only_restricted_rates_gives_no_row(self):
        rows = gp.parse_stay_response("2027-09-29", self.resp([
            self.rate("GOVT1", "Government Rate", 400), self.rate("CORP", "Corporate Rate", 450)]))
        self.assertEqual(rows, [])

    def test_ordinary_public_plans_are_kept(self):
        for name in ("Prepay Rate", "Flexible Rate", "Advance Purchase 3 Days Room Only", "Best Available Rate"):
            self.assertFalse(gp.is_restricted_rate({"rateCode": "X", "rateName": name}), name)


class ExitCodeTests(unittest.TestCase):
    """Live 2026-11-03: Hilton 4/6 hotels FAILED (Akamai) but exit code 0; Accor had no exit code at all."""

    def read(self, rel):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            return f.read()

    def test_harvesters_exit_with_their_result(self):
        self.assertIn("sys.exit(harvest_hilton(", self.read("crawlers/hilton_fast_harvester.py"))
        self.assertIn("sys.exit(harvest_marriott(", self.read("crawlers/marriott_fast_harvester.py"))
        self.assertIn("sys.exit(run_accor_harvester(", self.read("crawlers/accor_fast_harvester.py"))

    def test_marriott_blocked_or_unpriced_calendar_is_a_failure_not_no_availability(self):
        src = self.read("crawlers/marriott_fast_harvester.py")
        self.assertIn('"error": "BLOCKED_AFTER_REFRESH"', src)
        self.assertIn('"error": "DOM_FALLBACK_NO_PRICE_UNVERIFIED"', src)

    def test_marriott_8_workers_no_longer_force_local_proxies(self):
        self.assertNotIn("or args.workers == 8", self.read("crawlers/marriott_fast_harvester.py"))


class HonestyAuditEntryPointTests(unittest.TestCase):
    """Live 2026-11-03: `python -m engine.honesty_audit` exited 0 with no output (no entry point)."""

    def test_cli_runs_and_reports(self):
        import io
        import tempfile
        from contextlib import redirect_stdout
        from engine import honesty_audit
        from engine.schema import create_full_schema
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "t.db")
            c = sqlite3.connect(db)
            create_full_schema(c)
            c.close()
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = honesty_audit.main(["--db", db, "--workspace", d])
            self.assertIn("VERDICT:", buf.getvalue())
            self.assertIn(code, (0, 1, 2))


class RadissonNonHotelTests(unittest.TestCase):
    """Live 2026-11-03: 'asia-pacific', 'europe', 'middle-east-africa', 'central-eastern-southern-europe',
    'choose-your-room' were in the hotel list."""

    def test_region_pages_are_not_hotels(self):
        from crawlers import radisson_harvester as rh
        for s in ("asia-pacific", "europe", "middle-east-africa", "central-eastern-southern-europe", "choose-your-room"):
            self.assertIn(s, rh.NON_HOTEL_SLUGS)


if __name__ == "__main__":
    unittest.main()
