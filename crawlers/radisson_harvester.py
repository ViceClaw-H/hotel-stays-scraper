#!/usr/bin/env python3
"""
Radisson Hotel Group - price harvester (Schema v2, zero fabrication).

What it does
  1. (optional) reads the official sitemaps to list Radisson hotels into hotel_stays.db;
  2. opens YOUR installed Chrome/Edge with a throw-away profile and, from inside radissonhotels.com,
     asks the site's own availability API for the price of one night on a spread of dates;
  3. saves every server response verbatim as evidence (engine.rate_writer hashes it) and stores one
     row per (date, room): cheapest public room-only rate, tax inclusive, plus points when the
     server states them.  See engine/extractors/radisson.py for the exact row rules.

What it never does: invent a price, a currency, a room name or a date. A room/date the server does
not price gets no row. If nothing could be harvested the script exits with code 1.

No cookie files and no login are needed: the browser session is created by the site itself.

Usage
    python crawlers/radisson_harvester.py                      # all Radisson hotels in the database
    python crawlers/radisson_harvester.py --limit 5            # first 5 hotels
    python crawlers/radisson_harvester.py --hotel radisson-blu-wiesbaden-schwarzer-bock
    python crawlers/radisson_harvester.py --dates 24 --days-ahead 330
    python crawlers/radisson_harvester.py --discover           # refresh the hotel list first
    python crawlers/radisson_harvester.py --headless           # no window (may be blocked by the site)
"""
import argparse
import datetime
import gzip
import json
import os
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from engine.extractors import radisson as rad_parse
from engine.rate_writer import write_rate_batch
from engine import harvest_state

SITE = "https://www.radissonhotels.com"
SOURCE_TYPE = "OFFICIAL_RADISSON_CRS"
STAYS_URL = SITE + "/availability-api/stays-by-rooms"
DELAY_SECONDS = 1.8          # polite pacing between requests
# v9f: sitemap paths under /hotels/ that are region / navigation pages, not hotels (seen 2026-11-03)
NON_HOTEL_SLUGS = {
    "asia-pacific", "europe", "middle-east-africa", "central-eastern-southern-europe", "choose-your-room",
    "americas", "africa", "middle-east", "asia", "china", "india", "nordics", "uk-ireland", "germany",
    "offers", "dining", "meetings", "services", "destinations", "brands", "search", "rooms",
}
STATUS_SOURCE = "RADISSON"
MAX_CONSECUTIVE_FAILURES = 4  # stop a hotel (and report) instead of hammering the site

# ----------------------------------------------------------------------------------------------
# Code that runs INSIDE the radissonhotels.com page (same origin, so the site's own cookies apply).
# Each returns plain data; none of it invents anything.
# ----------------------------------------------------------------------------------------------
JS_HOTEL_INFO = """async (slug) => {
  const r = await fetch('/en-us/hotels/' + slug, {headers: {accept: 'text/html'}});
  const html = await r.text();
  const m = html.match(/"branchCode":"([A-Z0-9]{4,10})"/);
  let ld = null;
  for (const b of html.matchAll(/<script type="application\\/ld\\+json">([\\s\\S]*?)<\\/script>/g)) {
    try {
      const d = JSON.parse(b[1]);
      for (const x of (Array.isArray(d) ? d : [d])) {
        if (x && m && x.identifier === m[1] && x.address) { ld = {name: x.name, address: x.address}; }
      }
    } catch (e) {}
  }
  return {status: r.status, code: m ? m[1] : null, ld: ld};
}"""

JS_ROOMS = """async (code) => {
  const r = await fetch('/content-api/hotels/' + code + '/rooms?galleryWithVideos=true',
                        {headers: {accept: 'application/json', 'Accept-Language': 'en-us'}});
  return {status: r.status, text: await r.text()};
}"""

JS_STAYS = """async (a) => {
  const h = {'content-type': 'application/json', accept: 'application/json',
             'Accept-Language': 'en-us', Saver: 'true'};
  const tx = sessionStorage.getItem('transactionId');
  if (tx) h.transactionId = tx;
  const body = {hotelCode: a.code, checkInDate: a.checkIn, checkOutDate: a.checkOut, searchType: 'lowest',
                occupancies: [{adults: a.adults, children: []}], sourceOfBusiness: 'desktop', groupedStays: true};
  const r = await fetch('/availability-api/stays-by-rooms', {method: 'POST', headers: h, body: JSON.stringify(body)});
  return {status: r.status, text: await r.text()};
}"""


