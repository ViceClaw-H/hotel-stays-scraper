"""Wyndham Rewards rate + Free Night harvester (schema v2 contract).

Source: Wyndham's own booking-engine service
    GET https://www.wyndhamhotels.com/BWSServices/services/hotels/availability/getRoomsAndRates
There is NO calendar endpoint: one request per stay date. One response carries every room with every
rate plan (cash, Points+Cash and Free Night), so cash and points always come from the same answer.

What this script does, per hotel (all decisions are visible in logs/wyndham_crawler.log):
  1. property/brand ids: table wyndham_property_map, else scraped once from the hotel's own page
     (overview_propertyId / overview_brandId). A 200 page that is a 'Search Results' page = the hotel
     was removed -> INACTIVE. HTTP 404 -> INACTIVE. Several catalog ids can be one Wyndham property:
     it is harvested once under the first hotel id in catalog order, the others become DUPLICATE.
  2. dates: a FIXED grid (GRID_ID / ANCHOR below), nearest date first. The first 3 dates ARE the
     probes: their answers are stored as data, no call is wasted. All three "425 No availability" ->
     NO_AVAILABILITY / HTTP_425_CHANNEL (retry in 14 days). If some dates answer and later ones do not,
     the booking horizon is detected (after the last priced date, two consecutive 425 answers stop the
     hotel) instead of spending the remaining calls. 403/429/5xx/timeouts are FAILED/PARTIAL, never
     'no availability'.
  3. raw evidence: every parsed response is stored verbatim in one gzip JSON document per hotel and run
     (evidence/wyndham/raw/<hotel_id>__<timestamp>.json.gz). The rows are derived from that document
     with engine.extractors.wyndham.parse_evidence - exactly what the offline verifier replays.
  4. one DB transaction per hotel: rows + evidence registry through engine.rate_writer.write_rate_batch,
     state through engine.harvest_state.record (table harvest_status, source 'WYNDHAM'). Writer
     rejections are recorded in harvest_status, never dropped.

Request pacing: ONE shared throttle for all workers (max requests/second) with adaptive backoff on
403/429/5xx/timeouts (a shared pause that grows exponentially and decays after successes). If the
source keeps blocking, the run stops by itself.

Usage (from the project root):
    python crawlers\\wyndham_stream_harvester.py                     # everything due
    python crawlers\\wyndham_stream_harvester.py --limit 40 --country "United States"
    python crawlers\\wyndham_stream_harvester.py --hotel wynd_daysinnalmaga wynd_laquintaforsyth
    python crawlers\\wyndham_stream_harvester.py --retry-failed       # FAILED / PARTIAL hotels, now
    python crawlers\\wyndham_stream_harvester.py --refresh-days 30    # also re-harvest OK hotels older than 30 days
    python crawlers\\wyndham_stream_harvester.py --upgrade-legacy     # hotels that still only have pre-contract rows
    python crawlers\\wyndham_stream_harvester.py --grid weekly        # every Wed+Sat for 12 months (104 dates)
    python crawlers\\wyndham_stream_harvester.py --dry-run --limit 5  # no DB writes, evidence to a temp dir
"""
import argparse
import asyncio
import os
import random
import re
import sqlite3
import sys
import tempfile
import time
import traceback
import logging
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine import harvest_state                                   # noqa: E402
from engine.extractors import wyndham as wx                        # noqa: E402
from engine.rate_writer import write_rate_batch                    # noqa: E402
from engine.schema import HARVEST_STATUS_DDL, create_full_schema, schema_version   # noqa: E402

SOURCE = "WYNDHAM"
SOURCE_TYPE = "OFFICIAL_WYNDHAM_CRS"
DEFAULT_DB = os.path.join(ROOT, "hotel_stays.db")
DEFAULT_LOG = os.path.join(ROOT, "logs", "wyndham_crawler.log")
EVIDENCE_REL_DIR = "evidence/wyndham/raw"

# ------------------------------------------------------------------------------------------------
# The date grid. FIXED (not derived from today) so every run - and every row already in the database -
# refers to the same stay dates.
#   W24 : anchor + 14 days, then 12 months (30-day steps) x (next Wednesday + next Saturday) = 24 dates.
#         This is the grid the existing Wyndham rows were produced with (run of 2026-09-21).
#   W104: every Wednesday and Saturday over the 52 weeks starting anchor + 14 days = 104 dates.
# Dates before today are skipped (the writer rejects PAST_DATE).
# ------------------------------------------------------------------------------------------------
ANCHOR = date(2026, 9, 21)
GRID_ID = "W24-2026-09-21"
GRID_LEAD_DAYS = 14
_WED, _SAT = 2, 5


def stratified_dates(anchor: date = ANCHOR, months: int = 12) -> List[str]:
    base = anchor + timedelta(days=GRID_LEAD_DAYS)
    out = set()
    for m in range(months):
        ref = base + timedelta(days=m * 30)
        ahead_wed = (_WED - ref.weekday() + 7) % 7 or 7
        ahead_sat = (_SAT - ref.weekday() + 7) % 7 or 7
        out.add((ref + timedelta(days=ahead_wed)).isoformat())
        out.add((ref + timedelta(days=ahead_sat)).isoformat())
    return sorted(out)


