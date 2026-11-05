"""Test to ensure ZERO synthetic, procedural, or benchmark data exists in rate_records."""
import os
import sqlite3
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "hotel_stays.db")

FORBIDDEN_KEYWORDS = [
    "synthetic",
    "estimated",
    "multiplier",
    "fake",
    "benchmark formula",
    "procedural",
    "placeholder"
]

class TestZeroSyntheticGate(unittest.TestCase):
    def test_no_synthetic_keywords_in_notes(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        q = " OR ".join([f"LOWER(notes) LIKE '%{kw}%'" for kw in FORBIDDEN_KEYWORDS])
        count = cur.execute(f"SELECT count(*) FROM rate_records WHERE {q}").fetchone()[0]
        conn.close()
        
        self.assertEqual(count, 0, f"Violated Zero-Synthetic policy: {count} rows contain forbidden keywords in notes!")

    def test_every_rate_has_registered_evidence(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        unverified = cur.execute("""
            SELECT count(*) FROM rate_records 
            WHERE evidence_file IS NULL OR evidence_grade NOT IN ('RAW', 'SUMMARY')
        """).fetchone()[0]
        conn.close()
        
        self.assertEqual(unverified, 0, f"Found {unverified} rate records without valid RAW/SUMMARY evidence!")

if __name__ == "__main__":
    unittest.main()
