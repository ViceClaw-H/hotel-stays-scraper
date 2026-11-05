"""Offline tests for engine/honesty_audit.py and tools/check_one_hotel.py (with fake chain scripts)."""
import datetime
import gzip
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.honesty_audit import audit_rows, verdict, scan_evidence_keys  # noqa: E402
from engine.rate_writer import RateRow, write_rate_batch                  # noqa: E402
from engine.schema import create_full_schema                               # noqa: E402
from tools import check_one_hotel as cho                                   # noqa: E402


def fut(n):
    return (datetime.date.today() + datetime.timedelta(days=n)).isoformat()


GOOD = {"calendar_response": {"2026-11-03": {"min_rate": 1, "min_los": 1}}}


def ev_bytes(obj):
    return json.dumps(obj).encode()


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = sqlite3.connect(os.path.join(self.tmp.name, "t.db"))
        create_full_schema(self.db)
        for h in ("swiss_a", "swiss_b"):
            self.db.execute("INSERT INTO hotels (id, brand, name, city, country, currency, loyalty_model, award_category, track_points, official_url) "
                            "VALUES (?, 'SWISS_BELHOTEL', ?, 'Unknown', 'Unknown', 'IDR', 'X', 'STANDARD', 0, 'https://www.swiss-belhotel.com/')", (h, h))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def write(self, hotel, prices, evidence, points_only=False, room="UNKNOWN (test)"):
        rows = [RateRow(stay_date=fut(5 + i), room_name=room, cash_rate=None if points_only else p, currency=None if points_only else "IDR",
                        points_required=1000 + i if points_only else None) for i, p in enumerate(prices)]
        return write_rate_batch(self.db, hotel_id=hotel, source_type="OFFICIAL_SWISSBEL_CRS", source_url="https://ibe-api.hotelchamp.io/api/v1/x",
                                rows=rows, evidence_relpath=f"evidence/t/raw/{hotel}.json", evidence_bytes=ev_bytes(evidence),
                                evidence_grade="RAW", workspace_dir=self.tmp.name)

    def codes(self):
        return {f.code for f in audit_rows(self.db, self.tmp.name)}

    def test_clean_rows_pass(self):
        self.write("swiss_a", [500000 + i * 1000 for i in range(5)], GOOD)
        self.assertEqual(verdict(audit_rows(self.db, self.tmp.name)), "PASS")

    def test_script_added_keys_in_evidence_fail(self):
        self.write("swiss_a", [500000 + i for i in range(5)], {"2026-11-03": {"min_rate": 100, "all_in_rate": 120, "excluded_taxes": 20, "base_min_rate": 100}})
        f = audit_rows(self.db, self.tmp.name)
        self.assertEqual(verdict(f), "FAIL")
        self.assertIn("EVIDENCE_NOT_VERBATIM", {x.code for x in f})

    def test_points_only_rows_need_no_tax_or_currency(self):
        self.write("swiss_a", [None] * 4, GOOD, points_only=True)
        self.assertEqual(verdict(audit_rows(self.db, self.tmp.name)), "PASS")
        self.assertIn("POINTS_ONLY_ROWS", self.codes())

    def test_too_uniform_prices_warn(self):
        self.write("swiss_a", [500000] * 16, GOOD)
        self.assertEqual(verdict(audit_rows(self.db, self.tmp.name)), "WARN")
        self.assertIn("TOO_UNIFORM", self.codes())

    def test_same_tax_ratio_in_different_hotels_warns(self):
        recs = [{"date": f"d{i}", "subtotal": 100.0 + i, "estimated_taxes": round((100.0 + i) * 0.1, 2)} for i in range(12)]
        self.write("swiss_a", [500000 + i for i in range(5)], {"records": recs})
        self.write("swiss_b", [510000 + i for i in range(5)], {"records": recs})
        c = self.codes()
        self.assertIn("CONSTANT_TAX_RATIO", c)
        self.assertIn("ESTIMATED_KEY", c)

    def test_forbidden_note_fails(self):
        self.write("swiss_a", [500000 + i for i in range(3)], GOOD)
        self.db.execute("UPDATE rate_records SET notes = 'estimated total'")
        self.db.commit()
        self.assertIn("FORBIDDEN_NOTE", self.codes())

    def test_missing_evidence_file_fails(self):
        self.write("swiss_a", [500000 + i for i in range(3)], GOOD)
        os.remove(os.path.join(self.tmp.name, "evidence/t/raw/swiss_a.json"))
        self.assertIn("EVIDENCE_MISSING", self.codes())

    def test_no_rows_fails(self):
        self.assertEqual(verdict(audit_rows(self.db, self.tmp.name)), "FAIL")

    def test_key_scanner_sees_nested_keys_and_gz(self):
        k = scan_evidence_keys({"a": [{"b": {"all_in_rate": 1, "estimated_taxes": 2}}]})
        self.assertEqual((k["script_added"], k["estimated"]), ({"all_in_rate"}, {"estimated_taxes"}))