class PageFetcher:
    """Wrapper that drives page navigation and evaluation directly without triggering in-page fetch blocks."""

    def __init__(self, page):
        self.page = page

    def hotel_info(self, slug: str) -> Dict[str, Any]:
        url = f"{SITE}/en-us/hotels/{slug}"
        try:
            resp = self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            status = resp.status if resp else 200
        except Exception as e:
            if is_browser_closed(e):
                raise                                   # let main() restart the browser; never relabel it as an HTTP status
            return {"status": None, "code": None, "ld": None,
                    "error": f"{type(e).__name__}: {str(e).splitlines()[0][:120] if str(e) else ''}"}
        
        self.page.wait_for_timeout(2000)
        html = self.page.content()
        m = re.search(r'"branchCode":"([A-Z0-9]{4,10})"', html)
        code = m.group(1) if m else None
        
        # If code was found in the page DOM, the page was successfully loaded
        if code:
            status = 200
        else:
            print(f"      [DEBUG hotel_info] slug={slug} status={status} code={code} title={self.page.title()[:60]}", flush=True)
        ld = None
        for b in re.findall(r'<script type="application/ld\+json">([\s\S]*?)</script>', html):
            try:
                d = json.loads(b)
                for x in (d if isinstance(d, list) else [d]):
                    if isinstance(x, dict) and code and x.get("identifier") == code and x.get("address"):
                        ld = {"name": x.get("name"), "address": x.get("address")}
            except Exception:
                pass
        return {"status": status, "code": code, "ld": ld}

    def rooms(self, code: str) -> Dict[str, Any]:
        return self.page.evaluate(JS_ROOMS, code)

    def stays(self, code: str, check_in: str, check_out: str, adults: int = 2) -> Dict[str, Any]:
        return self.page.evaluate(JS_STAYS, {"code": code, "checkIn": check_in, "checkOut": check_out, "adults": adults})


# ----------------------------------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------------------------------
def choose_dates(n: int, days_ahead: int, start_offset: int = 1, today: Optional[datetime.date] = None) -> List[str]:
    """n evenly spread stay dates between today+start_offset and today+days_ahead (inclusive)."""
    today = today or datetime.date.today()
    first, last = start_offset, max(start_offset, days_ahead)
    if n <= 1 or first == last:
        offsets = [first]
    else:
        offsets = sorted({first + round(i * (last - first) / (n - 1)) for i in range(n)})
    return [(today + datetime.timedelta(days=o)).isoformat() for o in offsets]


def next_day(d: str) -> str:
    return (datetime.date.fromisoformat(d) + datetime.timedelta(days=1)).isoformat()


def build_evidence(hotel_id: str, hotel_code: str, rooms_response: Any, stays: List[Dict[str, Any]],
                   adults: int = 2, harvested_at: Optional[str] = None) -> bytes:
    doc = {
        "format": rad_parse.EVIDENCE_FORMAT,
        "version": rad_parse.EVIDENCE_VERSION,
        "hotel_id": hotel_id,
        "hotel_code": hotel_code,
        "source_url": STAYS_URL,
        "harvested_at": harvested_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "occupancy": {"adults": adults, "children": 0},
        "rooms_response": rooms_response,
        "stays": stays,
    }
    return gzip.compress(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0)


class Blocked(RuntimeError):
    """The site refused us (HTTP 403/429): stop and tell the user, do not retry in a loop."""


MAX_RELAUNCHES = 5          # browser restarts allowed per run
MAX_NAV_STREAK = 8          # consecutive hotels that never got an answer from the site -> stop


def is_browser_closed(exc: BaseException) -> bool:
    m = str(exc).lower()
    return any(w in m for w in ("target page, context or browser has been closed", "browser has been closed", "has been closed", "target closed", "browser closed", "connection closed"))


