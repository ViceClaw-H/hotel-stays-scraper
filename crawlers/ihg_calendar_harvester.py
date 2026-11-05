"""IHG availability-calendar harvester (schema v2 contract).

One official source: POST https://apis.ihg.com/availability/v1/calendar - the very call ihg.com makes for its
Money and Points (Reward Nights) calendars. Per hotel:

    * 1 money call + 1 points call per 63-day window (the API silently truncates longer windows to 63 days),
      6 windows cover the ~350-day booking horizon  ->  at most 12 calls, plus 1 profile call (room names,
      reused from the previous evidence file while it is younger than --profile-days).
    * cash  = totalAmountAfterFeeTax of the lowest offer (all taxes and fees; never the pre-tax amount)
    * points = Reward Night offer of the same room type
    * every answer is stored verbatim in one gzip evidence file per hotel; engine.extractors.ihg.parse_evidence
      turns that file into rows (the harvester uses it on the bytes it just built, the verifier replays it).
    * one DB transaction per hotel through engine.rate_writer.write_rate_batch + engine.harvest_state.record.

Usage (from the project root or anywhere - paths derive from this file):
    python crawlers/ihg_calendar_harvester.py --limit 25 --workers 6
    python crawlers/ihg_calendar_harvester.py --hotel AADAL,DPSUB --dry-run
    python crawlers/ihg_calendar_harvester.py --country "United Kingdom" --retry-failed
    python crawlers/ihg_calendar_harvester.py --refresh-days 7        # re-harvest OK hotels older than 7 days
    python crawlers/ihg_calendar_harvester.py --refresh-headers       # re-capture the site's request headers

Console output is milestone-only (one line per 50 hotels, one line per failure); the trace is in logs/ihg_crawler.log.
"""
import argparse
import asyncio
import glob
import json
import logging
import os
import sqlite3
import sys
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine import harvest_state                                    # noqa: E402
from engine.extractors import ihg as ex                             # noqa: E402
from engine.rate_writer import write_rate_batch                     # noqa: E402

SOURCE = "IHG"
SOURCE_TYPE = "OFFICIAL_IHG_CRS"
DB_PATH = os.path.join(ROOT, "hotel_stays.db")
CATALOG_HEADERS_PATH = os.path.join(ROOT, "catalogs", "ihg", "ihg_headers.json")
HEADERS_PATH = os.path.join(ROOT, "scratch", "ihg_headers.json")
LOG_PATH = os.path.join(ROOT, "logs", "ihg_crawler.log")

DEFAULT_IHG_API_KEY = os.environ.get("IHG_API_KEY", "")
DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json; charset=UTF-8",
    "ihg-language": "en-US",
    "ihg-sessionid": os.environ.get("IHG_SESSION_ID", ""),
    "referer": "https://www.ihg.com/",
    "sec-ch-ua": '"Chromium";v="130", "Not?A_Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "x-ihg-api-key": DEFAULT_IHG_API_KEY,
}
EVIDENCE_REL_DIR = "evidence/ihg/crs"

WINDOW_DAYS = 63          # the API accepts longer windows but returns only start..start+62 (verified 2026-09-21)
MAX_WINDOWS = 6           # 6 x 63 = 378 days; the booking horizon is ~350 days
EMPTY_WINDOWS_STOP = 3    # a hotel with no calendar days in this many consecutive windows is 'no availability'
PROFILE_MAX_AGE_DAYS = 30
BATCH = 50                # console summary every N hotels

# Incident 2026-09-22: a sustained 403 streak (block_streak >= BLOCK_COOLDOWN_AT) went straight to trying an auth
# refresh, and gave up the whole run when that failed. But the refresh's own validation POST comes from the SAME
# blocked IP, so it fails for the same reason the main calls do - "refresh rejected" proved nothing about whether
# the headers were actually stale. Measured that day: the block itself cleared in ~9s (403s from 10:12:51.874 to
# 10:13:00.626, then 200s resumed), yet the run declared itself blocked and stopped. So: wait first, with the SAME
# headers, before ever trying to refresh them; only escalate to a refresh (and only then to giving up) if waiting
# doesn't work either.
BLOCK_COOLDOWN_AT = 8         # consecutive 403s before the first cooldown (same threshold as before)
COOLDOWN_SECONDS = 30.0       # base pause; round 2 waits 2x this, etc.
# Measured 2026-11-03 on another PC: 49 consecutive 403s and the block was still there after 30s + 60s (the edge blocks the IP for
# minutes, not seconds, when twelve scrapers share it). Longer rounds: 30s, 90s, 5 min, 15 min before escalating or giving up.
COOLDOWN_SCHEDULE = (30.0, 90.0, 300.0, 900.0)
MAX_COOLDOWNS = len(COOLDOWN_SCHEDULE)   # cooldown rounds tried before escalating to an auth refresh

