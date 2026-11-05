"""Test that run_evidence_audit passes Layer 1 (byte parity) and Layer 2 (value replay)."""
import os
import unittest
from engine.verify_evidence_integrity import run_evidence_audit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "hotel_stays.db")

class TestEvidenceVerifier(unittest.TestCase):
    def test_evidence_integrity_audit(self):
        report = run_evidence_audit(DB_PATH, strict=False)
        self.assertTrue(report.get("audit_passed"), f"Evidence audit failed: {report}")
        self.assertEqual(report.get("mismatches", 0), 0, f"Found {report.get('mismatches')} value mismatches!")

if __name__ == "__main__":
    unittest.main()