# ----------------------------------------------------------------------------------------------
# Harvest one hotel
# ----------------------------------------------------------------------------------------------
def harvest_hotel(fetcher, conn: sqlite3.Connection, hotel_id: str, slug: str, dates: List[str],
                  workspace_dir: str = BASE_DIR, sleep=time.sleep, adults: int = 2) -> Dict[str, Any]:
    """Returns {'written': n, 'rejected': [...], 'failed_dates': [...], 'skipped_reason': str|None}."""
    info = fetcher.hotel_info(slug)
    if info.get("status") in (403, 429):
        raise Blocked(f"HTTP {info.get('status')} on the hotel page")
    code = info.get("code")
    if info.get("error"):
        return {"written": 0, "rejected": [], "failed_dates": [], "skipped_reason": f"navigation error: {info['error']}"}
    if info.get("status") != 200 or not code:
        return {"written": 0, "rejected": [], "failed_dates": [], "skipped_reason": f"hotel page gave no hotel code (HTTP {info.get('status')})"}

    # Avoid triggering Akamai block on /content-api/rooms; stays-by-rooms provides the authentic pricing
    rooms_json = {"rooms": []}

    stays: List[Dict[str, Any]] = []
    failed: List[str] = []
    consecutive = 0
    currency_seen: Optional[str] = None
    for d in dates:
        sleep(DELAY_SECONDS)
        res = fetcher.stays(code, d, next_day(d), adults)
        status = res.get("status")
        if status in (403, 429):
            print(f"      [DEBUG stays error] status={status} text={res.get('text', '')[:200]}", flush=True)
            raise Blocked(f"HTTP {status} while pricing {d}")
        parsed = None
        if status == 200:
            try:
                parsed = json.loads(res["text"])
            except ValueError:
                parsed = None
        if parsed is None:
            failed.append(d)
            consecutive += 1
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                break
            continue
        consecutive = 0
        stays.append({"stay_date": d, "response": parsed})
        currency_seen = currency_seen or parsed.get("currency")

    if not stays:
        return {"written": 0, "rejected": [], "failed_dates": failed, "skipped_reason": "no priced response"}

    evidence = build_evidence(hotel_id, code, rooms_json, stays, adults)
    rows = rad_parse.parse_evidence(evidence)
    if not rows:
        return {"written": 0, "rejected": [], "failed_dates": failed, "skipped_reason": "server returned no qualifying public room-only rate"}

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    res = write_rate_batch(
        conn,
        hotel_id=hotel_id,
        source_type=SOURCE_TYPE,
        source_url=STAYS_URL,
        rows=rows,
        evidence_relpath=f"evidence/radisson/raw/{hotel_id}__{ts}.json.gz",
        evidence_bytes=evidence,
        evidence_grade="RAW",
        workspace_dir=workspace_dir,
        notes="Official Radisson availability API, 1-night stays, 2 adults",
    )
    _update_hotel_facts(conn, hotel_id, info, currency_seen)
    return {"written": res.written, "rejected": res.rejected, "failed_dates": failed, "skipped_reason": None}


def _update_hotel_facts(conn: sqlite3.Connection, hotel_id: str, info: Dict[str, Any], currency: Optional[str]) -> None:
    """Replace the placeholder city/country/currency written by the roster step with what the site states."""
    ld = info.get("ld") or {}
    addr = ld.get("address") or {}
    city, country = addr.get("addressLocality"), addr.get("addressCountry")
    sets, vals = [], []
    if ld.get("name"):
        sets.append("name = ?"); vals.append(str(ld["name"]).strip())
    if city:
        sets.append("city = ?"); vals.append(str(city).strip())
    if country:
        sets.append("country = ?"); vals.append(str(country).strip())
    if currency:
        sets.append("currency = ?"); vals.append(str(currency).upper())
    if sets:
        conn.execute(f"UPDATE hotels SET {', '.join(sets)} WHERE id = ?", (*vals, hotel_id))
        conn.commit()


