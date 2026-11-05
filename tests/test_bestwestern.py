"""Best Western: the harvester must never store a pre-tax figure as a tax-inclusive price."""
import datetime
import glob
import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import bestwestern_harvester as bw    # noqa: E402
from engine.schema import create_full_schema        # noqa: E402

REAL = sorted(glob.glob(os.path.join(ROOT, "evidence", "bestwestern", "raw", "*.json")))


def response_text(taxed=None):
    """A Best Western BFF response shaped like the real ones (hotel fields trimmed)."""
    hotel = {"resort": "99999",
             "resortSummary": {"resort": "99999", "name": "Best Western Test Inn", "latitude": 1.0, "longitude": 2.0,
                               "currencyCode": "EUR", "city": "Amsterdam", "country": "Netherlands"},
             "resortSearchRate": {"totalAmount": 3815352.27, "totalAmountWithFeesAndTaxes": None,
                                  "averageNightlyRate": 3815352.27, "averageNightlyAmountWithFeesAndTaxes": taxed,
                                  "resortRoomCategory": "2216780"},
             "resortSearchPoint": None}
    return json.dumps({"data": {"searchHotels": {"taxesAndFeesAvailable": taxed is not None, "hotels": [hotel]}}})


class BwTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "t.db")
        c = sqlite3.connect(self.db_path)
        create_full_schema(c)
        c.execute("ALTER TABLE hotels ADD COLUMN lifecycle_status TEXT DEFAULT 'ACTIVE'")   # columns the real database has
        c.execute("ALTER TABLE hotels ADD COLUMN status_updated_at TEXT")
        c.commit()
        c.close()
        self.old = (bw.DB_PATH, bw.EVIDENCE_DIR, bw.search_cluster_rates, bw.time.sleep)
        bw.DB_PATH, bw.EVIDENCE_DIR = self.db_path, self.tmp.name
        bw.time.sleep = lambda s: None

    def tearDown(self):
        bw.DB_PATH, bw.EVIDENCE_DIR, bw.search_cluster_rates, bw.time.sleep = self.old
        self.tmp.cleanup()

    def fake(self, taxed):
        text = response_text(taxed)
        bw.search_cluster_rates = lambda *a, **k: (text, json.loads(text)["data"]["searchHotels"]["hotels"])

    def count(self):
        c = sqlite3.connect(self.db_path)
        n = c.execute("SELECT COUNT(*) FROM rate_records").fetchone()[0]
        c.close()
        return n

    def test_pre_tax_only_response_stores_nothing_and_exits_1(self):
        self.fake(None)
        with self.assertRaises(SystemExit) as cm:
            bw.harvest_and_record_bestwestern(limit_hubs=1, grid_months=2)
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(self.count(), 0)

    def test_tax_inclusive_price_is_stored_with_unknown_room_and_native_hotel_currency(self):
        self.fake(4_321_000.0)
        bw.harvest_and_record_bestwestern(limit_hubs=1, grid_months=1)
        c = sqlite3.connect(self.db_path)
        cash, ccy, taxinc, room, rclass = c.execute("SELECT cash_rate, raw_currency, tax_inclusive, room_name, room_class FROM rate_records LIMIT 1").fetchone()
        hcur = c.execute("SELECT currency FROM hotels WHERE id='bw_99999'").fetchone()[0]
        c.close()
        self.assertEqual((cash, ccy, taxinc), (4_321_000.0, "IDR", 1))
        self.assertTrue(room.startswith("UNKNOWN") and rclass == "UNKNOWN")      # no invented 'Standard Room'
        self.assertEqual(hcur, "EUR")                                            # hotel's own currency, not a guessed IDR

    @unittest.skipUnless(REAL, "no shipped real evidence")
    def test_every_shipped_real_response_is_pre_tax_only(self):
        """Documents the finding: in the real Best Western evidence the tax-inclusive field is always empty."""
        taxed = 0
        for f in REAL:
            with open(f, encoding="utf-8") as fh:
                doc = json.load(fh)
            # v9f: only cluster-search responses are relevant; other evidence written by later live runs is skipped
            hotels = (((doc.get("data") or {}).get("searchHotels") or {}).get("hotels")) if isinstance(doc, dict) else None
            for h in hotels or []:
                    if h["resortSearchRate"].get("averageNightlyAmountWithFeesAndTaxes") is not None:
                        taxed += 1
        self.assertEqual(taxed, 0)


if __name__ == "__main__":
    unittest.main()
