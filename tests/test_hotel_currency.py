# -*- coding: utf-8 -*-
"""Currency must come from the SOURCE. Accor (price text), Langham (response field), no literal fallbacks in launched harvesters."""
import datetime
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import langham_harvester as lh                   # noqa: E402
from engine.currency_source import currency_from_text, is_iso  # noqa: E402
from engine.extractors import accor as accor_parse            # noqa: E402
from engine.honesty_audit import audit_rows, verdict          # noqa: E402
from engine.schema import create_full_schema                  # noqa: E402


def fut(n):
    return (datetime.date.today() + datetime.timedelta(days=n)).isoformat()


class SourceCurrencyTests(unittest.TestCase):
    def test_reads_codes_and_unambiguous_symbols_only(self):
        self.assertEqual(currency_from_text("IDR 1,318,750"), "IDR")
        self.assertEqual(currency_from_text("€66"), "EUR")
        self.assertEqual(currency_from_text("Rp 769.500"), "IDR")
        self.assertEqual(currency_from_text("US$105"), "USD")
        for ambiguous in ("$66", "¥1200", "kr 500", "", None, "USD 5 / EUR 5"):
            self.assertIsNone(currency_from_text(ambiguous), ambiguous)
        self.assertTrue(is_iso("IDR")) and self.assertFalse(is_iso("Unknown"))


def accor_evidence(days):
    cal = [{"date": d, "availability": {"status": "AVAILABLE"},
            "offer": {"pricing": {"aggregationType": "NIGHT", "main": {"formattedAmount": m}, "alternative": {"formattedAmount": a}}}} for d, m, a in days]
    return json.dumps({"format": "accor-calendar-evidence", "version": 1, "hotel_id": "accor_8455", "source_url": "https://all.accor.com/x",
                       "raw_responses": [{"from": "a", "to": "b", "data": {"data": {"hotelOffers": {"calendar": cal}}}}]}).encode()


class AccorTests(unittest.TestCase):
    def test_currency_is_read_from_price_text_and_harvester_evidence_replays(self):
        rows = accor_parse.parse_evidence(accor_evidence([(fut(2), "IDR 1,318,750", "IDR 1,388,158"), (fut(3), "€66", "€69")]))
        self.assertEqual([(r.cash_rate, r.currency) for r in rows], [(1318750.0, "IDR"), (66.0, "EUR")])

    def test_price_without_a_named_currency_is_skipped_not_defaulted(self):
        rows = accor_parse.parse_evidence(accor_evidence([(fut(2), "$66", "$69"), (fut(3), "66", "69"), (fut(4), "IDR 900,000", None)]))
        self.assertEqual([(r.cash_rate, r.currency) for r in rows], [(900000.0, "IDR")])


class LanghamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = sqlite3.connect(os.path.join(self.tmp.name, "t.db"))
        create_full_schema(self.db)
        self.prop = {"synxis_id": "27406", "name": "THE LANGHAM, LONDON"}

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def run_h(self, post):
        with mock.patch.object(lh, "post_json", post):
            return lh.harvest_property(self.db, self.prop, 1, workspace_dir=self.tmp.name, sleep=lambda s: None)

    def test_writes_server_numbers_and_currency_with_no_fx_or_defaults(self):
        cal = [{"date": fut(2), "amount": 680.83, "amountWithTax": 817, "currency": "GBP"},
               {"date": fut(3), "amount": 712.5, "amountWithTax": 855, "currency": "GBP"}]
        r = self.run_h(lambda payload: (200, {"data": {"calendar": cal}}, ""))
        self.assertEqual((r["written"], r["reason"]), (2, None))
        got = self.db.execute("SELECT stay_date, cash_rate, raw_currency, tax_inclusive FROM rate_records ORDER BY stay_date").fetchall()
        self.assertEqual(got, [(fut(2), 817.0, "GBP", 1), (fut(3), 855.0, "GBP", 1)])
        self.assertEqual(self.db.execute("SELECT city, country, currency FROM hotels").fetchone(), ("Unknown", "Unknown", "GBP"))
        bad = [f for f in audit_rows(self.db, self.tmp.name) if f.level == "FAIL"]
        self.assertEqual(bad, [], bad)

    def test_day_without_currency_is_dropped(self):
        cal = [{"date": fut(2), "amount": 100, "amountWithTax": 120}, {"date": fut(3), "amount": 100, "amountWithTax": 120, "currency": "USD"}]
        r = self.run_h(lambda payload: (200, {"data": {"calendar": cal}}, ""))
        self.assertEqual(r["written"], 1)

    def test_failed_window_is_reported(self):
        r = self.run_h(lambda payload: (500, None, "HTTP 500"))
        self.assertEqual(r["written"], 0)
        self.assertIn("HTTP 500", r["reason"])

    def test_blocked_stops_the_run(self):
        def post(payload):
            raise lh.Blocked("HTTP 429")
        with self.assertRaises(lh.Blocked):
            self.run_h(post)


class NoLiteralCurrencyFallbackTests(unittest.TestCase):
    LAUNCHED = ["accor_fast_harvester", "hilton_fast_harvester", "marriott_fast_harvester", "langham_harvester", "ihg_calendar_harvester",
                "swissbel_harvester", "bestwestern_harvester", "gha_harvester", "radisson_harvester", "wyndham_stream_harvester"]
    PATTERN = re.compile(r"""(or|else)\s+["'](USD|EUR|IDR|GBP|AUD|SGD)["']|get\(\s*["']currency["']\s*,\s*["'][A-Z]{3}["']|default_currency\s*(:\s*str)?\s*=\s*["'][A-Z]{3}["']|FX_RATES""")

    def test_no_default_currency_literal_in_launched_harvesters(self):
        offenders = []
        for name in self.LAUNCHED:
            p = os.path.join(ROOT, "crawlers", name + ".py")
            if os.path.exists(p) and self.PATTERN.search(open(p, encoding="utf-8", errors="ignore").read()):
                offenders.append(name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
