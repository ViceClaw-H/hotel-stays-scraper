# -*- coding: utf-8 -*-
"""Accor Fast Smart-Horizon Harvester.
Queries official Accor GraphQL PriceCalendar API via curl_cffi HTTP client.
Leaky faucet (v9f-r3): drips below Accor's limit, never stops on HTTP 429 (see class Faucet).
Uses Smart Horizon Cutoff to stop querying once availability horizon ends.
Writes evidence files and saves compliant rate batches through engine.rate_writer.
"""
import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from curl_cffi import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass

from engine.rate_writer import RateRow, write_rate_batch, CALENDAR_UNKNOWN_ROOM
from engine import harvest_state
from engine.currency_source import currency_from_text, is_iso
from engine.extractors.accor import parse_evidence

SOURCE = "ACCOR_CALENDAR"
SOURCE_TYPE = "OFFICIAL_ACCOR_CRS"
DB_PATH = os.path.join(ROOT, "hotel_stays.db")
EVIDENCE_DIR = os.path.join(ROOT, "evidence", "accor", "raw")
GRAPHQL_URL = "https://api.accor.com/bff/v1/graphql"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("accor_harvester")


def load_calendar_query():
    path = os.path.join(ROOT, "crawlers", "graphql", "accor_pricecalendar_query.graphql")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    raise FileNotFoundError(f"Accor GraphQL query not found at {path}")


def get_headers():
    return {
        "content-type": "application/json",
        "origin": "https://all.accor.com",
        "referer": "https://all.accor.com/",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "apikey": os.environ.get("ACCOR_API_KEY", ""),
        "clientid": "all.accor",
        "app-id": "all.accor",
        "app-version": "1.52.1",
        "lang": "en"
    }


def clean_amount(val):
    if not val:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace("\xa0", " ").strip()
    s = re.sub(r"[^\d.,]", "", s).strip()
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            s = s.replace(".", "")
    try:
        return float(s)
    except Exception:
        return None


class AccorRateLimitError(RuntimeError):
    """Raised when Accor responds with HTTP 429 (Apigee Rate Limit hit)."""
    pass


class Faucet:
    """Accor Pacing Faucet:
    Maintains safe drip interval below Accor's Apigee limit (default 1.35s = ~44 req/min).
    Circuit Breaker: On HTTP 429, stops immediately instead of looping exponential pauses
    (user empirical standard: Apigee 429 backoff does not recover in-session).
    """
    BASE_INTERVAL = 1.35
    MAX_INTERVAL = 60.0
    OPEN_AFTER = 50

    def __init__(self, workers: int = 1, sleep=None, base_interval: Optional[float] = None):
        self.min_interval = (base_interval or self.BASE_INTERVAL) * max(1, workers)
        self.interval = self.min_interval
        self.ok_streak = 0
        self.hits_429 = 0
        self.blocked_since = None
        self._sleep = sleep or time.sleep

    def drip(self):
        self._sleep(self.interval)

    def on_ok(self):
        if self.blocked_since is not None:
            log.info(f"Accor faucet: answers again after {time.time() - self.blocked_since:.0f}s blocked; "
                     f"dripping every {self.interval:.1f}s")
        self.blocked_since = None
        self.ok_streak += 1
        if self.ok_streak >= self.OPEN_AFTER and self.interval > self.min_interval:
            self.interval = max(self.min_interval, self.interval * 0.9)
            self.ok_streak = 0

    def on_429(self, retry_after: Optional[float] = None):
        self.hits_429 += 1
        log.error(f"[ERROR] Accor HTTP 429 terdeteksi (Apigee Rate Limit hit). "
                  f"Sesuai aturan: berhenti segera (circuit breaker, tidak retry/pause berulang). Cooldown IP diperlukan.")
        raise AccorRateLimitError("Accor HTTP 429: Apigee rate limit hit. Stopping immediately.")


