# -*- coding: utf-8 -*-
"""v9d: findings from the run on another PC (2026-11-03) turned into regression tests."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import bestwestern_harvester as bw        # noqa: E402
from crawlers import radisson_harvester as rh           # noqa: E402
from engine.schema import create_full_schema            # noqa: E402


class RunnerTests(unittest.TestCase):
    def test_runner_launches_price_scripts_not_roster_scripts(self):
        txt = open(os.path.join(ROOT, "crawlers", "master_concurrent_runner.py"), encoding="utf-8").read()
        for good in ("swissbel_harvester.py", "gha_harvester.py", "langham_harvester.py"):
            self.assertIn(good, txt)
        for bad in ("swissbel_property_discovery.py", "gha_master_crawler.py", "langham_master_365"):
            self.assertNotIn(bad, txt)
        self.assertIn('"--rate", "1.5"', txt)                       # IHG was blocked at 4 req/s with 6 workers
        self.assertIn("PARTIAL", txt)                               # exit code 2 is shown as partial, not "DONE OK"

    def test_legacy_langham_script_and_session_cookies_are_gone(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "crawlers", "langham_master_365_and_percentiles_crawler.py")))
        p = os.path.join(ROOT, "crawlers", "pw_radisson_session", "radisson_cookies.json")
        self.assertEqual(json.load(open(p, encoding="utf-8")), [])

    def test_folders_needed_by_launched_scripts_are_present(self):
        self.assertTrue(os.path.exists(os.path.join(ROOT, "data", "hyatt_official_directory.json")))   # Hyatt crashed without it
        self.assertTrue(os.path.exists(os.path.join(ROOT, "database", "__init__.py")))                  # gha_master_crawler imports it

    def test_all_bat_files_use_crlf(self):
        for f in os.listdir(ROOT):
            if f.lower().endswith(".bat"):
                raw = open(os.path.join(ROOT, f), "rb").read()
                self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), f)

    def test_ihg_defaults_are_gentle_and_cooldowns_long(self):
        from crawlers import ihg_calendar_harvester as ihg
        a = ihg.build_parser().parse_args([])
        self.assertLessEqual(a.workers, 3)
        self.assertLessEqual(a.rate, 1.5)
        self.assertGreaterEqual(sum(ihg.COOLDOWN_SCHEDULE), 600)

    def test_cookie_onboarding_guide_is_linked_from_every_entry_point(self):
        guide = os.path.join(ROOT, "00_START_HERE_WAJIB_DIBACA.txt")
        self.assertTrue(os.path.exists(guide))
        with open(guide, encoding="utf-8") as handle:
            guide_text = handle.read().lower()
        for required in ("run pertama", "ip berubah", "sesi kedaluwarsa", "403", "captcha", "tidak otomatis"):
            self.assertIn(required, guide_text)

        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as handle:
            readme = handle.read()
        self.assertIn("00_START_HERE_WAJIB_DIBACA.txt", readme)
        self.assertLess(readme.index("00_START_HERE_WAJIB_DIBACA.txt"), readme.index("1_SETUP_NEW_PC.bat"))

        with open(os.path.join(ROOT, "RUN_MENU.bat"), encoding="utf-8") as handle:
            menu = handle.read()
        self.assertIn("[C] REGENERATE ALL COOKIES", menu)
        self.assertIn('if /i "%opt%"=="C" call REGENERATE_ALL_COOKIES.bat', menu)
        self.assertIn("/ C /", menu)

    def test_cookie_generators_require_packaged_playwright_runtime(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "ENSURE_FRESH_COOKIES.bat")))
        generators = (
            "GENERATE_HILTON_COOKIES.bat", "GENERATE_MARRIOTT_COOKIES.bat",
            "GENERATE_BESTWESTERN_COOKIES.bat", "GENERATE_RADISSON_COOKIES.bat",
        )
        for generator in generators:
            with open(os.path.join(ROOT, generator), encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn('set "PY_BIN=%~dp0portable_python\\python.exe"', text, generator)
            self.assertIn('if not exist "%PY_BIN%"', text, generator)
            self.assertIn('"%PY_BIN%"', text, generator)
            self.assertNotIn("else (", text, generator)


class RadissonRecoveryTests(unittest.TestCase):
    def test_browser_closed_is_recognised_and_not_relabelled_as_http_500(self):
        self.assertTrue(rh.is_browser_closed(RuntimeError("Page.evaluate: Target page, context or browser has been closed")))
        self.assertFalse(rh.is_browser_closed(RuntimeError("net::ERR_TIMED_OUT")))

        class Page:
            def goto(self, *a, **k):
                raise RuntimeError("Target page, context or browser has been closed")
        with self.assertRaises(RuntimeError):
            rh.PageFetcher(Page()).hotel_info("some-hotel")

        class Page2:
            def goto(self, *a, **k):
                raise RuntimeError("net::ERR_TIMED_OUT at https://x")
        info = rh.PageFetcher(Page2()).hotel_info("some-hotel")
        self.assertIsNone(info["status"])
        self.assertIn("ERR_TIMED_OUT", info["error"])

    def test_navigation_error_reason_is_not_an_http_status(self):
        class F:
            def hotel_info(self, slug):
                return {"status": None, "code": None, "ld": None, "error": "TimeoutError: boom"}
        tmp = tempfile.TemporaryDirectory()
        conn = sqlite3.connect(os.path.join(tmp.name, "t.db"))
        create_full_schema(conn)
        r = rh.harvest_hotel(F(), conn, "rad_x", "x", ["2026-12-05"], workspace_dir=tmp.name, sleep=lambda s: None)
        self.assertTrue(r["skipped_reason"].startswith("navigation error"))
        self.assertNotIn("HTTP", r["skipped_reason"])
        conn.close()
        tmp.cleanup()


class BestWesternRoomLevelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "t.db")
        c = sqlite3.connect(self.db_path)
        create_full_schema(c)
        c.execute("ALTER TABLE hotels ADD COLUMN lifecycle_status TEXT DEFAULT 'ACTIVE'")
        c.execute("ALTER TABLE hotels ADD COLUMN status_updated_at TEXT")
        c.commit()
        c.close()
        self.old = (bw.DB_PATH, bw.EVIDENCE_DIR, bw.search_cluster_rates, bw.query_room_rate_plans, bw.time.sleep)
        bw.DB_PATH, bw.EVIDENCE_DIR = self.db_path, self.tmp.name
        bw.time.sleep = lambda s: None
        hotel = {"resort": "99034", "resortSummary": {"resort": "99034", "name": "BW Test", "currencyCode": "IDR", "city": "Jakarta", "country": "Indonesia"},
                 "resortSearchRate": {"averageNightlyRate": 738000, "averageNightlyAmountWithFeesAndTaxes": None, "resortRoomCategory": "1"}}
        text = json.dumps({"data": {"searchHotels": {"taxesAndFeesAvailable": False, "hotels": [hotel]}}})
        bw.search_cluster_rates = lambda *a, **k: (text, [hotel])
        rooms = [{"roomCategoryCode": "K1", "roomId": "1", "description": "1 KING BED", "ratePlans": [
            {"shortName": "MEMBER ONLY", "taxIncluded": True, "averageNightlyRate": 500000, "isMemberRate": True},
            {"shortName": "FLEXIBLE", "taxIncluded": True, "averageNightlyRate": 820000, "isMemberRate": False},
            {"shortName": "EARLY", "taxIncluded": True, "averageNightlyRate": 738000, "isMemberRate": False},
            {"shortName": "UNSTATED", "taxIncluded": False, "averageNightlyRate": 100000, "averageNightlyRateWithTaxes": None, "isMemberRate": False}]}]
        bw.query_room_rate_plans = lambda *a, **k: (json.dumps({"rooms": rooms}), rooms)

    def tearDown(self):
        (bw.DB_PATH, bw.EVIDENCE_DIR, bw.search_cluster_rates, bw.query_room_rate_plans, bw.time.sleep) = self.old
        self.tmp.cleanup()

    def test_takes_lowest_public_plan_with_a_stated_tax_status(self):
        bw.harvest_and_record_bestwestern(limit_hubs=1, grid_months=1)
        c = sqlite3.connect(self.db_path)
        got = {r[0] for r in c.execute("SELECT cash_rate FROM rate_records")}
        notes = c.execute("SELECT notes FROM rate_records LIMIT 1").fetchone()[0]
        c.close()
        self.assertEqual(got, {738000.0})            # not the member rate (500000), not the first plan (820000), not the unstated-tax plan (100000)
        self.assertIn("taxIncluded=True", notes)



class LegacyLanghamFixTests(unittest.TestCase):
    def test_reports_then_fixes_only_langham_hotels_and_keeps_prices(self):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import fix_legacy_langham_hotels as fx
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "t.db")
        c = sqlite3.connect(path)
        create_full_schema(c)
        c.execute("INSERT INTO hotels (id, brand, name, city, country, currency, loyalty_model, award_category, track_points, official_url) VALUES ('lang_a','LANGHAM','A','Global','Global','USD','F','X',1,'u')")
        c.execute("INSERT INTO hotels (id, brand, name, city, country, currency, loyalty_model, award_category, track_points, official_url) VALUES ('hil_b','HILTON','B','Global','Global','USD','F','X',1,'u')")
        c.execute("INSERT INTO room_categories (id, hotel_id, raw_name, standardized_type, max_occupancy) VALUES ('lang_a_r','lang_a','Room','STANDARD',2)")
        c.execute("INSERT INTO rate_records (room_id, stay_date, cash_rate, award_available, raw_currency, raw_amount, tax_inclusive, source_url, source_type, room_name, room_class) VALUES ('lang_a_r','2026-12-05',817,0,'GBP',817,1,'u','OFFICIAL_LANGHAM_SYNXIS','Room','STANDARD')")
        c.commit()
        self.assertEqual(len(fx.plan(c)), 1)
        c.close()
        fx.main(["--db", path])                                   # report only
        c = sqlite3.connect(path)
        self.assertEqual(c.execute("SELECT city FROM hotels WHERE id='lang_a'").fetchone()[0], "Global")
        c.close()                                                 # v9f: Windows cannot delete an open file
        fx.main(["--db", path, "--apply"])
        c = sqlite3.connect(path)
        self.assertEqual(c.execute("SELECT city, country, currency FROM hotels WHERE id='lang_a'").fetchone(), ("Unknown", "Unknown", "GBP"))
        self.assertEqual(c.execute("SELECT city FROM hotels WHERE id='hil_b'").fetchone()[0], "Global")     # other brands untouched
        self.assertEqual(c.execute("SELECT cash_rate FROM rate_records").fetchone()[0], 817.0)              # price rows untouched
        c.close()
        tmp.cleanup()

    def test_valid_currency_is_never_overwritten_with_unknown(self):
        # v9f: seen live 2026-11-03 (dry-run): lang_the_langham_jakarta IDR -> Unknown. Must stay IDR.
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import fix_legacy_langham_hotels as fx
        c = sqlite3.connect(":memory:")
        create_full_schema(c)
        c.execute("INSERT INTO hotels (id, brand, name, city, country, currency, loyalty_model, award_category, track_points, official_url) VALUES ('lang_j','LANGHAM','J','Unknown','Indonesia','IDR','F','X',1,'u')")
        c.execute("INSERT INTO hotels (id, brand, name, city, country, currency, loyalty_model, award_category, track_points, official_url) VALUES ('lang_g','LANGHAM','G','Global','Global','Global','F','X',1,'u')")
        plan = {hid: new for hid, _old, new in fx.plan(c)}
        c.close()
        self.assertNotIn("lang_j", plan)                                          # nothing to change
        self.assertEqual(plan["lang_g"], ("Unknown", "Unknown", "Unknown"))      # only placeholders replaced


if __name__ == "__main__":
    unittest.main()