SEND_HEADERS = ("accept", "accept-language", "content-type", "referer", "user-agent", "x-ihg-api-key",
                "ihg-language", "ihg-sessionid", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform")

log = logging.getLogger("ihg")


# ------------------------------------------------------------------------------------------------
# Request headers
# ------------------------------------------------------------------------------------------------
def load_headers(path: str = HEADERS_PATH) -> Dict[str, str]:
    """Load cached headers from path or catalogs/ihg, guaranteed fallback to bundled DEFAULT_HEADERS."""
    candidates = [path, CATALOG_HEADERS_PATH, HEADERS_PATH]
    for c_path in candidates:
        if not c_path or not os.path.exists(c_path):
            continue
        try:
            with open(c_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            hdr = {k.lower(): str(v) for k, v in data.items() if not k.startswith("_")}
            if hdr.get("x-ihg-api-key"):
                return hdr
        except (OSError, ValueError):
            pass
    # Guaranteed Zero-Install fallback: returns default headers without needing any browser
    return DEFAULT_HEADERS.copy()


async def capture_headers(path: str = HEADERS_PATH, mnemonic: str = "AADAL", headed: bool = True) -> Dict[str, str]:
    """Open one IHG hotel page in a real browser, copy the request headers of the site's own apis.ihg.com calls and keep
    the set whose api key the CALENDAR endpoint accepts (the site uses two different keys on one page; both were
    accepted on 2026-09-21, but that is checked, not assumed)."""
    from playwright.async_api import async_playwright
    url = f"https://www.ihg.com/holidayinnexpress/hotels/us/en/andalusia/{mnemonic.lower()}/hoteldetail"
    found: Dict[str, Dict[str, str]] = {}                 # api key -> request headers

    async def on_request(req):
        if "apis.ihg.com" in req.url:
            try:
                h = await req.all_headers()
            except Exception:                              # noqa: BLE001
                return
            if h.get("x-ihg-api-key"):
                found.setdefault(h["x-ihg-api-key"], h)

    async with async_playwright() as p:
        # Prefer system Chrome or Edge so zero-install PCs don't need Playwright Chromium binaries
        browser = None
        for channel in ("chrome", "msedge", None):
            try:
                kwargs = {"headless": not headed, "args": ["--disable-blink-features=AutomationControlled"]}
                if channel:
                    kwargs["channel"] = channel
                browser = await p.chromium.launch(**kwargs)
                break
            except Exception:
                continue
        if browser is None:
            raise RuntimeError("Could not launch Chromium, Chrome, or Edge browser for header capture.")
        try:
            ctx = await browser.new_context()
            ctx.on("request", lambda r: asyncio.create_task(on_request(r)))
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2)
            for _ in range(24):                            # up to ~12 s more, stop once the page has settled
                n = len(found)
                await asyncio.sleep(0.5)
                if found and n == len(found):
                    break
        finally:
            await browser.close()
    if not found:
        raise RuntimeError(f"no apis.ihg.com request with x-ihg-api-key was seen while loading {url}")

    def accepted(h: Dict[str, str]) -> bool:
        from curl_cffi.requests import Session
        hdr = {k: v for k, v in h.items() if k in SEND_HEADERS and k != "user-agent" and not k.startswith("sec-ch-")}
        hdr["ihg-transactionid"] = str(uuid.uuid4())
        day = (date.today() + timedelta(days=30)).isoformat()
        r = Session(impersonate="chrome124", timeout=30).post(ex.CALENDAR_URL, headers=hdr, json=ex.calendar_body(mnemonic, day, day, False))
        return r.status_code == 200

    chosen = None
    for h in found.values():
        if await asyncio.to_thread(accepted, h):
            chosen = h
            break
    if chosen is None:
        raise RuntimeError(f"none of the {len(found)} captured api key(s) was accepted by {ex.CALENDAR_URL}")
    keep = {k: v for k, v in chosen.items() if k in SEND_HEADERS}
    keep["_captured_at"] = datetime.now().isoformat(timespec="seconds")
    keep["_captured_from"] = url
    keep["_keys_seen"] = len(found)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(keep, fh, indent=2)
    return {k: v for k, v in keep.items() if not k.startswith("_")}


# ------------------------------------------------------------------------------------------------
# Shared adaptive throttle: every worker slows down together on 403 / 429 / timeouts.
# A 5xx is handled locally per-request instead (see _send below) - it reflects that one call, not our rate.
# ------------------------------------------------------------------------------------------------
class Throttle:
    """Shared pacing for every worker.

    Measured live (2026-09-21): the API edge (Akamai) answers HTTP 403 'Access Denied' once one client sends more
    than roughly 5-6 requests per second: 3/s and 5/s ran clean, 7/s was blocked for 100% of a 45-request run
    (curl_cffi with a Chrome fingerprint; plain httpx additionally gets ~2-7% random 403s). So the limit that matters
    is a REQUEST RATE, not the number of parallel hotels:
      * `rate` requests/second are started (evenly spaced), `max_inflight` caps parallel requests;
      * a throttle signal (403/429/5xx/timeout) halves the rate, pauses everybody with an exponentially growing delay
        (simultaneous failures count as ONE incident) and 20 clean answers in a row give back 10% of the rate.
    """

    def __init__(self, max_inflight: int, rate: float = 4.0):
        self.max = max(1, max_inflight)
        self.max_rate = float(rate)
        self.rate = float(rate)
        self.min_rate = float(rate)
        self.limit = self.max
        self.inflight = 0
        self.next_slot = 0.0
        self.pause_until = 0.0
        self.penalty = 0.0
        self.ok_streak = 0
        self.events = 0

    async def acquire(self):
        while True:
            now = time.monotonic()
            if now >= self.pause_until and self.inflight < self.limit:
                slot = max(now, self.next_slot)
                self.next_slot = slot + 1.0 / self.rate
                self.inflight += 1
                if slot > now:
                    await asyncio.sleep(slot - now)
                return
            await asyncio.sleep(0.02)

    def release(self):
        self.inflight = max(0, self.inflight - 1)

    def on_success(self):
        self.ok_streak += 1
        if self.ok_streak >= 20:
            self.ok_streak = 0
            self.penalty = max(0.0, self.penalty / 2 - 0.5)
            self.rate = min(self.max_rate, self.rate * 1.1)

    def on_throttle(self, retry_after: Optional[float] = None):
        self.events += 1
        self.ok_streak = 0
        now = time.monotonic()
        if now < self.pause_until:
            return                      # a pause is already running: simultaneous failures are one incident
        self.rate = max(0.5, self.rate / 2)
        self.min_rate = min(self.min_rate, self.rate)
        self.penalty = min(60.0, max(3.0, self.penalty * 2))
        self.pause_until = now + (retry_after if retry_after else self.penalty)
        self.next_slot = max(self.next_slot, self.pause_until)


# ------------------------------------------------------------------------------------------------
# HTTP client
# ------------------------------------------------------------------------------------------------
SendFn = Callable[[str, str, Dict[str, str], Optional[dict]], Awaitable[Tuple[int, str, Dict[str, str]]]]


class IhgClient:
    """Sends the requests, retries transient failures, refreshes the site headers once on 401/403."""

    def __init__(self, headers: Dict[str, str], throttle: Throttle, send: Optional[SendFn] = None,
                 refresh: Optional[Callable[[], Awaitable[Dict[str, str]]]] = None, timeout: float = 40.0):
        self.headers = headers
        self.throttle = throttle
        self._refresh = refresh
        self._auth_lock = asyncio.Lock()
        self._headers_gen = 0
        self._last_refresh = 0.0
        self.fatal: Optional[str] = None          # set when auth cannot be repaired: the run must stop
        self.block_streak = 0
        self._refreshed_on_403 = False
        self.cooldown_rounds = 0
        self._cooldown_lock = asyncio.Lock()
        self.block_cooldown_seconds: Callable[[int], float] = lambda n: COOLDOWN_SCHEDULE[min(n, len(COOLDOWN_SCHEDULE)) - 1]   # tests override to 0
        self.requests = 0
        self.bytes = 0
        self._http = None
        self._kind = "curl"
        self._send = send or self._http_send
        self._timeout = timeout
        self.server_error_backoff: Callable[[int], float] = lambda n: min(2.0 * n, 6.0)   # tests override to 0

    async def _http_send(self, method, url, headers, body):
        """curl_cffi with a Chrome TLS/HTTP2 fingerprint (falls back to httpx if it is not installed)."""
        if self._http is None:
            try:
                from curl_cffi.requests import AsyncSession
                self._http = AsyncSession(impersonate="chrome124", timeout=self._timeout)
                self._kind = "curl"
            except ImportError:
                import httpx
                self._http = httpx.AsyncClient(timeout=self._timeout)
                self._kind = "httpx"
        if self._kind == "curl":
            # the impersonated TLS/HTTP2 fingerprint brings its own consistent user-agent / client hints; the ones
            # captured from another Chromium version would contradict it
            headers = {k: v for k, v in headers.items() if k != "user-agent" and not k.startswith("sec-ch-")}
        if method == "POST":
            r = await self._http.post(url, headers=headers, json=body)
        else:
            r = await self._http.get(url, headers=headers)
        return r.status_code, r.content.decode("utf-8", errors="replace"), {k.lower(): v for k, v in r.headers.items()}

    async def _reset_connection(self):
        old, self._http = self._http, None
        if old is not None:
            try:
                r = old.close()
                if asyncio.iscoroutine(r):
                    await r
            except Exception:                            # noqa: BLE001
                pass

    async def close(self):
        if self._http is not None:
            r = self._http.close()
            if asyncio.iscoroutine(r):
                await r

    async def _repair_auth(self, gen_used: int) -> bool:
        async with self._auth_lock:
            if self._headers_gen != gen_used:
                return True                          # somebody already refreshed
            if self._refresh is None or time.monotonic() - self._last_refresh < 120:
                return False
            self._last_refresh = time.monotonic()
            try:
                self.headers = await self._refresh()
            except Exception as e:                   # noqa: BLE001
                log.error("header refresh failed: %r", e)
                return False
            self._headers_gen += 1
            log.info("request headers re-captured after 401/403")
            return True

    async def _cooldown(self) -> bool:
        """Pause once (same headers, no refresh) and give a short 403 storm a chance to clear on its own.

        Coordinated across concurrent workers via a lock + a fresh block_streak check inside it: if another
        worker's cooldown (or a genuine success) already reset the streak by the time we get the lock, this one
        is a no-op - we don't stack redundant sleeps. Returns True to mean "retry", False when MAX_COOLDOWNS is
        used up and the caller should escalate to an auth refresh."""
        async with self._cooldown_lock:
            if self.block_streak < BLOCK_COOLDOWN_AT:
                return True                              # cleared already (by success or another worker's cooldown)
            if self.cooldown_rounds >= MAX_COOLDOWNS:
                return False
            self.cooldown_rounds += 1
            wait = self.block_cooldown_seconds(self.cooldown_rounds)
            log.warning("%d consecutive HTTP 403: cooling down %.0fs with the SAME headers before trying a refresh (round %d/%d)",
                        self.block_streak, wait, self.cooldown_rounds, MAX_COOLDOWNS)
            await asyncio.sleep(wait)
            self.block_streak = 0
            return True

    async def call(self, kind: str, method: str, url: str, body: Optional[dict], window: Optional[Tuple[str, str]] = None,
                   tag: str = "") -> Dict[str, Any]:
        """One logical request -> an evidence record (verbatim body, status, error).

        Answer classes (observed live 2026-09-21):
          200            ok
          400            deterministic (bad range / validation): returned as is, never retried
          401 / 407      the api key is rejected ('UNAUTHORIZED')  -> re-capture the site headers once, retry
          403 HTML       Akamai 'Access Denied' edge block, triggered by request bursts (> ~6/s). A single one is
                         retried after a shared pause. 8 in a row: cool down (same headers, no refresh) for up to
                         MAX_COOLDOWNS rounds - most such streaks clear within seconds - then try a header refresh,
                         then give up (finished hotels are kept; --retry-failed picks this hotel back up).
          429            throttle -> same as 403
          5xx            IHG's own backend failing that one call (observed 2026-09-22: hotel ACOMM's loyalty/points
                         service errored on every points window). Says nothing about our rate: retried locally up
                         to 3 times with a short backoff; the global throttle and other hotels are unaffected.
        """
        rec: Dict[str, Any] = {"kind": kind, "window": list(window) if window else None, "method": method, "url": url,
                               "request_body": body, "http_status": None, "fetched_at": None, "body": None, "error": None}
        auth_tried = False
        server_errors = 0
        for attempt in range(6):
            if self.fatal:
                rec["error"] = f"run stopped: {self.fatal}"
                return rec
            await self.throttle.acquire()
            gen = self._headers_gen
            hdr = {k: v for k, v in self.headers.items() if not k.startswith("_")}
            hdr["ihg-transactionid"] = str(uuid.uuid4())
            t0 = time.monotonic()
            try:
                status, text, rh = await self._send(method, url, hdr, body)
            except Exception as e:                   # noqa: BLE001  timeouts, resets, DNS
                self.throttle.release()
                self.throttle.on_throttle()
                rec.update(http_status=None, body=None, error=f"{type(e).__name__}: {e}", fetched_at=datetime.now().isoformat(timespec="seconds"))
                log.warning("%s %s %s attempt %d: %s", tag, kind, window, attempt + 1, rec["error"])
                continue
            self.throttle.release()
            self.requests += 1
            self.bytes += len(text)
            rec.update(http_status=status, body=text, error=None, fetched_at=datetime.now().isoformat(timespec="seconds"))
            log.debug("%s %s %s -> %s %d bytes %.2fs", tag, kind, window, status, len(text), time.monotonic() - t0)
            if status == 200:
                self.throttle.on_success()
                self.block_streak = 0
                self.cooldown_rounds = 0
                return rec
            if status in (401, 407):
                if not auth_tried and await self._repair_auth(gen):
                    auth_tried = True
                    continue
                self.fatal = f"HTTP {status} from {url} even after re-capturing the site headers: {text[:200]}"
                return rec
            if 500 <= status < 600:
                # A server error on ONE request says nothing about our request rate (observed 2026-09-22: hotel ACOMM
                # answered HTTP 500 to every points call and, treated as a block, slowed the whole run 2x and paused
                # all workers). Retry locally with a short backoff; after 3 tries the window fails with the verbatim
                # status and the hotel ends PARTIAL - the other workers are never slowed.
                server_errors += 1
                log.warning("%s %s %s HTTP %d, local retry %d/3 (no global throttle)", tag, kind, window, status, server_errors)
                if server_errors >= 3:
                    return rec
                await asyncio.sleep(self.server_error_backoff(server_errors))
                continue
            if status == 403 or status == 429:
                if status == 403:
                    self.block_streak += 1
                    if self.block_streak % 3 == 0:        # a flagged connection stays flagged: open a fresh one
                        await self._reset_connection()
                    if self.block_streak >= BLOCK_COOLDOWN_AT:   # unbroken edge blocks: wait first, refresh second, give up last
                        if await self._cooldown():
                            continue
                        if not self._refreshed_on_403 and await self._repair_auth(gen):
                            self._refreshed_on_403 = True    # one fresh browser session (new headers) before giving up
                            self.block_streak = 0
                            self.cooldown_rounds = 0
                            continue
                        self.fatal = (f"{self.block_streak} consecutive HTTP 403 'Access Denied' from {url} (after {self.cooldown_rounds} "
                                      f"cooldown round(s) totalling {sum(self.block_cooldown_seconds(n) for n in range(1, self.cooldown_rounds + 1)):.0f}s "
                                      f"and re-capturing the site headers): the API edge has blocked this IP (request rate too high?). "
                                      f"Wait ~15 minutes, lower --rate, and re-run: finished hotels are kept. Last answer: {text[:160]!r}")
                        return rec
                ra = None
                try:
                    ra = float(rh.get("retry-after", ""))
                except ValueError:
                    pass
                self.throttle.on_throttle(ra)
                log.warning("%s %s %s HTTP %d (throttle: rate now %.1f req/s, pause %.0fs)", tag, kind, window, status, self.throttle.rate, self.throttle.penalty)
                continue
            return rec                                # other 4xx: deterministic, do not retry
        return rec


# ------------------------------------------------------------------------------------------------
# One hotel
# ------------------------------------------------------------------------------------------------
@dataclass
class HotelResult:
    hotel: dict
    evidence: Optional[bytes] = None
    analysis: Optional[ex.Analysis] = None
    los: int = 1
    windows_tried: int = 0
    calls: int = 0
    seconds: float = 0.0
    error: Optional[Dict[str, Any]] = None        # first hard failure (verbatim) when nothing usable came back
    money_windows_failed: List[Tuple[str, str]] = field(default_factory=list)
    points_windows_failed: List[Tuple[str, str]] = field(default_factory=list)
    run_stamp: str = ""                            # this invocation's evidence-filename suffix; see persist()


def make_windows(start: date) -> List[Tuple[str, str]]:
    out = []
    for k in range(MAX_WINDOWS):
        s = start + timedelta(days=WINDOW_DAYS * k)
        out.append((s.isoformat(), (s + timedelta(days=WINDOW_DAYS - 1)).isoformat()))
    return out


def _has_days(rec: Dict[str, Any], kind: str) -> Optional[bool]:
    """True/False = the answer was readable and had / had no calendar days; None = no usable answer."""
    p = ex.parse_calendar_response(kind, rec.get("http_status"), rec.get("body"))
    if not p.ok:
        return None
    return p.calendar_days > 0


def _invalid_property(rec: Dict[str, Any]) -> bool:
    """The answer says the property does not exist (50010) or is not active (50037): no point asking further."""
    p = ex.parse_calendar_response(ex.KIND_MONEY, rec.get("http_status"), rec.get("body"))
    return p.ok and any(c in (ex.WARN_INVALID_PROPERTY, ex.WARN_NOT_ACTIVE) for c, _ in p.warnings)


def _latest_evidence_path(evidence_dir_abs: str, mn: str) -> Optional[str]:
    """The most recently written evidence file for this hotel, whatever run wrote it.

    2026-09-22 fix: evidence filenames now carry a per-run timestamp (see persist()) so a later run - in
    particular --retry-failed - never overwrites an earlier run's file while old rows still cite it. This
    is the read-side counterpart: 'the previous evidence' means the newest {mn}_*.json.gz on disk, found by
    globbing, not a single fixed path."""
    candidates = sorted(glob.glob(os.path.join(evidence_dir_abs, f"{mn}_*.json.gz")))
    if not candidates:
        legacy = os.path.join(evidence_dir_abs, f"{mn}.json.gz")   # pre-fix filename, still valid evidence
        return legacy if os.path.exists(legacy) else None
    return candidates[-1]           # ISO-stamped names sort chronologically as strings


def _profile_from_previous(path: Optional[str], max_age_days: int) -> Optional[Dict[str, Any]]:
    """The profile request record of the previous evidence file, if there is one that is fresh enough."""
    if not path:
        return None
    try:
        with open(path, "rb") as fh:
            doc = ex.load_evidence(fh.read())
    except (OSError, ValueError):
        return None
    for r in doc.get("requests", []):
        if r.get("kind") == ex.KIND_PROFILE and r.get("http_status") == 200 and r.get("body"):
            try:
                age = datetime.now() - datetime.fromisoformat(r.get("fetched_at"))
            except (TypeError, ValueError):
                return None
            if age <= timedelta(days=max_age_days) and ex.parse_profile_room_names(r["body"]):
                return r
    return None


async def harvest_hotel(client: IhgClient, hotel: dict, evidence_dir_abs: str, today: date,
                        profile_days: int = PROFILE_MAX_AGE_DAYS, run_stamp: str = "") -> HotelResult:
    mn = hotel["mnemonic"]
    t0 = time.monotonic()
    res = HotelResult(hotel, run_stamp=run_stamp)
    records: List[Dict[str, Any]] = []
    windows = make_windows(today)

    async def win(idx: int, los: int, money: bool = True, points: bool = True) -> Tuple[Optional[dict], Optional[dict]]:
        s, e = windows[idx]
        coros = []
        if money:
            coros.append(client.call(ex.KIND_MONEY, "POST", ex.CALENDAR_URL, ex.calendar_body(mn, s, e, False, los), (s, e), mn))
        if points:
            coros.append(client.call(ex.KIND_POINTS, "POST", ex.CALENDAR_URL, ex.calendar_body(mn, s, e, True, los), (s, e), mn))
        out = await asyncio.gather(*coros)
        records.extend(out)
        it = iter(out)
        return (next(it) if money else None), (next(it) if points else None)

    los = 1
    # ---- window 0 (retry once one day later if the API says the start date is before the hotel's today)
    m0, p0 = await win(0, los)
    res.windows_tried = 1
    if any(r and r["http_status"] == 400 and ex.WARN_OUT_OF_RANGE in (r.get("body") or "") for r in (m0, p0)):
        for r in (m0, p0):
            r["superseded"] = True                       # kept in the evidence, not counted as a failure
        windows[:] = make_windows(today + timedelta(days=1))
        m0, p0 = await win(0, los)
    if _invalid_property(m0) or _invalid_property(p0):
        return _finish(res, records, client, mn, t0, evidence_dir_abs, profile_days, None)
    d0 = [_has_days(m0, ex.KIND_MONEY), _has_days(p0, ex.KIND_POINTS)]
    if d0 == [None, None]:                              # nothing readable: do not hammer this hotel
        res.error = _first_failure(records)
        return _finish(res, records, client, mn, t0, evidence_dir_abs, profile_days, None)

    empty_run = 0 if any(d0) else 1
    if not any(d0):
        # Some hotels (Six Senses) refuse a 1-night stay: ask for 2 nights once before calling it empty.
        m2, _ = await win(0, 2, money=True, points=False)
        if _has_days(m2, ex.KIND_MONEY):
            los = 2
            await win(0, 2, money=False, points=True)
            empty_run = 0
    res.los = los

    have_data = empty_run == 0
    idx = 1
    while not have_data and idx < MAX_WINDOWS and empty_run < EMPTY_WINDOWS_STOP:
        m, p = await win(idx, los)
        res.windows_tried += 1
        if any(_has_days(r, k) for r, k in ((m, ex.KIND_MONEY), (p, ex.KIND_POINTS))):
            have_data = True
        else:
            empty_run += 1
        idx += 1
    if have_data:
        rest = list(range(idx, MAX_WINDOWS))
        prof_task = asyncio.create_task(_get_profile(client, mn, evidence_dir_abs, profile_days))
        await asyncio.gather(*[win(i, los) for i in rest])
        res.windows_tried += len(rest)
        records.append(await prof_task)
    return _finish(res, records, client, mn, t0, evidence_dir_abs, profile_days, True)


async def _get_profile(client: IhgClient, mn: str, evidence_dir_abs: str, profile_days: int) -> Dict[str, Any]:
    prev_path = await asyncio.to_thread(_latest_evidence_path, evidence_dir_abs, mn)
    prev = await asyncio.to_thread(_profile_from_previous, prev_path, profile_days)
    if prev:
        return prev
    return await client.call(ex.KIND_PROFILE, "GET", ex.PROFILE_URL.format(mn=mn), None, None, mn)


def _first_failure(records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The first request that did not come back with HTTP 200, verbatim. Real answers win over 'run stopped' notes."""
    bad = [r for r in records if r["http_status"] != 200 and not r.get("superseded")]
    bad.sort(key=lambda r: r["http_status"] is None)              # stable: answered requests first
    if not bad:
        return None
    r = bad[0]
    return {"kind": r["kind"], "url": r["url"], "window": r.get("window"), "http_status": r["http_status"],
            "text": (r.get("body") or r.get("error") or "")[:500], "request_body": r.get("request_body")}


def _finish(res: HotelResult, records: List[Dict[str, Any]], client: IhgClient, mn: str, t0: float,
            evidence_dir_abs: str, profile_days: int, need_profile: Optional[bool]) -> HotelResult:
    hotel = res.hotel
    res.calls = sum(1 for r in records if r["http_status"] is not None or r["error"])
    if res.error is None:
        res.error = _first_failure(records)
    for r in records:
        if r.get("superseded"):
            continue
        if r["kind"] == ex.KIND_MONEY and r["http_status"] != 200 and r["window"]:
            res.money_windows_failed.append(tuple(r["window"]))
        if r["kind"] == ex.KIND_POINTS and r["http_status"] != 200 and r["window"]:
            res.points_windows_failed.append(tuple(r["window"]))
    res.evidence = ex.build_evidence(hotel["hotel_id"], mn, datetime.now().isoformat(timespec="seconds"), records)
    res.analysis = ex.analyze_evidence(res.evidence)
    res.seconds = time.monotonic() - t0
    return res


# ------------------------------------------------------------------------------------------------
# Verdict and persistence
# ------------------------------------------------------------------------------------------------
@dataclass
class Verdict:
    status: str
    reason: Optional[str] = None
    detail: Optional[str] = None
    url: Optional[str] = None
    retry_days: int = -1


def decide(res: HotelResult, written: int, rejected: List[Tuple[str, str]]) -> Verdict:
    a = res.analysis
    fail = res.error
    url = ex.CALENDAR_URL
    if a is not None and (a.invalid_property or a.not_active):
        code = ex.WARN_INVALID_PROPERTY if a.invalid_property else ex.WARN_NOT_ACTIVE
        w = next((m for k, c, m in a.warnings if c == code), "")
        return Verdict("INACTIVE", "INVALID_PROPERTY_CODE" if a.invalid_property else "PROPERTY_NOT_ACTIVE",
                       f"warning {code}: {w} (POST {url} hotelMnemonics=[{res.hotel['mnemonic']}]); check the hotel page for closure/deflagging",
                       res.hotel.get("official_url") or url)
    if not a.rows:
        if fail:
            code = f"HTTP_{fail['http_status']}" if fail.get("http_status") else "NO_RESPONSE"
            return Verdict("FAILED", code, f"{fail['kind']} window={fail.get('window')}: {fail['text']}", fail.get("url") or url)
        warn = "; ".join(f"{c} {m}" for _, c, m in a.warnings[:3])
        if a.no_allin_days:
            return Verdict("PARTIAL", "NO_ALLIN_PRICE", f"{a.no_allin_days} days have a lowest offer but no totalAmountAfterFeeTax", url, 14)
        return Verdict("NO_AVAILABILITY", "NO_CALENDAR_DAYS",
                       f"0 calendar days in {res.windows_tried} window(s) (money+points, LOS 1{' and 2' if res.los == 1 else ''}); {warn or 'no warning returned'}", url)
    problems = []          # (reason, detail, url, retry_days)
    if fail and fail["kind"] == ex.KIND_PROFILE:
        problems.append(("PROFILE_UNAVAILABLE", f"room names unresolved, rows use 'UNKNOWN (IHG room type CODE)'; profile HTTP {fail.get('http_status')}: {fail['text']}",
                         fail.get("url") or url, -1))
    elif fail:
        problems.append(("WINDOW_FAILED", f"{fail['kind']} window={fail.get('window')} HTTP {fail.get('http_status')}: {fail['text']}", fail.get("url") or url, -1))
    elif not a.profile_ok:
        problems.append(("PROFILE_UNAVAILABLE", "room names unresolved (profile call failed); rows use 'UNKNOWN (IHG room type CODE)'",
                         ex.PROFILE_URL.format(mn=res.hotel["mnemonic"]), -1))
    if rejected:
        c = Counter(r for _, r in rejected)
        problems.append(("ROWS_REJECTED", "; ".join(f"{k} x{v}" for k, v in c.items()) + f" e.g. {rejected[0][0]}", url, -1))
    if a.no_allin_days:
        problems.append(("NO_ALLIN_PRICE", f"{a.no_allin_days} day(s) have a lowest offer without totalAmountAfterFeeTax, so cash is None there", url, 14))
    if not problems:
        return Verdict("OK", None, None, None)
    reason, _, purl, retry = problems[0]
    return Verdict("PARTIAL", reason, " | ".join(f"{r}: {d}" for r, d, _, _ in problems), purl, retry)


def persist(conn: sqlite3.Connection, workspace: str, res: HotelResult, today: date) -> Tuple[Verdict, int, List[Tuple[str, str]]]:
    """One transaction: rows + evidence + harvest_status. Raises only on programming/DB errors."""
    hotel = res.hotel
    a = res.analysis
    rows = a.rows
    money_bad = res.money_windows_failed
    # A failed money window must not turn existing cash cells into points-only cells.
    if money_bad:
        rows = [r for r in rows if r.cash_rate is not None or not any(s <= r.stay_date <= e for s, e in money_bad)]
    written = 0
    rejected: List[Tuple[str, str]] = []
    if rows:
        # Filename carries this run's own timestamp - see the 2026-09-22 note on _latest_evidence_path().
        # A --retry-failed run must never overwrite the file an earlier run's still-good rows point at;
        # rows for dates a later response no longer reports simply keep citing their own (untouched) file.
        stamp = res.run_stamp or datetime.now().strftime("%Y%m%dT%H%M%S")
        wr = write_rate_batch(
            conn, hotel_id=hotel["hotel_id"], source_type=SOURCE_TYPE, source_url=ex.CALENDAR_URL, rows=rows,
            evidence_relpath=f"{EVIDENCE_REL_DIR}/{hotel['mnemonic']}_{stamp}.json.gz", evidence_bytes=res.evidence,
            evidence_grade="RAW", workspace_dir=workspace,
            # points may only vanish from a row when every points window of this hotel really came back
            allow_points_removal=not res.points_windows_failed and a.requests["points_ok"] > 0,
            today=today, commit=False)
        written, rejected = wr.written, list(wr.rejected)
    v = decide(res, written, rejected)
    harvest_state.record(conn, SOURCE, hotel["hotel_id"], v.status, reason=v.reason, detail=v.detail, url=v.url,
                         grid_id=f"LOS{res.los}", dates_ok=written, dates_total=res.windows_tried * WINDOW_DAYS,
                         horizon_last_ok=a.horizon_last_ok, retry_days=v.retry_days, commit=False)
    conn.commit()
    return v, written, rejected


# ------------------------------------------------------------------------------------------------
# Selection
# ------------------------------------------------------------------------------------------------
def load_hotels(conn: sqlite3.Connection, countries: Optional[List[str]] = None,
                only: Optional[List[str]] = None) -> List[dict]:
    rows = conn.execute("SELECT id, name, city, country, official_url FROM hotels WHERE brand = 'IHG' ORDER BY id").fetchall()
    want = {m.strip().upper().removeprefix("IHG_") for m in only} if only else None
    cset = {c.strip().lower() for c in countries} if countries else None
    out = []
    for hid, name, city, country, url in rows:
        if not hid.startswith("ihg_"):
            continue
        mn = hid[4:].upper()
        if want is not None and mn not in want:
            continue
        if cset is not None and (country or "").strip().lower() not in cset:
            continue
        out.append({"hotel_id": hid, "mnemonic": mn, "name": name, "city": city or "", "country": country or "", "official_url": url or ""})
    return out


def select_due(hotels: List[dict], states: Dict[str, dict], *, retry_failed: bool, refresh_days: Optional[int],
               forced: bool, limit: Optional[int]) -> List[dict]:
    if forced:
        todo = list(hotels)
    else:
        todo = []
        for h in hotels:
            st = states.get(h["hotel_id"])
            if harvest_state.is_due(st, refresh_days=refresh_days) or (
                    retry_failed and st is not None and st["status"] in ("FAILED", "PARTIAL")):
                todo.append(h)
        todo.sort(key=lambda h: 0 if h["hotel_id"] not in states else 1)      # never-seen first (stable)
    return todo[:limit] if limit is not None else todo


# ------------------------------------------------------------------------------------------------
# Run
# ------------------------------------------------------------------------------------------------
@dataclass
class RunStats:
    done: int = 0
    statuses: Counter = field(default_factory=Counter)
    rows: int = 0
    calls: int = 0
    seconds_sum: float = 0.0
    cash_days: int = 0
    points_days: int = 0
    failures: List[str] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)


def setup_logging(path: str = LOG_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    log.setLevel(logging.DEBUG)
    if not any(isinstance(h, logging.FileHandler) for h in log.handlers):
        from logging.handlers import RotatingFileHandler
        fh = RotatingFileHandler(path, maxBytes=20_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)


async def run(args, client_factory=None) -> RunStats:
    setup_logging()
    today = date.today()
    run_stamp = datetime.now().strftime("%Y%m%dT%H%M%S")   # one per invocation; see persist()
    dry = args.dry_run
    if dry:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        workspace = tempfile.mkdtemp(prefix="ihg_dry_")
    else:
        conn = sqlite3.connect(args.db, timeout=60)
        from engine.schema import require_v2
        require_v2(conn, "IHG harvester")   # before any request
        conn.execute("PRAGMA busy_timeout = 60000")
        workspace = os.path.abspath(args.workspace)
    hotels = load_hotels(conn, args.country.split(",") if args.country else None,
                         args.hotel.split(",") if args.hotel else None)
    states = {} if dry and not _has_table(conn, "harvest_status") else harvest_state.load_all(conn, SOURCE)
    todo = select_due(hotels, states, retry_failed=args.retry_failed, refresh_days=args.refresh_days,
                      forced=bool(args.hotel), limit=args.limit)

    headers = load_headers(args.headers)
    if args.refresh_headers or headers is None:
        headers = await capture_headers(args.headers)
        print(f"[IHG] request headers captured -> {os.path.relpath(args.headers, ROOT)}")
    if not todo:
        print(f"[IHG] nothing to do ({len(hotels)} hotels match, none due)")
        return RunStats()

    throttle = Throttle(max_inflight=args.workers * args.inflight_per_worker, rate=args.rate)
    client = client_factory(headers, throttle) if client_factory else IhgClient(
        headers, throttle, refresh=lambda: capture_headers(args.headers))
    stats = RunStats()
    print(f"[IHG] {len(todo)} hotel(s) of {len(hotels)} | workers={args.workers} rate<={args.rate}/s | "
          f"{'DRY RUN (no DB writes, evidence in ' + workspace + ')' if dry else 'db=' + os.path.relpath(args.db, ROOT)} | log={os.path.relpath(LOG_PATH, ROOT)}")
    queue: asyncio.Queue = asyncio.Queue()
    for h in todo:
        queue.put_nowait(h)
    evidence_dir_abs = os.path.join(workspace, *EVIDENCE_REL_DIR.split("/"))
    os.makedirs(evidence_dir_abs, exist_ok=True)

    async def worker():
        while not client.fatal:
            try:
                h = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                res = await harvest_hotel(client, h, evidence_dir_abs, today, args.profile_days, run_stamp)
                if client.fatal and not res.analysis.rows:
                    return                                    # do not record hotels that only failed because the run is dead
                if dry:
                    a = res.analysis
                    v = decide(res, len(a.rows), [])
                    written = len(a.rows)
                    with open(os.path.join(evidence_dir_abs, f"{h['mnemonic']}_{run_stamp}.json.gz"), "wb") as fh:
                        fh.write(res.evidence)
                else:
                    v, written, rej = persist(conn, workspace, res, today)
                    for d, why in rej:
                        log.warning("%s rejected %s: %s", h["mnemonic"], d, why)
            except Exception as e:                            # noqa: BLE001 - one hotel must not stop the run
                log.exception("%s crashed", h["mnemonic"])
                v, written, res = Verdict("FAILED", "HARVEST_CRASH", f"{type(e).__name__}: {e}", ex.CALENDAR_URL), 0, None
                if not dry:
                    try:
                        harvest_state.record(conn, SOURCE, h["hotel_id"], "FAILED", reason=v.reason, detail=v.detail, url=v.url)
                    except Exception:                         # noqa: BLE001
                        log.exception("could not record failure for %s", h["mnemonic"])
            stats.done += 1
            stats.statuses[v.status] += 1
            stats.rows += written
            if res is not None:
                stats.calls += res.calls
                stats.seconds_sum += res.seconds
                stats.cash_days += res.analysis.cash_days
                stats.points_days += res.analysis.points_days
                a = res.analysis
                log.info("%s %s | %s %s | rows=%d cash=%d pts=%d pairs=%d nonstd=%d no_allin=%d reward_other_room=%d los=%d calls=%d %.1fs "
                         "evidence=%dB rooms_unresolved=%s cur=%s", h["mnemonic"], h["country"], v.status, v.reason or "", written,
                         a.cash_days, a.points_days, a.paired_days, a.nonstandard_cash_days, a.no_allin_days,
                         a.cash_days_reward_other_room, res.los, res.calls, res.seconds, len(res.evidence or b""), a.unresolved_room_codes, a.currency)
            if v.status != "OK":
                line = f"[IHG] {v.status:<15} {h['mnemonic']} {h['country'][:18]:<18} {v.reason or ''} | {' '.join((v.detail or '').split())[:170]} | {v.url or ''}"
                if v.status in ("FAILED", "PARTIAL", "INACTIVE") or args.show_all:
                    print(line)
                stats.failures.append(line)
            if stats.done % BATCH == 0:
                el = time.monotonic() - stats.started
                print(f"[IHG] {stats.done}/{len(todo)} | {dict(stats.statuses)} | rows={stats.rows} | {el / stats.done:.2f}s/hotel wall, "
                      f"{stats.calls / max(1, stats.done):.1f} calls/hotel | throttle events={throttle.events} | eta {(len(todo) - stats.done) * el / stats.done / 60:.0f} min")

    try:
        await asyncio.gather(*[worker() for _ in range(args.workers)])
    finally:
        await client.close()
        if client.fatal:
            print(f"[IHG] STOPPED: {client.fatal}")
            print(f"[IHG] {queue.qsize()} hotel(s) were not attempted and keep their old state; fix authentication (--refresh-headers) and re-run.")
        conn.close()
    el = time.monotonic() - stats.started
    stats.stopped_early = bool(client.fatal)
    print(f"[IHG] finished {stats.done}/{len(todo)} in {el:.0f}s | {dict(stats.statuses)} | rows={stats.rows} | "
          f"{el / max(1, stats.done):.2f}s/hotel wall | {stats.calls / max(1, stats.done):.1f} calls/hotel | "
          f"{client.bytes / 1e6:.0f} MB received | throttle events={throttle.events} (lowest rate {throttle.min_rate:.1f}/{throttle.max_rate:.1f} req/s)")
    return stats


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="IHG availability-calendar harvester (cash all-in + Reward Night points).")
    p.add_argument("--limit", type=int, default=None, help="attempt at most N hotels")
    p.add_argument("--hotel", help="mnemonic(s), comma separated (e.g. AADAL,DPSUB); forces a re-harvest of exactly these")
    p.add_argument("--country", help="hotels.country value(s), comma separated")
    p.add_argument("--workers", type=int, default=3, help="hotels harvested in parallel (default 3; 6 got this IP blocked after ~100 hotels)")
    p.add_argument("--rate", type=float, default=1.5, help="max requests per second, shared by all workers (4/s still ended in 49 consecutive 403s)")
    p.add_argument("--inflight-per-worker", type=int, default=3, help="cap on simultaneous requests = workers x this")
    p.add_argument("--dry-run", action="store_true", help="no DB writes (DB opened read-only), evidence goes to a temp dir")
    p.add_argument("--retry-failed", action="store_true", help="also retry FAILED/PARTIAL hotels whose retry_after has not passed")
    p.add_argument("--refresh-days", type=int, default=None, help="re-harvest OK hotels last attempted more than N days ago")
    p.add_argument("--refresh-headers", action="store_true", help="re-capture the site's request headers with Playwright first")
    p.add_argument("--profile-days", type=int, default=PROFILE_MAX_AGE_DAYS, help="reuse a hotel's profile (room names) younger than N days")
    p.add_argument("--show-all", action="store_true", help="also print NO_AVAILABILITY lines on the console")
    p.add_argument("--workspace", default=ROOT, help="directory that evidence/ paths are relative to (default: the project root)")
    p.add_argument("--db", default=DB_PATH, help="SQLite file (default: the project's hotel_stays.db)")
    p.add_argument("--headers", default=HEADERS_PATH, help="cached request headers (default scratch/ihg_headers.json)")
    return p


def main(argv=None):
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    args = build_parser().parse_args(argv)
    stats = asyncio.run(run(args))
    if getattr(stats, "stopped_early", False):
        print("[IHG] keluar dengan kode 2: berhenti sebelum seluruh katalog selesai (bukan 'selesai penuh').")
        sys.exit(2)


if __name__ == "__main__":
    main()