FAKE_TEMPLATE = textwrap.dedent('''
    import os, sys, json, sqlite3, datetime
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, BASE)
    from engine.rate_writer import RateRow, write_rate_batch
    conn = sqlite3.connect(os.path.join(BASE, "hotel_stays.db"))
    MODE = "%MODE%"
    if MODE == "empty":
        print("[!] 0 baris: tidak ada yang dikarang."); sys.exit(1)
    from engine.extractors import swissbel as sbp
    d = (datetime.date.today() + datetime.timedelta(days=9)).isoformat()
    server = {"min_rate": 500000, "min_los": 1}
    if MODE == "bad":
        server = dict(server, all_in_rate=600000, excluded_taxes=100000)       # a script mutating the server's answer
    doc = {"format": "swissbel-calendar-evidence", "version": 1, "hotel_id": "swiss_fake", "property_id": "p", "harvested_at": "2026-11-02T00:00:00Z",
           "currency": {"code": "IDR"}, "calendar_url": "https://ibe-api.hotelchamp.io/api/v1/x", "calendar_response": {d: server},
           "tax_probes": [{"room_id": "r", "rate_id": "t", "check_in": d, "check_out": d, "status": 200,
                           "response": {"included": [{"name": "gst", "cost": 1}], "excluded": [], "to_be_paid_later": []}}]}
    ev = json.dumps(doc).encode()
    rows = sbp.parse_evidence(ev)
    r = write_rate_batch(conn, hotel_id="swiss_fake", source_type="OFFICIAL_SWISSBEL_CRS", source_url="https://ibe-api.hotelchamp.io/api/v1/x",
                         rows=rows, evidence_relpath="evidence/swissbel/raw/swiss_fake.json", evidence_bytes=ev, evidence_grade="RAW", workspace_dir=BASE)
    print("written", r.written)
''')


class CheckToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.proj, "crawlers"))
        shutil.copytree(os.path.join(ROOT, "engine"), os.path.join(self.proj, "engine"), ignore=shutil.ignore_patterns("__pycache__"))
        for pkg in ("database", "core"):
            if os.path.isdir(os.path.join(ROOT, pkg)):
                shutil.copytree(os.path.join(ROOT, pkg), os.path.join(self.proj, pkg), ignore=shutil.ignore_patterns("__pycache__"))
        c = sqlite3.connect(os.path.join(self.proj, "hotel_stays.db"))
        create_full_schema(c)
        c.execute("INSERT INTO hotels (id, brand, name, city, country, currency, loyalty_model, award_category, track_points, official_url) "
                  "VALUES ('swiss_fake', 'SWISS_BELHOTEL', 'Fake', 'Unknown', 'Unknown', 'IDR', 'X', 'STANDARD', 0, 'https://www.swiss-belhotel.com/')")
        c.commit(); c.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_fake(self, mode):
        open(os.path.join(self.proj, "crawlers", f"fake_{mode}.py"), "w", encoding="utf-8").write(FAKE_TEMPLATE.replace("%MODE%", mode))
        return cho.run_chain("fake", project_root=self.proj, script=f"crawlers/fake_{mode}.py", args=[], timeout=120, say=lambda *_: None)

    def test_honest_script_passes_and_real_db_is_untouched(self):
        v, lines = self.run_fake("ok")
        self.assertIn(v, ("PASS", "WARN"), "\n".join(lines))
        n = sqlite3.connect(os.path.join(self.proj, "hotel_stays.db")).execute("SELECT COUNT(*) FROM rate_records").fetchone()[0]
        self.assertEqual(n, 0)                       # the check ran in a throw-away copy

    def test_script_that_mutates_server_answer_fails(self):
        v, lines = self.run_fake("bad")
        self.assertEqual(v, "FAIL", "\n".join(lines))
        self.assertIn("EVIDENCE_NOT_VERBATIM", "\n".join(lines))

    def test_script_that_writes_nothing_reports_no_rows_with_its_reason(self):
        v, lines = self.run_fake("empty")
        self.assertEqual(v, "NO ROWS")
        self.assertIn("tidak ada yang dikarang", "\n".join(lines))

    def test_unknown_chain_is_an_error(self):
        v, _ = cho.run_chain("nope", say=lambda *_: None)
        self.assertEqual(v, "ERROR")


if __name__ == "__main__":
    unittest.main()
