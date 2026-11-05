#!/usr/bin/env python3
"""
GHA DISCOVERY - price harvester (Schema v2, zero fabrication).

For each GHA hotel in the database it opens YOUR installed Chrome/Edge (throw-away profile) on
ghadiscovery.com and asks the site's own booking API for the price of one night (2 adults) on a spread
of dates. Every server response is saved verbatim (gzip) as evidence and hashed; one row is stored per
(date, room): the public "Best Available Rate" including taxes and fees. See engine/extractors/gha.py.

Never invented: prices, currency, room names. A room/date without such a rate gets no row. Hotels that
GHA does not run on its SynXis booking engine (no hotel id on their page) are skipped and reported.
If nothing was harvested the script exits with code 1.

The hotel LIST comes from crawlers/gha_master_crawler.py (official sitemaps) - run it first if the
database has no GHA hotels.

Usage
    python crawlers/gha_harvester.py                    # all GHA hotels in the database
    python crawlers/gha_harvester.py --limit 5
    python crawlers/gha_harvester.py --hotel kempinski/kempinski-the-boulevard-dubai
    python crawlers/gha_harvester.py --dates 24 --days-ahead 330 --headless
"""
import argparse
import datetime
import gzip
import json
import os
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from crawlers.radisson_harvester import Blocked, choose_dates, next_day   # shared pure helpers
from engine.extractors import gha as gha_parse
from engine.rate_writer import write_rate_batch

SITE = "https://www.ghadiscovery.com"
SOURCE_TYPE = "OFFICIAL_GHA_CRS"
RATES_URL = "https://oscp.ghadiscovery.com/api/v3/booking/hotel/rooms/rates"
DELAY_SECONDS = 1.5
MAX_CONSECUTIVE_FAILURES = 4

JS_HOTEL_INFO = """async (path) => {
  const r = await fetch('/' + path, {headers: {accept: 'text/html'}});
  const html = await r.text();
  const m = html.match(/<script id="__NEXT_DATA__"[^>]*>([\\s\\S]*?)<\\/script>/);
  if (!m) return {status: r.status, page: null};
  let page = null;
  try { page = JSON.parse(m[1]).props.pageProps.page; } catch (e) {}
  if (!page) return {status: r.status, page: null};
  let country = null;
  let cur = page.city && page.city._location ? page.city._location.parentLocation : null;
  while (cur && typeof cur === 'object') {
    const c = cur.content || {};
    if (c.name) { country = c.name; break; }
    cur = (c._location && c._location.parentLocation) || cur.parentLocation;
  }
  const brand = page._location && page._location.parentLocation && page._location.parentLocation.content
                ? page._location.parentLocation.content.code : null;
  return {status: r.status, page: {name: page.name, city: page.city ? page.city.name : null, country: country,
          hotelCode: page.reservationsEngineCode || null, brandCode: brand,
          chainId: page.synxisChainId || null, hotelId: page.synxisHotelId || null}};
}"""

JS_RATES = """async (a) => {
  const body = {numberOfRooms: 1, numberOfAdults: a.adults, startDate: a.checkIn, endDate: a.checkOut,
                hotelCode: a.hotelCode, brandCode: a.brandCode, chainId: a.chainId, hotelId: a.hotelId,
                numberOfChildren: 0, childAges: [], content: 'full', primaryChannel: 'SYDC',
                secondaryChannel: 'DSCVRYLYLTY', loyaltyProgram: 'GHA', loyaltyLevel: 'RED'};
  const r = await fetch('https://oscp.ghadiscovery.com/api/v3/booking/hotel/rooms/rates',
                        {method: 'POST', headers: {'content-type': 'application/json', accept: 'application/json'},
                         body: JSON.stringify(body)});
  return {status: r.status, text: await r.text()};
}"""


class PageFetcher:
    def __init__(self, page):
        self.page = page

    def hotel_info(self, path: str) -> Dict[str, Any]:
        return self.page.evaluate(JS_HOTEL_INFO, path)

    def rates(self, ids: Dict[str, Any], check_in: str, check_out: str, adults: int = 2) -> Dict[str, Any]:
        return self.page.evaluate(JS_RATES, {**ids, "checkIn": check_in, "checkOut": check_out, "adults": adults})