def weekly_dates(anchor: date = ANCHOR) -> List[str]:
    start = anchor + timedelta(days=GRID_LEAD_DAYS)
    out = []
    for i in range(52 * 7):
        d = start + timedelta(days=i)
        if d.weekday() in (_WED, _SAT):
            out.append(d.isoformat())
    return out


def make_grid(kind: str = "stratified", anchor: date = ANCHOR) -> Tuple[str, List[str]]:
    if kind == "weekly":
        dates = weekly_dates(anchor)
        return f"W{len(dates)}-{anchor.isoformat()}", dates
    dates = stratified_dates(anchor)
    return f"W{len(dates)}-{anchor.isoformat()}", dates


# ------------------------------------------------------------------------------------------------
# HTTP
# ------------------------------------------------------------------------------------------------
API_BASE = "https://www.wyndhamhotels.com/BWSServices/services/hotels/availability/getRoomsAndRates"
API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.wyndhamhotels.com/",
}
PAGE_HEADERS = {
    "User-Agent": API_HEADERS["User-Agent"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def api_url(property_id: str, brand_id: str, stay_date: str) -> str:
    ci = datetime.strptime(stay_date, "%Y-%m-%d")
    co = ci + timedelta(days=1)
    return (f"{API_BASE}?brand_id={brand_id}&checkout_date={co.strftime('%m-%d-%Y')}&checkin_date={ci.strftime('%m-%d-%Y')}"
            f"&adults=1&children=0&rooms=1&propertyId={property_id}&isOrsId={property_id}&altPropId={property_id}"
            f"&useWRPoints=true&language=en-us")


@dataclass
class Stats:
    api_requests: int = 0          # HTTP attempts against the availability service (incl. retries)
    page_requests: int = 0         # HTTP attempts against hotel pages (property id discovery)
    retries: int = 0
    backoff_events: int = 0        # times the shared throttle was penalised (403/429/5xx/timeout/blocked page)
    backoff_seconds: float = 0.0   # total shared pause time imposed
    failed_requests: int = 0       # requests that ended without a usable answer after all retries


class AdaptiveThrottle:
    """One throttle shared by every worker.

    * spaces request starts by 1/max_rps (wider after penalties)
    * penalize(): a 403/429/5xx/timeout pauses ALL workers for an exponentially growing time
      (base * 2^(level-1), capped); several workers hitting the same event count as one escalation
    * success(): after 40 clean answers the level relaxes by one
    * `blocked` turns True after `abort_after` consecutive bad answers: the run stops by itself
    """

    def __init__(self, max_rps: float = 5.0, base_delay: float = 5.0, max_delay: float = 120.0, abort_after: int = 40):
        self.min_interval = 1.0 / max_rps
        self.base_delay, self.max_delay, self.abort_after = base_delay, max_delay, abort_after
        self.level = 0
        self.pause_until = 0.0
        self.next_slot = 0.0
        self.ok_streak = 0
        self.consecutive_bad = 0
        self.events = 0
        self.paused_seconds = 0.0
        self.blocked = False

    async def wait(self) -> None:
        now = time.monotonic()
        start = max(now, self.pause_until, self.next_slot)
        self.next_slot = start + self.min_interval * (1 + 0.5 * self.level)
        if start > now:
            await asyncio.sleep(start - now)

    def penalize(self) -> float:
        now = time.monotonic()
        self.events += 1
        self.ok_streak = 0
        self.consecutive_bad += 1
        if self.consecutive_bad >= self.abort_after:
            self.blocked = True
        if now < self.pause_until:              # already paused for this incident: do not escalate again
            return 0.0
        self.level = min(self.level + 1, 6)
        delay = min(self.max_delay, self.base_delay * (2 ** (self.level - 1))) * random.uniform(0.9, 1.2)
        self.pause_until = now + delay
        self.paused_seconds += delay
        return delay

    def success(self) -> None:
        self.consecutive_bad = 0
        self.ok_streak += 1
        if self.level and self.ok_streak >= 40:
            self.level -= 1
            self.ok_streak = 0


@dataclass
class Raw:
    """What one request finally produced (after retries)."""
    url: str
    http_status: Optional[int]
    body: Optional[str]
    error: Optional[str]
    fetched_at: str
    attempts: int = 1
    final_url: Optional[str] = None       # after redirects (hotel pages)


class Fetcher:
    def __init__(self, throttle: AdaptiveThrottle, stats: Stats, log: logging.Logger, timeout: float = 20.0,
                 max_attempts: int = 3, session=None):
        self.throttle, self.stats, self.log = throttle, stats, log
        self.timeout, self.max_attempts = timeout, max_attempts
        self.session = session

    async def __aenter__(self):
        if self.session is None:
            from curl_cffi.requests import AsyncSession
            self.session = AsyncSession()
        return self

    async def __aexit__(self, *exc):
        try:
            await self.session.close()
        except Exception:
            pass

    async def get(self, url: str, *, page: bool = False) -> Raw:
        headers = PAGE_HEADERS if page else API_HEADERS
        status, body, err = None, None, None
        attempts = 0
        for attempt in range(1, self.max_attempts + 1):
            attempts = attempt
            await self.throttle.wait()
            if page:
                self.stats.page_requests += 1
            else:
                self.stats.api_requests += 1
            if attempt > 1:
                self.stats.retries += 1
            try:
                r = await self.session.get(url, headers=headers, impersonate="chrome124", timeout=self.timeout)
                status, body, err = r.status_code, r.text, None
            except Exception as e:                       # timeouts, resets, TLS errors
                status, body, err = None, None, f"{type(e).__name__}: {e}"
                self._penalize(f"{err} <- {url}")
                continue
            if status == 200:
                if not page and not body.lstrip().startswith("{"):     # interstitial / challenge page, not the API
                    err = "HTTP 200 but the body is not JSON (blocked or interstitial page)"
                    self._penalize(f"{err} <- {url}")
                    continue
                self.throttle.success()
                return Raw(url, 200, body, None, _now(), attempts, str(r.url))
            if status in (403, 429) or status >= 500:
                err = f"HTTP {status}"
                self._penalize(f"{err} <- {url}")
                continue
            self.throttle.success()                                    # 404 & co: a definite answer, no retry
            return Raw(url, status, body, f"HTTP {status}", _now(), attempts, str(r.url))
        self.stats.failed_requests += 1
        return Raw(url, status, body, err, _now(), attempts)

    def _penalize(self, why: str) -> None:
        self.stats.backoff_events += 1
        delay = self.throttle.penalize()
        if delay:
            self.stats.backoff_seconds += delay
            self.log.warning("BACKOFF level=%s pause=%.1fs (%s)", self.throttle.level, delay, why[:200])


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------------------------------------
# Hotel page -> property id
# ------------------------------------------------------------------------------------------------
_P_MAIN = re.compile(r'overview_propertyId\s*=\s*["\']([0-9]+)["\']')
_B_MAIN = re.compile(r'overview_brandId\s*=\s*["\']([A-Za-z0-9]+)["\']')
_P_ALT = (re.compile(r'["\']propertyId["\']\s*:\s*["\']?([0-9]{4,6})["\']?'), re.compile(r'data-propertyid=["\']([0-9]{4,6})["\']'))
_B_ALT = (re.compile(r'["\']brandId["\']\s*:\s*["\']?([A-Za-z0-9]{2,4})["\']?'), re.compile(r'data-brandid=["\']([A-Za-z0-9]{2,4})["\']'))
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


@dataclass
class PageVerdict:
    kind: str                       # OK | INACTIVE | FAILED
    property_id: str = ""
    brand_id: str = ""
    reason: str = ""
    detail: str = ""
    retry_days: int = -1


def classify_page(url: str, status: Optional[int], text: Optional[str], error: Optional[str],
                  final_url: Optional[str] = None) -> PageVerdict:
    if status is None:
        return PageVerdict("FAILED", reason="TIMEOUT_OR_CONNECTION", detail=error or "no response")
    if status == 404:
        return PageVerdict("INACTIVE", reason="HTTP_404", detail=f"HTTP 404 for {url}")
    if status != 200:
        return PageVerdict("FAILED", reason=f"HTTP_{status}", detail=error or f"HTTP {status}")
    t = text or ""
    tm = _TITLE.search(t)
    title = re.sub(r"\s+", " ", tm.group(1)).strip() if tm else ""
    p = _P_MAIN.search(t)
    b = _B_MAIN.search(t)
    if not p and "search results" not in title.lower():
        p = next((m for m in (rx.search(t) for rx in _P_ALT) if m), None)
    if not b and p:
        b = next((m for m in (rx.search(t) for rx in _B_ALT) if m), None)
    if p and b:
        return PageVerdict("OK", property_id=p.group(1), brand_id=b.group(1))
    if not p and "search results" in title.lower():
        return PageVerdict("INACTIVE", reason="REDIRECT_TO_SEARCH",
                           detail=f"HTTP 200, no propertyId in page; page title '{title}'; catalog URL {url}; resolved to {final_url or url}")
    return PageVerdict("FAILED", reason="PAGE_NO_PROPERTY_ID" if not p else "PAGE_NO_BRAND_ID",
                       detail=f"HTTP 200 but no {'propertyId' if not p else 'brandId'} found; page title '{title[:120]}'")


# ------------------------------------------------------------------------------------------------
# Date ladder (pure logic over an injected fetch function - unit-tested with fixtures)
# ------------------------------------------------------------------------------------------------
@dataclass
class Entry:
    stay_date: str
    raw: Raw
    parsed: wx.ParsedResponse


@dataclass
class Ladder:
    entries: List[Entry] = field(default_factory=list)
    stop: str = "complete"          # complete | dead | horizon | failing | first_wave_failed
    stop_detail: str = ""


async def run_ladder(fetch: Callable[[str], Awaitable[Raw]], dates: List[str], probes: int = 3, wave: int = 3,
                     horizon_misses: int = 2, max_consecutive_fails: int = 3) -> Ladder:
    """Walk the dates nearest-first.

    * the first `probes` dates are fetched together (they are the probes AND real data)
    * all probes 'no availability' -> stop ('dead'); a probe failing without any priced date -> stop
    * after a priced date, a 'no availability' answer switches to one-date-at-a-time testing; after
      `horizon_misses` consecutive ones the hotel MAY be at its booking horizon. Two misses in a row can
      also be a sold-out/closed stretch (seen live: H+ Hotel Bremen answers 425 on grid dates 2-3 and 5,
      then prices every date up to the end; Wyndham Grand Xishuangbanna reopens for the last 4), so
      the last grid date is tested once: still 425 -> horizon confirmed, stop; priced -> not a horizon,
      every remaining date is fetched.
    * otherwise dates are fetched in waves of `wave` concurrent requests
    """
    lad = Ladder()
    have: Dict[str, Entry] = {}

    def add(d: str, raw: Raw) -> Entry:
        pr = wx.parse_response(d, raw.url, raw.http_status, raw.body, raw.error)
        e = Entry(d, raw, pr)
        lad.entries.append(e)
        have[d] = e
        return e

    i, n = 0, len(dates)
    seen_ok = False
    consec_na = 0
    consec_fail = 0
    testing = False
    horizon_check = True
    while i < n:
        size = probes if i == 0 else (1 if testing else wave)
        batch = [d for d in dates[i:i + size] if d not in have]
        i += len(dates[i:i + size])
        raws = await asyncio.gather(*(fetch(d) for d in batch))
        for d, raw in zip(batch, raws):
            e = add(d, raw)
            kind = e.parsed.kind
            if kind == wx.KIND_OK:
                seen_ok, consec_na, consec_fail, testing = True, 0, 0, False
            elif kind == wx.KIND_NOAVAIL:
                consec_na += 1
                consec_fail = 0
                if seen_ok:
                    testing = True
            else:
                consec_fail += 1
        if not seen_ok:
            lad.stop = "dead" if all(e.parsed.kind == wx.KIND_NOAVAIL for e in lad.entries) else "first_wave_failed"
            break
        if horizon_check and consec_na >= horizon_misses:
            tail = [e.stay_date for e in lad.entries[-consec_na:]]
            last = dates[-1]
            if last in have:
                confirm = have[last]
            elif i < n:
                confirm = add(last, await fetch(last))
            else:
                confirm = None
            if confirm is not None and confirm.parsed.kind == wx.KIND_OK:
                horizon_check, consec_na, testing = False, 0, False     # reopens later: not a horizon, walk everything
                continue
            lad.stop, lad.stop_detail = "horizon", ", ".join(tail)
            break
        if consec_fail >= max_consecutive_fails:
            lad.stop = "failing"
            break
    lad.entries.sort(key=lambda e: e.stay_date)
    return lad


# ------------------------------------------------------------------------------------------------
# Verdict for one hotel
# ------------------------------------------------------------------------------------------------
@dataclass
class HotelResult:
    hotel_id: str
    status: str
    reason: Optional[str] = None
    detail: Optional[str] = None
    url: Optional[str] = None
    dates_ok: Optional[int] = None
    dates_total: Optional[int] = None
    horizon_last_ok: Optional[str] = None
    retry_days: int = -1
    cash_none: int = 0
    api_requests: int = 0
    page_requests: int = 0
    rejected: List[Tuple[str, str]] = field(default_factory=list)
    seconds: float = 0.0
    evidence_bytes: int = 0


def assess_without_rows(lad: Ladder) -> Tuple[str, str, str, str]:
    """Status for a hotel that produced no priced date. Returns (status, reason, detail, url)."""
    fails = [e for e in lad.entries if e.parsed.kind == wx.KIND_FAIL]
    if fails:
        f = fails[0].parsed
        return "FAILED", f.code, f.message, f.url
    if lad.entries:
        nas = [e for e in lad.entries if e.parsed.kind == wx.KIND_NOAVAIL]
        if nas and len(nas) == len(lad.entries):
            p = nas[0].parsed
            return "NO_AVAILABILITY", p.code, p.message, p.url
        oks = [e for e in lad.entries if e.parsed.kind == wx.KIND_OK]
        if oks:
            return "FAILED", "NO_PRICE_IN_RESPONSE", "rooms were returned but no cash or Free Night price could be read", oks[0].parsed.url
    return "FAILED", "NO_RESPONSES", "no request was made", ""


def build_result(hotel_id: str, lad: Ladder, rows: list, rejected: List[Tuple[str, str]], written: int) -> HotelResult:
    oks = [e for e in lad.entries if e.parsed.kind == wx.KIND_OK]
    total = len(lad.entries)
    res = HotelResult(hotel_id, "OK", dates_ok=written, dates_total=total)
    res.rejected = list(rejected)
    res.cash_none = sum(1 for r in rows if r.cash_rate is None)
    if oks:
        res.horizon_last_ok = oks[-1].stay_date
    fails = [e for e in lad.entries if e.parsed.kind == wx.KIND_FAIL]
    if not oks:
        res.status, res.reason, res.detail, res.url = assess_without_rows(lad)
        return res
    if written == 0:
        codes = _reject_summary(rejected)
        res.status, res.reason = "FAILED", "ALL_ROWS_REJECTED"
        res.detail = f"writer rejected every row: {codes}" if rejected else "no row could be built from the responses"
        res.url = oks[0].parsed.url
        return res
    problems = []
    if fails:
        f = fails[0].parsed
        res.reason, res.detail, res.url = f.code, f.message, f.url
        problems.append(f"{len(fails)} request(s) failed (first: {f.code} on {f.stay_date})")
    if rejected:
        codes = _reject_summary(rejected)
        problems.append(f"writer rejected {len(rejected)} row(s): {codes}")
        if not fails:
            res.reason = "WRITER_REJECTED"
            res.detail = f"writer rejected: {codes}"
            bad = rejected[0][0]
            res.url = next((e.parsed.url for e in lad.entries if e.stay_date == bad), oks[0].parsed.url)
        else:
            res.detail = f"{res.detail} | writer rejected: {codes}"
    if problems:
        res.status = "PARTIAL"
        return res
    if lad.stop == "horizon":
        first_miss = next((e for e in lad.entries if e.stay_date > oks[-1].stay_date and e.parsed.kind == wx.KIND_NOAVAIL), None)
        res.reason = "BOOKING_HORIZON"
        if first_miss:
            res.detail, res.url = first_miss.parsed.message, first_miss.parsed.url
    return res


def _reject_summary(rejected: List[Tuple[str, str]]) -> str:
    by: Dict[str, List[str]] = {}
    for d, code in rejected:
        by.setdefault(code, []).append(d)
    return "; ".join(f"{c} x{len(ds)} ({', '.join(ds[:3])}{'...' if len(ds) > 3 else ''})" for c, ds in sorted(by.items()))


# ------------------------------------------------------------------------------------------------
# Database helpers
# ------------------------------------------------------------------------------------------------
PROPERTY_MAP_DDL = """
CREATE TABLE IF NOT EXISTS wyndham_property_map (
    hotel_id TEXT PRIMARY KEY,
    property_id TEXT NOT NULL,
    brand_id TEXT NOT NULL,
    resolved_at TEXT
)"""


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(PROPERTY_MAP_DDL)
    conn.execute(HARVEST_STATUS_DDL)
    conn.commit()


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def load_catalog(conn: sqlite3.Connection) -> List[dict]:
    """Wyndham hotels in catalog order (country, name, id) - the order that decides the canonical id of duplicates."""
    cur = conn.execute("SELECT id, name, city, country, official_url FROM hotels WHERE brand = 'WYNDHAM' ORDER BY country, name, id")
    return [{"id": r[0], "name": r[1], "city": r[2], "country": r[3], "url": r[4]} for r in cur]


def load_property_map(conn: sqlite3.Connection) -> Dict[str, Tuple[str, str]]:
    if not _has_table(conn, "wyndham_property_map"):
        return {}
    return {h: (p, b) for h, p, b in conn.execute("SELECT hotel_id, property_id, brand_id FROM wyndham_property_map")}


def load_states(conn: sqlite3.Connection) -> Dict[str, dict]:
    if not _has_table(conn, "harvest_status"):
        return {}
    return harvest_state.load_all(conn, SOURCE)


def load_legacy_hotel_ids(conn: sqlite3.Connection) -> set:
    """Hotels that still carry Wyndham rows not produced by this harvester (no raw evidence from it)."""
    grade = "rr.evidence_grade <> 'RAW' OR " if schema_version(conn) >= 2 else ""
    cur = conn.execute(
        f"""SELECT DISTINCT rc.hotel_id FROM rate_records rr JOIN room_categories rc ON rc.id = rr.room_id
            WHERE rr.source_type = ? AND ({grade}rr.evidence_file IS NULL OR rr.evidence_file NOT LIKE ?)""",
        (SOURCE_TYPE, EVIDENCE_REL_DIR + "/%"))
    return {r[0] for r in cur}


def select_queue(catalog: List[dict], states: Dict[str, dict], args, legacy_ids: Optional[set] = None,
                 today: Optional[date] = None) -> List[dict]:
    hotels = catalog
    if args.country:
        hotels = [h for h in hotels if (h["country"] or "").lower() == args.country.lower()]
    if args.hotel:
        wanted = {x for x in args.hotel}
        by_id = {h["id"]: h for h in catalog}
        missing = wanted - set(by_id)
        if missing:
            raise SystemExit(f"unknown Wyndham hotel id(s): {', '.join(sorted(missing))}")
        queue = [h for h in hotels if h["id"] in wanted] if args.country else [by_id[i] for i in args.hotel if i in by_id]
    elif args.retry_failed:
        queue = [h for h in hotels if (states.get(h["id"]) or {}).get("status") in ("FAILED", "PARTIAL")]
    else:
        queue = [h for h in hotels if harvest_state.is_due(states.get(h["id"]), today=today, refresh_days=args.refresh_days)]
        if args.upgrade_legacy:
            queue = [h for h in queue if h["id"] in (legacy_ids or set())]
        queue.sort(key=lambda h: 0 if states.get(h["id"]) is None else 1)     # never-seen first; stable in catalog order
    if args.limit:
        queue = queue[: args.limit]
    return queue


# ------------------------------------------------------------------------------------------------
# The harvester
# ------------------------------------------------------------------------------------------------
class Harvester:
    def __init__(self, *, conn_r, conn_w, fetcher: Fetcher, stats: Stats, log: logging.Logger, workspace: str,
                 grid_id: str, dates: List[str], catalog: List[dict], upgrade_legacy: bool = False,
                 dry_run: bool = False, date_concurrency: int = 3, today: Optional[date] = None):
        self.conn_r, self.conn_w, self.fetcher, self.stats, self.log = conn_r, conn_w, fetcher, stats, log
        self.workspace, self.grid_id, self.dry_run = workspace, grid_id, dry_run
        self.upgrade_legacy, self.date_concurrency = upgrade_legacy, date_concurrency
        self.today = today or date.today()
        self.dates = [d for d in dates if d >= self.today.isoformat()]
        self.prop_map = load_property_map(conn_r)
        self.claims: Dict[str, str] = {}
        for h in catalog:                                   # catalog order decides the canonical hotel
            m = self.prop_map.get(h["id"])
            if m:
                self.claims.setdefault(m[0], h["id"])
        self.abort = False

    # -- one hotel ----------------------------------------------------------------------------
    async def process(self, hotel: dict) -> HotelResult:
        hid = hotel["id"]
        t0 = time.monotonic()
        ctx = {"api": 0, "page": 0}                         # this hotel's own HTTP attempts (stats are global)
        try:
            res = await self._process(hotel, ctx)
        except Exception as e:                              # a bug must not kill the run or vanish
            self.log.error("INTERNAL_ERROR %s\n%s", hid, traceback.format_exc())
            res = HotelResult(hid, "FAILED", "INTERNAL_ERROR", f"{type(e).__name__}: {e}", None)
            self._store(res, None)
        res.seconds = time.monotonic() - t0
        res.api_requests = ctx["api"]
        res.page_requests = ctx["page"]
        return res

    async def _process(self, hotel: dict, ctx: dict) -> HotelResult:
        hid = hotel["id"]
        meta = self.prop_map.get(hid)
        new_map = None
        if meta is None:
            url = hotel.get("url")
            if not url:
                res = HotelResult(hid, "FAILED", "MISSING_URL", "hotel has no official_url in the catalog", None, retry_days=30)
                self._store(res, None)
                return res
            raw = await self.fetcher.get(url, page=True)
            ctx["page"] += raw.attempts
            verdict = classify_page(url, raw.http_status, raw.body, raw.error, raw.final_url)
            if verdict.kind != "OK":
                res = HotelResult(hid, verdict.kind, verdict.reason, verdict.detail, url, retry_days=verdict.retry_days)
                self._store(res, None)
                return res
            meta = (verdict.property_id, verdict.brand_id)
            new_map = (hid, meta[0], meta[1])
            self.prop_map[hid] = meta
        pid, bid = meta

        owner = self.claims.setdefault(pid, hid)
        if owner != hid:
            res = HotelResult(hid, "DUPLICATE", owner, f"same Wyndham propertyId {pid} as {owner}; harvested there", hotel.get("url"))
            self._store(res, new_map)
            return res

        async def fetch(d: str) -> Raw:
            raw = await self.fetcher.get(api_url(pid, bid, d))
            ctx["api"] += raw.attempts
            return raw

        lad = await run_ladder(fetch, self.dates, wave=self.date_concurrency)
        responses = []
        for e in lad.entries:
            item = {"stay_date": e.stay_date, "request_url": e.raw.url, "http_status": e.raw.http_status,
                    "fetched_at": e.raw.fetched_at, "body": e.raw.body}
            if e.raw.body is not None and len(e.raw.body) > 2000 and (e.raw.http_status != 200 or not e.raw.body.lstrip().startswith("{")):
                item["body"], item["truncated"] = e.raw.body[:2000], True
            if e.raw.error:
                item["error"] = e.raw.error
            responses.append(item)

        evidence = None
        rows: list = []
        if any(e.parsed.kind == wx.KIND_OK for e in lad.entries):
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            evidence = wx.build_evidence(hid, pid, bid, self.grid_id, _now(), responses)
            rows = wx.parse_evidence(evidence)                 # rows come from the saved bytes, not from live objects
            self.log.info("EVIDENCE %s %d bytes gz, %d rows (%s)", hid, len(evidence), len(rows), stamp)
        else:
            stamp = ""
        for e in lad.entries:
            p = e.parsed
            row = p.row
            self.log.info("  %s %s %s %s%s%s", hid, e.stay_date, p.kind, p.code or "",
                          f" cash={row.cash_rate} {row.currency} pts={row.points_required} room='{row.room_name}'" if row else "",
                          f" msg={p.message[:120]!r}" if p.message else "")
        res = self._store_rows(hid, hotel, lad, rows, evidence, stamp, new_map)
        if lad.stop == "horizon":
            self.log.info("HORIZON %s last priced date %s, stopped after no-availability on %s", hid, res.horizon_last_ok, lad.stop_detail)
        return res

    # -- persistence --------------------------------------------------------------------------
    def _store_rows(self, hid, hotel, lad: Ladder, rows, evidence, stamp, new_map) -> HotelResult:
        conn = self.conn_w
        rejected: List[Tuple[str, str]] = []
        written = 0
        ev_rel = None
        try:
            if rows:
                ev_rel = f"{EVIDENCE_REL_DIR}/{hid}__{stamp}.json.gz"
                wres = write_rate_batch(
                    conn, hotel_id=hid, source_type=SOURCE_TYPE, source_url=rows[0].source_url, rows=rows,
                    evidence_relpath=ev_rel, evidence_bytes=evidence, evidence_grade="RAW",
                    workspace_dir=self.workspace, allow_points_removal=self.upgrade_legacy, commit=False)
                rejected, written = wres.rejected, wres.written
            res = build_result(hid, lad, rows, rejected, written)
            if evidence:
                res.evidence_bytes = len(evidence)
            self._record(conn, res, new_map)
            conn.commit()
        except Exception as e:
            conn.rollback()
            self.log.error("DB_ERROR %s\n%s", hid, traceback.format_exc())
            res = HotelResult(hid, "FAILED", "DB_WRITE_ERROR", f"{type(e).__name__}: {e}", rows[0].source_url if rows else None)
            self._store(res, new_map)
            return res
        if rejected:
            self.log.warning("REJECTED %s %s", hid, _reject_summary(rejected))
        if ev_rel and not self.dry_run:
            self._prune_old_evidence(hid, ev_rel)
        return res

    def _store(self, res: HotelResult, new_map) -> None:
        try:
            self._record(self.conn_w, res, new_map)
            self.conn_w.commit()
        except Exception:
            self.conn_w.rollback()
            self.log.error("DB_ERROR recording state of %s\n%s", res.hotel_id, traceback.format_exc())

    def _record(self, conn, res: HotelResult, new_map) -> None:
        if new_map:
            conn.execute(
                """INSERT INTO wyndham_property_map (hotel_id, property_id, brand_id, resolved_at) VALUES (?,?,?,?)
                   ON CONFLICT(hotel_id) DO UPDATE SET property_id=excluded.property_id, brand_id=excluded.brand_id,
                       resolved_at=excluded.resolved_at""", (*new_map, _now()))
        harvest_state.record(conn, SOURCE, res.hotel_id, res.status, reason=res.reason, detail=res.detail, url=res.url,
                             grid_id=self.grid_id, dates_ok=res.dates_ok, dates_total=res.dates_total,
                             horizon_last_ok=res.horizon_last_ok, retry_days=res.retry_days, commit=False)

    def _prune_old_evidence(self, hid: str, keep_rel: str) -> None:
        """Remove this hotel's earlier evidence files once no row references them any more."""
        try:
            d = os.path.join(self.workspace, EVIDENCE_REL_DIR)
            rx = re.compile(r"^" + re.escape(hid) + r"__\d{8}T\d{6}\.json\.gz$")
            for name in os.listdir(d):
                rel = f"{EVIDENCE_REL_DIR}/{name}"
                if rel == keep_rel or not rx.match(name):
                    continue
                if self.conn_w.execute("SELECT 1 FROM rate_records WHERE evidence_file = ? LIMIT 1", (rel,)).fetchone():
                    continue
                os.remove(os.path.join(d, name))
                self.conn_w.execute("DELETE FROM evidence_registry WHERE evidence_file = ?", (rel,))
                self.conn_w.commit()
                self.log.info("PRUNED unreferenced evidence %s", rel)
        except Exception as e:
            self.log.warning("prune of old evidence for %s failed: %s", hid, e)


# ------------------------------------------------------------------------------------------------
# Run
# ------------------------------------------------------------------------------------------------
def setup_logger(path: str) -> logging.Logger:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    log = logging.getLogger("wyndham")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    h = RotatingFileHandler(path, maxBytes=25_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.propagate = False
    return log


async def run(args) -> int:
    log = setup_logger(args.log_file)
    grid_id, dates = make_grid(args.grid, date.fromisoformat(args.anchor))
    tmp_ws = None
    workspace = args.workspace
    if args.dry_run:
        tmp_ws = tempfile.mkdtemp(prefix="wyndham_dry_")
        workspace = tmp_ws
        conn_r = sqlite3.connect(Path(args.db).resolve().as_uri() + "?mode=ro", uri=True)
        conn_w = sqlite3.connect(":memory:")
        create_full_schema(conn_w)
        ensure_tables(conn_w)
    else:
        conn_r = conn_w = sqlite3.connect(args.db, timeout=60)
        from engine.schema import require_v2
        require_v2(conn_w, "Wyndham harvester")   # before it creates tables or makes a single request
        conn_w.execute("PRAGMA journal_mode=WAL")
        conn_w.execute("PRAGMA busy_timeout=60000")
        ensure_tables(conn_w)

    catalog = load_catalog(conn_r)
    states = load_states(conn_r)
    legacy = load_legacy_hotel_ids(conn_r) if args.upgrade_legacy else None
    queue = select_queue(catalog, states, args, legacy)

    stats = Stats()
    throttle = AdaptiveThrottle(max_rps=args.max_rps)
    counts: Dict[str, int] = {}
    fail_lines = 0

    print("=" * 78)
    print(f"WYNDHAM harvester | grid {grid_id} ({len(dates)} dates, {len([d for d in dates if d >= date.today().isoformat()])} still in the future)"
          f" | catalog {len(catalog):,} | queue {len(queue):,} | workers {args.workers} | max {args.max_rps:g} req/s")
    print(f"db: {args.db}{'  [DRY RUN: no DB writes, evidence in ' + tmp_ws + ']' if args.dry_run else ''}")
    print(f"trace log: {args.log_file}")
    print("=" * 78, flush=True)
    log.info("RUN START grid=%s dates=%d queue=%d workers=%d dry_run=%s args=%s", grid_id, len(dates), len(queue), args.workers, args.dry_run, vars(args))
    if not queue:
        print("Nothing due. (use --refresh-days N, --retry-failed or --hotel ID to force)")
        return 0

    q: asyncio.Queue = asyncio.Queue()
    for h in queue:
        q.put_nowait(h)
    t_start = time.monotonic()
    done = 0
    agg = {"hotels_api": 0, "api_req": 0, "page_req": 0, "cash_none": 0, "dates_ok": 0, "evidence_bytes": 0}
    live_hotels = 0

    async with Fetcher(throttle, stats, log) as fetcher:
        hv = Harvester(conn_r=conn_r, conn_w=conn_w, fetcher=fetcher, stats=stats, log=log, workspace=workspace,
                       grid_id=grid_id, dates=dates, catalog=catalog, upgrade_legacy=args.upgrade_legacy,
                       dry_run=args.dry_run, date_concurrency=args.date_concurrency)

        def report(res: HotelResult) -> None:
            nonlocal done, live_hotels, fail_lines
            done += 1
            counts[res.status] = counts.get(res.status, 0) + 1
            agg["api_req"] += res.api_requests
            agg["page_req"] += res.page_requests
            agg["cash_none"] += res.cash_none
            agg["dates_ok"] += res.dates_ok or 0
            agg["evidence_bytes"] += res.evidence_bytes
            if res.api_requests:
                live_hotels += 1
            log.info("HOTEL %s %s reason=%s ok=%s/%s cash_none=%d api_req=%d page_req=%d %.1fs horizon=%s url=%s detail=%s",
                     res.hotel_id, res.status, res.reason, res.dates_ok, res.dates_total, res.cash_none, res.api_requests,
                     res.page_requests, res.seconds, res.horizon_last_ok, res.url, (res.detail or "")[:300])
            if res.status in ("FAILED", "PARTIAL"):
                fail_lines += 1
                print(f"  {res.status:<8} {res.hotel_id} | {res.reason} | {(res.detail or '')[:110]} | {res.url}", flush=True)
            if done % 50 == 0 or done == len(queue):
                el = time.monotonic() - t_start
                print(f"[{done:>6}/{len(queue)}] {el/60:6.1f} min | " +
                      " ".join(f"{k}={v}" for k, v in sorted(counts.items())) +
                      f" | api_req={stats.api_requests} ({stats.api_requests / max(done, 1):.1f}/hotel) pages={stats.page_requests}"
                      f" backoffs={stats.backoff_events} | {done / max(el / 60, 1e-9):.0f} hotels/min", flush=True)

        async def worker():
            while not hv.abort:
                try:
                    h = q.get_nowait()
                except asyncio.QueueEmpty:
                    return
                report(await hv.process(h))
                if throttle.blocked:
                    hv.abort = True
                    print(f"STOPPING: {throttle.consecutive_bad} consecutive blocked/failed answers - the source is refusing us. "
                          f"Finished hotels are saved; run again later (FAILED hotels retry after 1 day).", flush=True)

        try:
            await asyncio.gather(*(worker() for _ in range(max(1, args.workers))))
        except asyncio.CancelledError:
            pass

    el = time.monotonic() - t_start
    print("-" * 78)
    print(f"DONE {done}/{len(queue)} hotels in {el/60:.1f} min | " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"requests: api={stats.api_requests} pages={stats.page_requests} retries={stats.retries} "
          f"backoff_events={stats.backoff_events} ({stats.backoff_seconds:.0f}s paused) failed_requests={stats.failed_requests}")
    print(f"rows written: {agg['dates_ok']}, of which without all-in cash (points only): {agg['cash_none']} | evidence: {agg['evidence_bytes']/1024:.0f} KB gz")
    log.info("RUN END done=%d counts=%s stats=%s agg=%s elapsed=%.1fs", done, counts, stats, agg, el)
    if args.dry_run:
        print(f"dry-run evidence kept in {tmp_ws}")
    return 0


def _disable_quick_edit() -> None:
    """A click in a Windows console freezes the process; switch QuickEdit off."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(h, ctypes.byref(mode)):
            k32.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)
    except Exception:
        pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Wyndham rate + Free Night harvester (schema v2)")
    p.add_argument("--limit", type=int, default=None, help="process at most N hotels")
    p.add_argument("--hotel", nargs="+", default=None, metavar="ID", help="only these hotel ids (ignores retry dates)")
    p.add_argument("--country", default=None, help="only this country (exact, case-insensitive)")
    p.add_argument("--workers", type=int, default=1, help="hotels processed in parallel (default 1, per golden standard)")
    p.add_argument("--dry-run", action="store_true", help="no DB writes; evidence goes to a temp directory")
    p.add_argument("--retry-failed", action="store_true", help="only hotels whose state is FAILED or PARTIAL, regardless of retry date")
    p.add_argument("--refresh-days", type=int, default=None, help="also re-harvest OK hotels last harvested N or more days ago")
    p.add_argument("--upgrade-legacy", action="store_true",
                   help="only hotels that still hold pre-contract rows (no raw evidence from this harvester); "
                        "their old points may be replaced by the fresh answer")
    p.add_argument("--grid", choices=("stratified", "weekly"), default="stratified",
                   help="stratified = the 24-date grid W24 (default); weekly = every Wed+Sat for 12 months (104 dates)")
    p.add_argument("--anchor", default=ANCHOR.isoformat(), help=f"grid anchor date (default {ANCHOR.isoformat()}, fixed)")
    p.add_argument("--max-rps", type=float, default=5.0, help="global request rate cap (default 5/s)")
    p.add_argument("--date-concurrency", type=int, default=3, help="dates fetched at once inside one hotel (default 3)")
    p.add_argument("--db", default=DEFAULT_DB, help=argparse.SUPPRESS)
    p.add_argument("--workspace", default=ROOT, help=argparse.SUPPRESS)
    p.add_argument("--log-file", default=DEFAULT_LOG, help=argparse.SUPPRESS)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    _disable_quick_edit()
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nInterrupted. Every finished hotel is already saved; run again to resume.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
