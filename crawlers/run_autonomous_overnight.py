# -*- coding: utf-8 -*-
"""Autonomous Overnight Rate Harvester (Schema v2).

Executes harvesting from lowest request cost to highest request cost completely
in the background without requiring user intervention:

Phase 1: Langham Hospitality Group (Lowest Cost)
    - Direct Sabre SynXis calendar API via curl_cffi.
    - 365 days of 100% all-in room cost per hotel.
    - Zero browser overhead, ~1.5 minutes for all remaining properties.

Phase 2: World of Hyatt Award Calendar (Ultra-Low Request Cost)
    - 366-day award points redemption calendar per hotel.
    - Runs 2 parallel offscreen workers in the background.
    - Fully autonomous with automatic session recycling and Kasada protection.
"""
import logging
import os
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LOG_FILE = os.path.join(ROOT, "logs", "autonomous_overnight.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("overnight")


def run_phase_langham():
    log.info("=================================================================")
    log.info("🚀 PHASE 1: HARVESTING LANGHAM HOSPITALITY GROUP (LOWEST COST)")
    log.info("=================================================================")
    from crawlers.langham_fast_harvester import harvest_langham

    try:
        harvest_langham()
        log.info("✅ Phase 1: Langham harvesting successfully completed!")
    except Exception as e:
        log.error(f"❌ Phase 1: Langham encountered error: {e}")


def run_phase_accor(limit: int = 100, days: int = 90, workers: int = 5):
    log.info("=================================================================")
    log.info("🚀 PHASE 2: HARVESTING ACCOR HOTELS (PURE GRAPHQL API, 0 BROWSER)")
    log.info("=================================================================")
    from crawlers.accor_fast_harvester import harvest_accor

    try:
        harvest_accor(limit=limit, days=days, workers=workers)
        log.info("✅ Phase 2: Accor harvesting batch completed!")
    except Exception as e:
        log.error(f"❌ Phase 2: Accor encountered error: {e}")


def run_phase_hyatt():
    log.info("=================================================================")
    log.info("🚀 PHASE 3: HARVESTING WORLD OF HYATT 366-DAY CALENDAR (OFFSCREEN)")
    log.info("=================================================================")
    cmd = [
        sys.executable,
        os.path.join(ROOT, "crawlers", "hyatt_avail_days_harvester.py"),
        "--workers", "2"
    ]
    log.info(f"Starting Hyatt harvester: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=ROOT)
    proc.wait()
    log.info(f"✅ Phase 3: Hyatt completed with exit code {proc.returncode}")


def main():
    start_time = datetime.now()
    log.info(f"[*] Autonomous overnight pipeline initiated at {start_time.isoformat()}")

    # Phase 1: Langham (32 hotels)
    run_phase_langham()

    # Small cooldown
    time.sleep(3)

    # Phase 2: Accor (Pure GraphQL, 2 paced parallel workers)
    run_phase_accor(limit=500, days=60, workers=2)

    # Small cooldown
    time.sleep(3)

    # Phase 3: Hyatt (Offscreen Chrome workers)
    run_phase_hyatt()

    end_time = datetime.now()
    log.info(f"[*] Autonomous overnight pipeline finished. Total duration: {end_time - start_time}")


if __name__ == "__main__":
    main()
