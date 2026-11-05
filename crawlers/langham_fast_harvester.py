# -*- coding: utf-8 -*-
"""Langham Hospitality Group 365-Day Flexible Calendar Harvester (Schema v2).

Harvests daily fully-taxed room rates across up to 365 days via official Sabre SynXis calendar API:
    POST https://reservations.brilliantbylangham.com/api/booking/calendar_availability

Features:
- Pure HTTP API execution via curl_cffi (lightweight, zero headless browser overhead).
- Captures 100% all-in room cost ('amountWithTax', taxes and fees inclusive).
- Saves verbatim evidence JSON under evidence/langham/raw/.
- Validates cryptographic provenance via engine.rate_writer.write_rate_batch().
- Tracks per-hotel state in harvest_status (OK, PARTIAL, NO_AVAILABILITY).
"""
import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from curl_cffi import requests

from engine import harvest_state
from engine.extractors.langham import (
    EVIDENCE_FORMAT,
    EVIDENCE_VERSION,
    parse_evidence,
)
from engine.rate_writer import write_rate_batch
from engine.schema import HARVEST_STATUS_DDL

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass

SOURCE = "LANGHAM_CALENDAR"
SOURCE_TYPE = "OFFICIAL_LANGHAM_SYNXIS"
DB_PATH = os.path.join(ROOT, "hotel_stays.db")
EVIDENCE_DIR = os.path.join(ROOT, "evidence", "langham", "raw")
ROSTER_FILES = [
    os.path.join(ROOT, "catalogs", "langham", "langham_3tier_resolved.json"),
    os.path.join(ROOT, "catalogs", "langham", "langham_master_crs_roster.json"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("langham")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://reservations.brilliantbylangham.com",
    "Referer": "https://reservations.brilliantbylangham.com/"
}


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def get_synxis_id_for_hotel(hotel_id: str, hotel_name: str, city: str, roster: List[Dict]) -> Optional[str]:
    hnorm = normalize(hotel_name)
    hcitynorm = normalize(city)

    # 1. Direct name match
    for r in roster:
        rnorm = normalize(r.get("name", ""))
        if rnorm == hnorm or (len(rnorm) > 8 and rnorm in hnorm) or (len(hnorm) > 8 and hnorm in rnorm):
            return str(r["synxis_id"])

    # 2. City + brand match
    for r in roster:
        rnorm = normalize(r.get("name", ""))
        if hcitynorm and len(hcitynorm) >= 3 and hcitynorm in rnorm:
            return str(r["synxis_id"])

    return None


def fetch_hotel_calendar_api(session: requests.Session, synxis_id: str, months_to_fetch: int = 12) -> List[Dict]:
    """Fetch consecutive 30-day calendar windows for a hotel."""
    calendar_entries = []
    current_start = date.today()
    api_url = "https://reservations.brilliantbylangham.com/api/booking/calendar_availability"

    for _ in range(months_to_fetch):
        current_end = current_start + timedelta(days=30)
        start_str = current_start.strftime("%Y-%m-%d")
        end_str = current_end.strftime("%Y-%m-%d")

        payload = {
            "hotelCode": str(synxis_id),
            "startDate": start_str,
            "endDate": end_str,
            "adults": 1,
            "children": 0,
            "childAges": []
        }

        try:
            resp = session.post(
                api_url,
                json=payload,
                headers=HEADERS,
                impersonate="chrome124",
                timeout=20
            )
            if resp.status_code == 200:
                body = resp.json()
                items = body.get("data", {}).get("calendar", [])
                calendar_entries.extend(items)
        except Exception as e:
            log.warning(f"Error fetching window {start_str} to {end_str} for {synxis_id}: {e}")

        current_start = current_end + timedelta(days=1)
        time.sleep(0.15)

    # Deduplicate by date
    dedup = {}
    for entry in calendar_entries:
        dt = entry.get("date")
        if dt:
            dedup[dt] = entry

    return [dedup[k] for k in sorted(dedup.keys())]


def harvest_langham(
    hotel_ids: Optional[List[str]] = None,
    limit: Optional[int] = None,
    months: int = 12,
    dry_run: bool = False,
    force: bool = False
):
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute(HARVEST_STATUS_DDL)
    conn.commit()

    roster = []
    if os.path.exists(ROSTER_FILES[1]):
        with open(ROSTER_FILES[1], "r", encoding="utf-8") as fh:
            roster = json.load(fh)

    c = conn.cursor()
    if hotel_ids:
        rows = c.execute(
            f"SELECT id, name, official_url, currency, city FROM hotels WHERE brand = 'LANGHAM' AND ("
            + " OR ".join(f"id LIKE '%{h}%'" for h in hotel_ids)
            + ")",
        ).fetchall()
    elif force:
        rows = c.execute("""
            SELECT h.id, h.name, h.official_url, h.currency, h.city
            FROM hotels h
            WHERE h.brand = 'LANGHAM'
            ORDER BY h.id ASC
        """).fetchall()
    else:
        rows = c.execute("""
            SELECT h.id, h.name, h.official_url, h.currency, h.city
            FROM hotels h
            LEFT JOIN harvest_status hs ON hs.hotel_id = h.id AND hs.source = 'LANGHAM_CALENDAR'
            WHERE h.brand = 'LANGHAM' AND (hs.status IS NULL OR hs.status NOT IN ('OK'))
            ORDER BY h.id ASC
        """).fetchall()

    if limit and limit > 0:
        rows = rows[:limit]

    log.info(f"Target Langham properties to process: {len(rows)}")
    if not rows:
        log.info("No Langham properties due for harvesting.")
        conn.close()
        return

    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    session = requests.Session()
    total_rates_written = 0

    try:
        for idx, (hotel_id, name, official_url, hotel_curr, city) in enumerate(rows, 1):
            sid = get_synxis_id_for_hotel(hotel_id, name, city, roster)

            if not sid:
                log.warning(f"[{idx}/{len(rows)}] Skipping {hotel_id} ({name}): SynXis ID not resolved.")
                harvest_state.record(
                    conn,
                    source=SOURCE,
                    hotel_id=hotel_id,
                    status="FAILED",
                    reason="UNRESOLVED_SYNXIS_ID",
                    detail=f"Unable to find Sabre SynXis hotel ID for {name}",
                    url=official_url
                )
                conn.commit()
                continue

            log.info(f"[{idx}/{len(rows)}] Processing {hotel_id} (SynXis: {sid} - {name[:35]})...")

            calendar_data = fetch_hotel_calendar_api(session, synxis_id=sid, months_to_fetch=months)

            now_iso = datetime.now().isoformat(timespec="seconds") + "Z"
            detected_currency = (
                calendar_data[0].get("currency") if calendar_data else (hotel_curr or "USD")
            )

            evidence_dict = {
                "format": EVIDENCE_FORMAT,
                "version": EVIDENCE_VERSION,
                "hotel_id": hotel_id,
                "synxis_id": sid,
                "source_url": f"https://reservations.brilliantbylangham.com/api/booking/calendar_availability?hotelCode={sid}",
                "harvested_at": now_iso,
                "currency": detected_currency,
                "tax_inclusive": 1,
                "calendar": calendar_data
            }

            evidence_bytes = json.dumps(evidence_dict, ensure_ascii=False, indent=2).encode("utf-8")
            evidence_file = f"evidence/langham/raw/langham_{hotel_id}_{date.today().strftime('%Y%m%d')}.json"

            rate_rows = parse_evidence(evidence_bytes)
            log.info(f"    [+] Extracted {len(rate_rows)} bookable rate dates (currency: {detected_currency})")

            if dry_run:
                log.info(f"    [DRY-RUN] Would write {len(rate_rows)} rates to {evidence_file}")
                continue

            if not rate_rows:
                log.info(f"    [*] Property has 0 bookable dates in window.")
                harvest_state.record(
                    conn,
                    source=SOURCE,
                    hotel_id=hotel_id,
                    status="NO_AVAILABILITY",
                    reason="NO_DATES_RETURNED",
                    detail="SynXis calendar API returned empty availability grid",
                    url=official_url,
                    dates_ok=0,
                    dates_total=len(calendar_data)
                )
                conn.commit()
                continue

            write_res = write_rate_batch(
                conn,
                hotel_id=hotel_id,
                source_type=SOURCE_TYPE,
                source_url=evidence_dict["source_url"],
                rows=rate_rows,
                evidence_relpath=evidence_file,
                evidence_bytes=evidence_bytes,
                evidence_grade="RAW",
                workspace_dir=ROOT,
                notes="Langham official Sabre SynXis flexible calendar (amountWithTax)",
                allow_points_removal=True
            )

            total_rates_written += write_res.written
            horizon_last = max(r.stay_date for r in rate_rows) if rate_rows else None
            evidence_hash = write_res.evidence_sha256[:12] if write_res.evidence_sha256 else "N/A"
            if write_res.rejected:
                log.warning(f"    [!] Rejected {len(write_res.rejected)} rows: {write_res.rejected[:3]}")

            harvest_state.record(
                conn,
                source=SOURCE,
                hotel_id=hotel_id,
                status="OK" if write_res.written > 0 else "PARTIAL",
                url=official_url,
                dates_ok=write_res.written,
                dates_total=len(calendar_data),
                horizon_last_ok=horizon_last
            )
            conn.commit()
            log.info(f"    [OK] DB updated: {write_res.written} rates written (SHA-256: {evidence_hash}...)")

    finally:
        conn.close()

    log.info(f"Langham harvesting completed. Total rates written across batch: {total_rates_written}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Langham Hospitality Group Calendar Harvester (Schema v2)")
    parser.add_argument("--hotel", type=str, help="Comma-separated hotel IDs (e.g. lang_the_langham_sydney)")
    parser.add_argument("--limit", type=int, help="Limit number of properties to process")
    parser.add_argument("--months", type=int, default=12, help="Number of months to harvest per hotel (default: 12)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse without writing to database")
    parser.add_argument("--force", action="store_true", help="Harvest every property, ignoring existing OK status")

    args = parser.parse_args()
    h_list = [h.strip().lower() for h in args.hotel.split(",")] if args.hotel else None

    harvest_langham(
        hotel_ids=h_list,
        limit=args.limit,
        months=args.months,
        dry_run=args.dry_run,
        force=args.force
    )