# ----------------------------------------------------------------------------------------------
# Roster (hotel list) from the official sitemaps - kept from the previous version
# ----------------------------------------------------------------------------------------------
def discover_radisson_hotels(limit=None):
    from curl_cffi import requests
    print("[roster] Reading Radisson sitemaps (rate-limited)...")
    try:
        r = requests.get(SITE + "/sitemapindex.xml", impersonate="chrome124", timeout=20)
        if r.status_code != 200:
            print(f"  [!] Sitemap index: HTTP {r.status_code}")
            return []
        root = ET.fromstring(r.content)
        locs = [e.text for e in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
        target = [s for s in locs if "hotel-overview" in s or "remaining-hotel" in s]
    except Exception as e:
        print(f"  [!] Could not read the sitemap index: {e}")
        return []
    found = set()
    for sm in (target[:limit] if limit else target):
        try:
            time.sleep(DELAY_SECONDS)
            resp = requests.get(sm, impersonate="chrome124", timeout=20)
            if resp.status_code != 200:
                continue
            for l in ET.fromstring(resp.content).findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc'):
                txt = l.text or ""
                if "/hotels/" in txt:
                    part = txt.split("/hotels/")[1].split("/")[0].split("?")[0]
                    if part and part.lower() not in NON_HOTEL_SLUGS:
                        found.add(part.lower())
        except Exception:
            pass
    print(f"  {len(found)} hotels found")
    return sorted(found)


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def ingest_radisson_roster(conn: sqlite3.Connection, slugs: List[str]) -> int:
    """Register hotels that are not yet in the database. City and country stay 'Unknown' and currency is
    the placeholder 'Unknown' until the price harvest reads the real values from the hotel's own
    page. Nothing is guessed."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    lifecycle = _has_column(conn, "hotels", "lifecycle_status")
    added = 0
    for s in slugs:
        hid = f"rad_{s.replace('-', '_')}"
        if conn.execute("SELECT 1 FROM hotels WHERE id = ?", (hid,)).fetchone():
            continue
        cols = ["id", "brand", "name", "city", "country", "currency", "loyalty_model", "award_category",
                "track_points", "official_url", "created_at"]
        vals = [hid, "RADISSON", s.replace("-", " ").title(), "Unknown", "Unknown", "Unknown", "RADISSON_REWARDS",
                "STANDARD", 1, f"{SITE}/en-us/hotels/{s}", now]
        if lifecycle:
            cols += ["lifecycle_status", "status_updated_at"]
            vals += ["ACTIVE", now]
        conn.execute(f"INSERT INTO hotels ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
        added += 1
    conn.commit()
    return added


def slug_from_url(url: str) -> Optional[str]:
    m = re.search(r"/hotels/([^/?#]+)", url or "")
    return m.group(1) if m else None


# ----------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Radisson price harvester (no fabrication)")
    ap.add_argument("--hotel", action="append", help="hotel slug (repeatable), e.g. radisson-blu-wiesbaden-schwarzer-bock")
    ap.add_argument("--limit", type=int, default=None, help="only the first N hotels")
    ap.add_argument("--dates", type=int, default=12, help="number of stay dates per hotel (default 12)")
    ap.add_argument("--days-ahead", type=int, default=330, help="furthest stay date, days from today (default 330)")
    ap.add_argument("--discover", action="store_true", help="refresh the hotel list from the official sitemaps first")
    ap.add_argument("--headless", action="store_true", help="run without a visible window")
    ap.add_argument("--db", default=os.path.join(BASE_DIR, "hotel_stays.db"))
    args = ap.parse_args(argv)

    print("=" * 66)
    print("  RADISSON HOTEL GROUP - PRICE HARVESTER (tanpa fabrikasi)")
    print("=" * 66)

    conn = sqlite3.connect(args.db, timeout=60.0)
    try:
        if args.discover or not conn.execute("SELECT 1 FROM hotels WHERE brand='RADISSON' LIMIT 1").fetchone():
            slugs = discover_radisson_hotels()
            if not slugs:
                print("[!] ERROR: tidak ada hotel Radisson yang bisa didaftar. Exit 1.")
                return 1
            print(f"  {ingest_radisson_roster(conn, slugs)} hotel baru dimasukkan ke database")

        if args.hotel:
            targets = []
            for s in args.hotel:
                hid = f"rad_{s.replace('-', '_')}"
                targets.append((hid, s))
            ingest_radisson_roster(conn, [s for _, s in targets])
        else:
            where = "brand='RADISSON'" + (" AND lifecycle_status='ACTIVE'" if _has_column(conn, "hotels", "lifecycle_status") else "")
            rows = conn.execute(
                f"""SELECT h.id, h.official_url FROM hotels h
                    LEFT JOIN harvest_status hs ON hs.hotel_id = h.id AND hs.source = '{STATUS_SOURCE}'
                    WHERE {where.replace("brand=", "h.brand=").replace("lifecycle_status", "h.lifecycle_status")}
                      AND NOT (COALESCE(hs.status, '') = 'INACTIVE' AND COALESCE(hs.reason, '') = 'NOT_A_HOTEL_PAGE')
                    ORDER BY h.id""").fetchall()
            targets = [(hid, slug_from_url(u)) for hid, u in rows
                       if slug_from_url(u) and slug_from_url(u).lower() not in NON_HOTEL_SLUGS]
        if args.limit:
            targets = targets[: args.limit]
        if not targets:
            print("[!] ERROR: tidak ada hotel untuk diproses. Exit 1.")
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
        total_rows = ok_hotels = 0
        stopped_early = False
        profile = os.path.join(BASE_DIR, "crawlers", "pw_radisson_session", "browser_profile")
        with sync_playwright() as p:
            try:
                ctx = launch_persistent(p, profile, headless=args.headless)
            except Exception as e:
                print(f"[!] ERROR: browser tidak bisa dibuka: {e}")
                return 1
            relaunches, nav_streak, attempted = 0, 0, 0
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                fetcher = PageFetcher(page)
                for i, (hid, slug) in enumerate(targets, 1):
                    r = None
                    for attempt in (1, 2):
                        try:
                            r = harvest_hotel(fetcher, conn, hid, slug, dates)
                            break
                        except Blocked as e:
                            print(f"[{i}/{len(targets)}] [!] Situs menolak permintaan ({e}). Berhenti; coba lagi nanti tanpa --headless.")
                            stopped_early = True
                            break
                        except Exception as e:
                            if not is_browser_closed(e):
                                print(f"[{i}/{len(targets)}] {slug}: error - {type(e).__name__}: {str(e).splitlines()[0][:160]}")
                                break
                            # The browser/page died (seen 2026-11-03: hotel 14, then 862 hotels were skipped as fake "HTTP 500"). Restart it.
                            relaunches += 1
                            print(f"[{i}/{len(targets)}] [!] browser tertutup ({str(e).splitlines()[0][:100]}); membuka ulang ({relaunches}/{MAX_RELAUNCHES})...", flush=True)
                            if relaunches > MAX_RELAUNCHES:
                                print("[!] browser terus tertutup; berhenti. Tutup Chrome lain yang memakai profil ini lalu jalankan ulang (hotel selesai tidak diulang).")
                                stopped_early = True
                                break
                            try:
                                ctx.close()
                            except Exception:
                                pass
                            try:
                                ctx = launch_persistent(p, profile, headless=args.headless)
                                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                                fetcher = PageFetcher(page)
                            except Exception as e2:
                                print(f"[!] browser tidak bisa dibuka ulang: {e2}")
                                stopped_early = True
                                break
                    if stopped_early:
                        break
                    if r is None:
                        nav_streak += 1
                        attempted += 1
                        if nav_streak >= MAX_NAV_STREAK:
                            print(f"[!] {MAX_NAV_STREAK} hotel berturut-turut gagal tanpa jawaban situs; berhenti (bukan 'HTTP 500' dari server).")
                            stopped_early = True
                            break
                        continue
                    attempted += 1
                    if r["skipped_reason"]:
                        if r["skipped_reason"].startswith("hotel page gave no hotel code"):
                            # v9f: a page without a hotel code is not a hotel (region page, 404): never retried as one
                            harvest_state.record(conn, source=STATUS_SOURCE, hotel_id=hid, status="INACTIVE",
                                                 reason="NOT_A_HOTEL_PAGE", detail=r["skipped_reason"],
                                                 url=f"{SITE}/en-us/hotels/{slug}")
                        nav_streak = nav_streak + 1 if r["skipped_reason"].startswith("navigation error") else 0
                        print(f"[{i}/{len(targets)}] {slug}: dilewati - {r['skipped_reason']}")
                        if nav_streak >= MAX_NAV_STREAK:
                            print(f"[!] {MAX_NAV_STREAK} hotel berturut-turut gagal membuka halaman; berhenti.")
                            stopped_early = True
                            break
                        continue
                    nav_streak = 0
                    ok_hotels += 1
                    total_rows += r["written"]
                    extra = f", {len(r['rejected'])} ditolak gerbang bukti" if r["rejected"] else ""
                    extra += f", {len(r['failed_dates'])} tanggal gagal" if r["failed_dates"] else ""
                    print(f"[{i}/{len(targets)}] {slug}: {r['written']} baris tersimpan{extra}")
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
    finally:
        conn.close()

    print(f"\nSELESAI: {ok_hotels} hotel, {total_rows} baris harga tersimpan.")
    if total_rows == 0:
        print("[!] ERROR: tidak ada harga yang berhasil diambil. Exit 1.")
        return 1
    if stopped_early:
        print(f"[!] PARSIAL: berhenti sebelum seluruh {len(targets)} hotel diproses (kode keluar 2). Jalankan ulang untuk melanjutkan.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
