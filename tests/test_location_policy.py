"""Test to ensure location data integrity: no 'Global' placeholders in city or country."""
import os
import sqlite3
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "hotel_stays.db")

class TestLocationPolicy(unittest.TestCase):
    def test_no_global_cities(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        count = cur.execute("SELECT count(*) FROM hotels WHERE city = 'Global'").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0, f"Found {count} hotels with lazy 'Global' city placeholder!")

    def test_no_global_countries(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        count = cur.execute("SELECT count(*) FROM hotels WHERE country = 'Global'").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0, f"Found {count} hotels with lazy 'Global' country placeholder!")

if __name__ == "__main__":
    unittest.main()
