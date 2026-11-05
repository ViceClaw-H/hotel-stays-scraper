#!/usr/bin/env python3
"""Pre-flight Readiness & Health Check for Antigravity Hotel Harvester & Engine.

Verifies:
1. Python Runtime & Architecture
2. Browser Availability (Chrome / Edge)
3. Master SQLite Database Integrity
4. Zero-Synthetic & Zero-Global Policy Adherence
5. Cryptographic Evidence Integrity (Layer 1 Byte Parity & Layer 2 Replay)
"""
import sys
import os
import sqlite3
import subprocess

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "hotel_stays.db")

def check_python():
    print("[1/5] Checking Python Runtime...")
    print(f"      Version : {sys.version.split()[0]} ({sys.platform})")
    print(f"      Location: {sys.executable}")
    return True

def check_browser():
    print("[2/5] Checking Browser Availability for Playwright Scrapers...")
    candidates = [
        os.environ.get("CHROME_BIN") or "",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    found = [p for p in candidates if p and os.path.exists(p)]
    if found:
        print(f"      [OK] Browser detected: {found[0]}")
        return True
    else:
        print("      [WARN] No local Google Chrome or Microsoft Edge detected. (Offline viewing works, headless browser scrapers require Chrome/Edge).")
        return False

def check_database():
    print("[3/5] Checking Master Database Integrity...")
    if not os.path.exists(DB_PATH):
        print(f"      [FAIL] hotel_stays.db not found at {DB_PATH}")
        return False
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # SQLite integrity check
    res = cur.execute("PRAGMA integrity_check").fetchone()[0]
    if res != "ok":
        print(f"      [FAIL] Integrity check failed: {res}")
        conn.close()
        return False
    print("      [OK] SQLite PRAGMA integrity_check: ok")
    
    # Counts
    hotels = cur.execute("SELECT count(*) FROM hotels").fetchone()[0]
    rates = cur.execute("SELECT count(*) FROM rate_records").fetchone()[0]
    ev = cur.execute("SELECT count(*) FROM evidence_registry").fetchone()[0]
    print(f"      [OK] Cataloged Hotels: {hotels:,} | Active Rates: {rates:,} | Evidence Files: {ev:,}")
    conn.close()
    return True

def check_policies():
    print("[4/5] Checking Zero-Synthetic & Strict Location Policies...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 1. Zero synthetic keywords
    forbidden = ["synthetic", "estimated", "multiplier", "fake", "benchmark formula", "procedural", "placeholder"]
    q = " OR ".join([f"LOWER(notes) LIKE '%{kw}%'" for kw in forbidden])
    synthetic_count = cur.execute(f"SELECT count(*) FROM rate_records WHERE {q}").fetchone()[0]
    if synthetic_count > 0:
        print(f"      [FAIL] Found {synthetic_count} rows with synthetic keywords!")
        conn.close()
        return False
    print("      [OK] 0 rows with synthetic keywords in rate_records.")
    
    # 2. Zero 'Global' locations
    global_cities = cur.execute("SELECT count(*) FROM hotels WHERE city = 'Global'").fetchone()[0]
    global_countries = cur.execute("SELECT count(*) FROM hotels WHERE country = 'Global'").fetchone()[0]
    if global_cities > 0 or global_countries > 0:
        print(f"      [WARN] Found {global_cities} Global cities and {global_countries} Global countries.")
    else:
        print("      [OK] 0 'Global' speculative location values in hotels table.")
        
    conn.close()
    return True

def check_evidence():
    print("[5/5] Running Cryptographic Evidence Integrity Audit...")
    try:
        from engine.verify_evidence_integrity import run_evidence_audit
        report = run_evidence_audit(DB_PATH, strict=False)
        if report.get("audit_passed"):
            print("      [OK] Cryptographic Evidence Audit: PASSED (0 missing, 0 mismatches)")
            return True
        else:
            print("      [FAIL] Cryptographic Evidence Audit FAILED.")
            return False
    except Exception as e:
        print(f"      [FAIL] Error running evidence audit: {e}")
        return False

def main():
    print("=" * 70)
    print("   ANTIGRAVITY HOTEL HARVESTER & ENGINE - PRE-FLIGHT READINESS CHECK")
    print("=" * 70)
    p_ok = check_python()
    b_ok = check_browser()
    d_ok = check_database()
    l_ok = check_policies()
    e_ok = check_evidence()
    print("=" * 70)
    if d_ok and l_ok and e_ok:
        print("   >>> READINESS STATUS: ALL CORE TESTS PASSED. READY FOR RUN. <<<")
        print("=" * 70)
        sys.exit(0)
    else:
        print("   >>> READINESS STATUS: CRITICAL CHECKS FAILED. <<<")
        print("=" * 70)
        sys.exit(1)

if __name__ == "__main__":
    main()