def build_evidence(hotel_id: str, hotel_code: str, stays: List[Dict[str, Any]], adults: int = 2,
                   harvested_at: Optional[str] = None) -> bytes:
    doc = {
        "format": gha_parse.EVIDENCE_FORMAT, "version": gha_parse.EVIDENCE_VERSION,
        "hotel_id": hotel_id, "hotel_code": hotel_code, "source_url": RATES_URL,
        "harvested_at": harvested_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "occupancy": {"adults": adults, "children": 0}, "stays": stays,
    }
    return gzip.compress(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0)


def page_path(official_url: str) -> Optional[str]:
    p = urlparse(official_url or "").path.strip("/")
    return p if p.count("/") == 1 else None


def harvest_hotel(fetcher, conn: sqlite3.Connection, hotel_id: str, path: str, dates: List[str],
                  workspace_dir: str = BASE_DIR, sleep=time.sleep, adults: int = 2) -> Dict[str, Any]:
    info = fetcher.hotel_info(path)
    if info.get("status") in (403, 429):
        raise Blocked(f"HTTP {info.get('status')} on the hotel page")
    page = info.get("page")
    if info.get("status") != 200 or not page:
        return {"written": 0, "rejected": [], "failed_dates": [], "skipped_reason": f"hotel page unreadable (HTTP {info.get('status')})"}
    ids = {k: page.get(k) for k in ("hotelCode", "brandCode", "chainId", "hotelId")}
    if not all(ids.values()):
        return {"written": 0, "rejected": [], "failed_dates": [],
                "skipped_reason": "hotel is not on GHA's SynXis booking engine (no hotel id on its page)"}

    stays: List[Dict[str, Any]] = []
    failed: List[str] = []
    consecutive = 0
    for d in dates:
        sleep(DELAY_SECONDS)
        res = fetcher.rates(ids, d, next_day(d), adults)
        status = res.get("status")
        if status in (403, 429):
            raise Blocked(f"HTTP {status} while pricing {d}")
        parsed = None
        if status == 200:
            try:
                parsed = json.loads(res["text"])
            except ValueError:
                parsed = None
        if not isinstance(parsed, dict) or not isinstance(parsed.get("rooms"), list):
            failed.append(d)
            consecutive += 1
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                break
            continue
        consecutive = 0
        stays.append({"stay_date": d, "response": parsed})

    if not stays:
        return {"written": 0, "rejected": [], "failed_dates": failed, "skipped_reason": "no usable response"}
    evidence = build_evidence(hotel_id, ids["hotelCode"], stays, adults)
    rows = gha_parse.parse_evidence(evidence)
    if not rows:
        return {"written": 0, "rejected": [], "failed_dates": failed,
                "skipped_reason": "server returned rooms, but no rate open to the general public "
                                  "(non-member, non-restricted, with taxes and fees) for these dates"}
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    res = write_rate_batch(
        conn, hotel_id=hotel_id, source_type=SOURCE_TYPE, source_url=RATES_URL, rows=rows,
        evidence_relpath=f"evidence/gha/raw/{hotel_id}__{ts}.json.gz", evidence_bytes=evidence,
        evidence_grade="RAW", workspace_dir=workspace_dir,
        notes="Official GHA DISCOVERY booking API, 1-night stays, 2 adults",
    )
    _update_hotel_facts(conn, hotel_id, page, rows[0].currency)
    return {"written": res.written, "rejected": res.rejected, "failed_dates": failed, "skipped_reason": None}


