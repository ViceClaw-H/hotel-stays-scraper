"""Auto-trigger 4-Worker Benchmark on Hilton NO_AVAILABILITY properties once 2-worker fleet finishes."""
import os
import sys
import time
import sqlite3
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "hotel_stays.db")

print("4-Worker Benchmark Watchdog active: monitoring 2-worker fleet completion...")

while True:
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        c = conn.cursor()
        c.execute("""
            SELECT count(*) 
            FROM hotels h
            LEFT JOIN harvest_status hs ON hs.hotel_id = h.id AND hs.source = 'HILTON_CALENDAR'
            WHERE h.brand = 'HILTON' AND (hs.status IS NULL OR hs.status NOT IN ('OK', 'NO_AVAILABILITY'))
        """)
        remaining = c.fetchone()[0]
        
        c.execute("SELECT count(*) FROM harvest_status WHERE source = 'HILTON_CALENDAR' AND status = 'NO_AVAILABILITY'")
        no_avail = c.fetchone()[0]
        conn.close()
    except Exception as e:
        print(f"Watchdog DB read error: {e}")
        time.sleep(30)
        continue

    if remaining == 0:
        print(f"\n==================================================================")
        print(f"  2-WORKER FLEET COMPLETED 100% OF GLOBAL HILTON PORTFOLIO!")
        print(f"  Now launching 4-WORKER benchmark on {no_avail} NO_AVAILABILITY hotels...")
        print(f"==================================================================\n")
        time.sleep(10)
        
        cmd = [
            sys.executable, "-u", os.path.join(ROOT, "crawlers", "hilton_fast_harvester.py"),
            "--workers", "4",
            "--months", "12",
            "--port", "9275",
            "--recheck-unavailable"
        ]
        cflags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == "win32" else 0
        proc = subprocess.Popen(cmd, creationflags=cflags)
        proc.wait()
        print("\n4-Worker benchmark completed with exit code:", proc.returncode)
        break
        
    time.sleep(60)