def _retry_after_seconds(resp) -> Optional[float]:
    """Seconds from a Retry-After header (number form only); None when absent/unreadable."""
    try:
        v = resp.headers.get("Retry-After")
        return float(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def harvest_accor_hotel(session: requests.Session, hotel_code: str, query_str: str,
                        country: str = "", currency: Optional[str] = None,
                        total_days_target: int = 120, faucet: Optional["Faucet"] = None) -> Dict:
    faucet = faucet or Faucet()
    start_date = date.today()
    chunk_size = 7
    curr_date = start_date
    end_date = start_date + timedelta(days=total_days_target)

    headers = get_headers()
    all_rates = {}
    skipped_no_currency = [0]
    raw_responses = []
    consecutive_empty_chunks = 0
    t0 = time.time()
    ok_responses = 0             # v9f: chunks that really returned HTTP 200 JSON
    failed_chunks = []           # v9f: (from, to, reason) kept so a failure is never labelled 'sold out'

    while curr_date < end_date:
        to_date = min(curr_date + timedelta(days=chunk_size - 1), end_date)
        from_str = curr_date.strftime("%Y-%m-%d")
        to_str = to_date.strftime("%Y-%m-%d")

        variables = {
            "hotelId": hotel_code,
            "hotelId2": hotel_code,
            "dateIn": from_str,
            "dateOut": (curr_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "nbAdults": 1,
            "childrenAges": [],
            "countryMarket": "FR",  # Universal: forces Accor CRS to return 100% all-in final checkout rate (TTC) under EU consumer law
            # None lets the server answer in the hotel's own currency; the currency of every price is READ from the price text below
            "currency": currency if is_iso(currency) else None,
            "from": from_str,
            "to": to_str,
            "use": "NIGHT",
            "concession": None
        }

        payload = {
            "operationName": "PriceCalendar",
            "variables": variables,
            "query": query_str
        }

        try:
            r = session.post(GRAPHQL_URL, json=payload, headers=headers, impersonate="chrome124", timeout=15)
            if r.status_code == 429:
                faucet.on_429(_retry_after_seconds(r))
                continue                      # same chunk again; the faucet never gives up
            elif r.status_code != 200:
                failed_chunks.append((from_str, to_str, f"HTTP_{r.status_code}"))
                log.warning(f"Accor HTTP {r.status_code} for {hotel_code} {from_str}..{to_str}")
                curr_date = to_date + timedelta(days=1)
                faucet.drip()
                continue

            res_json = r.json()
            ok_responses += 1
            faucet.on_ok()
            raw_responses.append({"from": from_str, "to": to_str, "data": res_json})

            # Check if Accor explicitly flags hotel as missing / invalid / closed
            if "errors" in res_json:
                for err in res_json.get("errors", []):
                    msg = str(err.get("message", "")) + " " + str(err.get("extensions", {}))
                    if "missing or invalid" in msg.lower() or "invalid_input" in msg.lower():
                        return {
                            "rates": all_rates,
                            "raw_responses": raw_responses,
                            "duration": time.time() - t0,
                            "is_closed": True
                        }

            data_field = res_json.get("data") if isinstance(res_json, dict) else {}
            hotel_offers = data_field.get("hotelOffers") if isinstance(data_field, dict) else {}
            calendar_data = hotel_offers.get("calendar", []) if isinstance(hotel_offers, dict) else []

            chunk_rates = 0
            for day_entry in calendar_data:
                if not isinstance(day_entry, dict):
                    continue
                stay_dt = day_entry.get("date")
                avail = (day_entry.get("availability") or {}).get("status")
                if avail == "UNAVAILABLE" or not stay_dt:

                    continue

                offer = day_entry.get("offer") or {}
                pricing = offer.get("pricing") or {}
                main_p = pricing.get("main") or {}
                alt_p = pricing.get("alternative") or {}

                member_amt = clean_amount(main_p.get("formattedAmount"))
                if not member_amt:
                    member_amt = clean_amount(alt_p.get("formattedAmount"))

                if not member_amt or member_amt <= 0:
                    continue
                # currency comes from the site's own price text ("IDR 1,318,750" / "€66"); unreadable -> skip, never default
                day_curr = currency_from_text(main_p.get("formattedAmount")) or currency_from_text(alt_p.get("formattedAmount"))
                if day_curr is None:
                    skipped_no_currency[0] += 1
                    continue

                # Accor ALL is a fixed cash rebate (2,000 pts = 40 EUR flat voucher).
                # Zero synthetic points: omit points completely to maintain authentic cash pricing.
                all_rates[stay_dt] = {
                    "stay_date": stay_dt,
                    "cash_rate": member_amt,
                    "currency": day_curr,
                    "points": None
                }
                chunk_rates += 1

            # Smart Horizon Cutoff
            if chunk_rates > 0:
                consecutive_empty_chunks = 0
            else:
                consecutive_empty_chunks += 1

            # Smart Horizon Cutoff:
            # 1. If we found rates and hit 2 consecutive empty weeks, the booking horizon ended!
            if len(all_rates) > 0 and consecutive_empty_chunks >= 2:
                break
            # 2. If 0 rates found across the first 4 consecutive weeks (1 month), hotel has no calendar availability!
            if len(all_rates) == 0 and consecutive_empty_chunks >= 4:
                break

        except AccorRateLimitError:
            raise
        except Exception as e:
            failed_chunks.append((from_str, to_str, f"{type(e).__name__}: {e}"[:200]))
            log.warning(f"Error on chunk {from_str} -> {to_str}: {e}")

        curr_date = to_date + timedelta(days=1)
        faucet.drip()

    elapsed = time.time() - t0
    return {
        "rates": all_rates,
        "raw_responses": raw_responses,
        "duration": elapsed,
        "skipped_no_currency": skipped_no_currency[0],
        "ok_responses": ok_responses,
        "failed_chunks": failed_chunks,
    }


def run_accor_harvester(limit: Optional[int] = None, interface: Optional[str] = None,
                        worker_id: int = 1, num_workers: int = 1, days: int = 120,
                        interval: Optional[float] = None):
    query_str = load_calendar_query()
    session = requests.Session(interface=interface) if interface else requests.Session()

    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    c = conn.cursor()

    c.execute("""
        SELECT h.id, h.name, h.country, h.currency
        FROM hotels h
        LEFT JOIN harvest_status hs ON h.id = hs.hotel_id AND hs.source = 'ACCOR_CALENDAR'
        WHERE h.brand = 'ACCOR' AND (hs.status IS NULL OR hs.status NOT IN ('OK', 'NO_AVAILABILITY'))
        ORDER BY h.id
    """)
    properties = c.fetchall()

    if num_workers > 1:
        properties = [p for i, p in enumerate(properties) if i % num_workers == (worker_id - 1)]
        log.info(f"Worker {worker_id}/{num_workers} assigned {len(properties)} properties (Interface: {interface or 'Default'})")

    if limit:
        properties = properties[:limit]

    log.info(f"Starting Accor Harvester for {len(properties)} properties (Window: {days} days, Interface: {interface or 'Default'})...")

    faucet = Faucet(workers=num_workers, base_interval=interval)
    log.info(f"Accor faucet: 1 request every {faucet.interval:.1f}s for this worker "
             f"({60 / faucet.interval:.1f}/min; {num_workers} worker(s) share the IP)")
    failed_hotels = 0
    for idx, (hotel_id, name, country, db_curr) in enumerate(properties, start=1):
        if idx > 1 and idx % 35 == 0:
            log.info(f"Batch checkpoint ({idx} hotels). Resting 90s to let Apigee IP bucket drain completely...")
            time.sleep(90.0)

        m = re.search(r'accor_([a-z0-9]+)', hotel_id)
        hotel_code = m.group(1) if m else None
        if not hotel_code:
            continue

        log.info(f"[{idx}/{len(properties)}] Harvesting Accor {hotel_id} ({name[:30]})...")
        try:
            res = harvest_accor_hotel(session, hotel_code=hotel_code, query_str=query_str,
                                      country=country or "", currency=db_curr,
                                      total_days_target=days, faucet=faucet)
        except AccorRateLimitError as e:
            harvest_state.record(
                conn,
                source=SOURCE,
                hotel_id=hotel_id,
                status="FAILED",
                reason="RATE_LIMITED_429",
                detail=f"Apigee HTTP 429: scraper stopped immediately to protect IP reputation ({e})",
                retry_days=0,
            )
            conn.commit()
            conn.close()
            log.error(f"[STOP] Accor Harvester dihentikan segera karena HTTP 429 pada {hotel_id}. Keluar dengan kode 2 (PARTIAL).")
            return 2

        rates_dict = res["rates"]
        elapsed = res["duration"]
        if res.get("skipped_no_currency"):
            log.warning(f"    {res['skipped_no_currency']} day(s) skipped: the price text names no currency (no default is assumed)")

        source_url = f"https://all.accor.com/hotel/{hotel_code}/index.en.shtml"
        # One source of truth: the saved evidence is replayed by the same pure extractor that verification uses.
        evidence_bytes = json.dumps({
            "format": "accor-calendar-evidence",
            "version": 1,
            "hotel_id": hotel_id,
            "hotel_code": hotel_code,
            "source_url": source_url,
            "harvested_at": datetime.now().isoformat() + "Z",
            "raw_responses": res["raw_responses"]
        }).encode("utf-8")
        rate_rows = parse_evidence(evidence_bytes)

        if len(rate_rows) > 0:
            evidence_file = os.path.join("evidence", "accor", "raw", f"accor_{hotel_code}_{date.today().strftime('%Y%m%d')}.json")
            os.makedirs(os.path.dirname(os.path.join(ROOT, evidence_file)), exist_ok=True)
            with open(os.path.join(ROOT, evidence_file), "wb") as f:
                f.write(evidence_bytes)

            write_res = write_rate_batch(
                conn,
                hotel_id=hotel_id,
                source_type=SOURCE_TYPE,
                source_url=source_url,
                rows=rate_rows,
                evidence_relpath=evidence_file,
                evidence_bytes=evidence_bytes,
                evidence_grade="RAW",
                workspace_dir=ROOT
            )

            harvest_state.record(
                conn,
                source=SOURCE,
                hotel_id=hotel_id,
                status="OK",
                detail=f"Harvested {len(rate_rows)} rates in {elapsed:.1f}s via PriceCalendar",
                dates_ok=len(rate_rows)
            )
            conn.commit()
            log.info(f"    [ACCOR OK] {hotel_id}: {write_res.written} rates saved to DB in {elapsed:.1f}s!")
        elif res.get("ok_responses", 0) == 0:
            # Not one successful answer: this is a failure, never 'sold out'.
            harvest_state.record(
                conn, source=SOURCE, hotel_id=hotel_id, status="FAILED", reason="NO_SUCCESSFUL_RESPONSE",
                detail=f"0 of the calendar requests succeeded: {res.get('failed_chunks')}"[:1000],
                retry_days=0,
            )
            conn.commit()
            failed_hotels += 1
            log.warning(f"    [ACCOR FAILED] {hotel_id}: no request succeeded ({len(res.get('failed_chunks') or [])} failed chunk(s)).")
        else:
            if res.get("is_closed"):
                harvest_state.record(
                    conn,
                    source=SOURCE,
                    hotel_id=hotel_id,
                    status="INACTIVE",
                    reason="CLOSED_OR_DEFLAGGED",
                    detail=f"Accor API confirmed missing or invalid hotel code {hotel_code}"
                )
                conn.commit()
                log.info(f"    [ACCOR INACTIVE/CLOSED] {hotel_id}: Property closed or deflagged from Accor.")
            else:
                harvest_state.record(
                    conn,
                    source=SOURCE,
                    hotel_id=hotel_id,
                    status="NO_AVAILABILITY",
                    reason="SOLD_OUT_OR_RESTRICTED",
                    detail=f"Active hotel but 0 bookable rooms in {days}-day window (sold out or min stay)"
                )
                conn.commit()
                log.info(f"    [ACCOR SOLD_OUT/NO_RATES] {hotel_id}: 0 rates found in {elapsed:.1f}s.")


    conn.close()
    if failed_hotels:
        log.warning(f"Accor Harvester finished with {failed_hotels} failed hotel(s) (exit code 2 = PARTIAL).")
        return 2
    log.info("Accor Harvester run complete!")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Accor Fast Harvester")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of hotels")
    parser.add_argument("--days", type=int, default=120, help="Horizon window in days (default: 120)")
    parser.add_argument("--interface", type=str, default=None, help="Local interface IP to bind (e.g. 192.168.1.4 or 192.168.42.212)")
    parser.add_argument("--worker-id", type=int, default=1, help="Worker ID (1-based)")
    parser.add_argument("--num-workers", type=int, default=1, help="Total number of workers")
    parser.add_argument("--interval", type=float, default=None,
                        help="Seconds between requests for the whole IP (default 1.35 = 44/min, golden standard); workers drip N times slower")
    args = parser.parse_args()
    sys.exit(run_accor_harvester(limit=args.limit, interface=args.interface,
                                 worker_id=args.worker_id, num_workers=args.num_workers,
                                 days=args.days, interval=args.interval) or 0)