def _update_hotel_facts(conn, hotel_id, page, currency):
    sets, vals = [], []
    for col, key in (("name", "name"), ("city", "city"), ("country", "country")):
        if page.get(key):
            sets.append(f"{col} = ?"); vals.append(str(page[key]).strip())
    if currency:
        sets.append("currency = ?"); vals.append(currency.upper())
    if sets:
        conn.execute(f"UPDATE hotels SET {', '.join(sets)} WHERE id = ?", (*vals, hotel_id))
        conn.commit()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GHA DISCOVERY price harvester (no fabrication)")
    ap.add_argument("--hotel", action="append", help="hotel page path 'brand-slug/hotel-slug' (repeatable)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dates", type=int, default=12)
    ap.add_argument("--days-ahead", type=int, default=330)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--db", default=os.path.join(BASE_DIR, "hotel_stays.db"))
    args = ap.parse_args(argv)

    print("=" * 66)
    print("  GHA DISCOVERY - PRICE HARVESTER (tanpa fabrikasi)")
    print("=" * 66)
    conn = sqlite3.connect(args.db, timeout=60.0)
    try:
        if args.hotel:
            targets = []
            for pth in args.hotel:
                row = conn.execute("SELECT id FROM hotels WHERE brand='GHA' AND official_url LIKE ?", (f"%/{pth}",)).fetchone()
                if row:
                    targets.append((row[0], pth))
                else:
                    print(f"  [!] {pth}: tidak ada di database GHA (jalankan crawlers/gha_master_crawler.py dulu)")
        else:
            targets = [(hid, page_path(u)) for hid, u in conn.execute("SELECT id, official_url FROM hotels WHERE brand='GHA' ORDER BY id")]
            targets = [(h, p) for h, p in targets if p]
        if args.limit:
            targets = targets[: args.limit]
        if not targets:
            print("[!] ERROR: tidak ada hotel GHA untuk diproses. Jalankan crawlers/gha_master_crawler.py dulu. Exit 1.")
            return 1

        from engine.browser_tools import MISSING_BROWSER_HELP, find_browser, launch_persistent
        path, kind = find_browser()
        if not path:
            print("[!] ERROR:\n" + MISSING_BROWSER_HELP)
            return 1
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("[!] ERROR: paket 'playwright' tidak terpasang. Pakai portable_python bawaan paket ini.")
            return 1

        dates = choose_dates(args.dates, args.days_ahead)
        print(f"  Browser : {kind} ({path})")
        print(f"  Hotel   : {len(targets)} | Tanggal per hotel: {len(dates)} ({dates[0]} .. {dates[-1]})")
        total = ok = 0
        profile = os.path.join(BASE_DIR, "crawlers", "pw_gha_session", "browser_profile")
        with sync_playwright() as p:
            try:
                ctx = launch_persistent(p, profile, headless=args.headless)
            except Exception as e:
                print(f"[!] ERROR: browser tidak bisa dibuka: {e}")
                return 1
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                try:
                    page.goto(SITE, wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    print(f"[!] ERROR: tidak bisa membuka ghadiscovery.com ({str(e).splitlines()[0]}). Periksa koneksi internet. Exit 1.")
                    return 1
                page.wait_for_timeout(4000)
                fetcher = PageFetcher(page)
                for i, (hid, pth) in enumerate(targets, 1):
                    try:
                        r = harvest_hotel(fetcher, conn, hid, pth, dates)
                    except Blocked as e:
                        print(f"[{i}/{len(targets)}] [!] Situs menolak permintaan ({e}). Berhenti; coba lagi nanti tanpa --headless.")
                        break
                    except Exception as e:
                        print(f"[{i}/{len(targets)}] {pth}: error - {e}")
                        continue
                    if r["skipped_reason"]:
                        print(f"[{i}/{len(targets)}] {pth}: dilewati - {r['skipped_reason']}")
                        continue
                    ok += 1
                    total += r["written"]
                    extra = f", {len(r['rejected'])} ditolak gerbang bukti" if r["rejected"] else ""
                    extra += f", {len(r['failed_dates'])} tanggal gagal" if r["failed_dates"] else ""
                    print(f"[{i}/{len(targets)}] {pth}: {r['written']} baris tersimpan{extra}")
            finally:
                ctx.close()
    finally:
        conn.close()
    print(f"\nSELESAI: {ok} hotel, {total} baris harga tersimpan.")
    if total == 0:
        print("[!] ERROR: tidak ada harga yang berhasil diambil. Exit 1.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
