"""Test database schema constraints and integrity."""
import os
import sqlite3
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "hotel_stays.db")

class TestSchemaGuard(unittest.TestCase):
    def test_sqlite_integrity(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        res = cur.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        self.assertEqual(res, "ok", f"Database PRAGMA integrity_check failed: {res}")

    def test_room_class_validity(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        invalid = cur.execute("""
            SELECT count(*) FROM rate_records 
            WHERE room_class NOT IN ('STANDARD','DELUXE','CLUB','SUITE','UNKNOWN')
        """).fetchone()[0]
        conn.close()
        self.assertEqual(invalid, 0, f"Found {invalid} records with invalid room_class!")

    def test_cash_positive(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        invalid = cur.execute("""
            SELECT count(*) FROM rate_records 
            WHERE cash_rate IS NOT NULL AND cash_rate <= 0
        """).fetchone()[0]
        conn.close()
        self.assertEqual(invalid, 0, f"Found {invalid} records with non-positive cash rate!")

if __name__ == "__main__":
    unittest.main()
