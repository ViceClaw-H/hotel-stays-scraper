# -*- coding: utf-8 -*-
"""
Hyatt AWARD calendar harvester (schema v2)
==========================================
World of Hyatt award points per night for every redeemable property, from Hyatt's own points calendar:

    GET https://www.hyatt.com/explore-hotels/service/avail/days?spiritCode={code}&startDate={D}&endDate={D}
    -> {"days": {"2026-11-09": {"STANDARD_ROOM": {"pointsValue": [17000], "pointsLevel": "OFF_PEAK", "rate": null}, ...}}}

Measured 2026-09-21:
  * ONE request can span the whole booking horizon (start=today, end=today+366 days is accepted; 13 monthly
    requests are not needed). For 3 hotels the room/points/level chosen for storage were identical in the
    one-year reply and in the 13 monthly replies (342/342, 343/343, 320/320 dates); only non-standard keys
    (PREMIUM_SUITE) differ on a few dates, which this harvester does not store.
  * A window that ENDS later than about today+367 is answered {"days": {}, "responseInfo": "soldOutHotel"}
    (also the reply for a truly sold-out hotel and for an unknown spirit code), so the window is capped at 366
    days and every "soldOutHotel" is confirmed with a second short request before it is trusted as
    NO_AVAILABILITY. (The old 13 monthly windows ended 2027-10-01 for a run on 2026-09-21: that last window
    was beyond the horizon and silently returned nothing, so the last ~3 weeks were never harvested.)
  * Server time is roughly proportional to the days requested for ordinary hotels (~4 s for a year) but ~1 s per
    day for slow hotels (e.g. drbmi, noecu, asora): a window longer than ~45 days is answered HTTP 504 after
    ~50 s. Such a window is not retried; the hotel is done in 31-day windows and `harvest_status.grid_id`
    is set to 'span:31' so the next run starts narrow.
  * The endpoint carries NO cash (`rate` is null in every cell, with or without the calendar page's own
    parameters). Cash comes from crawlers/hyatt_cash_benchmark_harvester.py.
  * Kasada: a Chrome that Playwright attached to within ~1 s of launch got HTTP 429 on its first request; the
    same code with the attach delayed to 8 s after launch got 200 (see HyattCDPSession.start).

Contract (see engine/schema.py, engine/rate_writer.py):
  * points-only rows: cash_rate NULL, raw_currency NULL, points > 0; room_name = the API's room key
    (STANDARD_ROOM, or the fallback key chosen by engine.extractors.hyatt.choose_award_room).
  * evidence = the verbatim response text, parsed by engine.extractors.hyatt.parse_evidence.
  * every DB write goes through engine.rate_writer.write_rate_batch, one transaction per hotel.
  * per-hotel state in harvest_status (source HYATT_AWARD): OK / PARTIAL / FAILED / NO_AVAILABILITY.
    A hotel is only OK when every planned window returned a definitive answer.

Run:
  python crawlers/hyatt_avail_days_harvester.py                      # every hotel that is due
  python crawlers/hyatt_avail_days_harvester.py --workers 3          # 3 Chromes on ports 9322..9324
  python crawlers/hyatt_avail_days_harvester.py --spirit balgh,dpsaz # named hotels (ignores state)
  python crawlers/hyatt_avail_days_harvester.py --retry-failed       # FAILED/PARTIAL hotels now
  python crawlers/hyatt_avail_days_harvester.py --refresh-days 3     # also re-do OK hotels older than 3 days
  python crawlers/hyatt_avail_days_harvester.py --limit 10 --dry-run # fetch + parse, write nothing
"""
import argparse
import atexit
import json
import logging
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dateutil.relativedelta import relativedelta  # noqa: E402

from engine import harvest_state  # noqa: E402
from engine.extractors import hyatt as hx  # noqa: E402
from engine.rate_writer import write_rate_batch  # noqa: E402
from engine.schema import HARVEST_STATUS_DDL  # noqa: E402

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass

SOURCE = "HYATT_AWARD"                       # harvest_status.source
SOURCE_TYPE = "OFFICIAL_HYATT_AVAIL_DAYS"    # rate_records.source_type
CATALOG_PATH = os.path.join(ROOT, "data", "hyatt_official_directory.json")
BASE = "https://www.hyatt.com"
MAX_WINDOW_DAYS = 360        # Safe window within Hyatt's API single-call limit
CHUNK_DAYS = 31              # window size used when a long window times out (slow hotels: ~1 s of server time per day)
CONFIRM_DAYS = 30            # length of the confirmation window for "soldOutHotel"
KASADA_WARMUP_SECONDS = 8.0   # seconds after Chrome launch before Playwright may attach (see HyattCDPSession.start)
OFFSCREEN = True   # Chrome window is opened off-screen (never pops up); --visible sets this False

import shutil
CHROME_CANDIDATES = [
    os.environ.get("CHROME_BIN") or "",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
    shutil.which("chrome") or "",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    shutil.which("msedge") or "",
]
CHROME_BIN = next((p for p in CHROME_CANDIDATES if p and os.path.exists(p)), CHROME_CANDIDATES[1])

log = logging.getLogger("hyatt")


# ── logging / console ───────────────────────────────────────────────────────────────────────
def setup_logging(workspace: str, tag: str = "hyatt") -> str:
    """Full trace goes to logs/hyatt_crawler.log; the console only gets milestone lines (see Console)."""
    logs = os.path.join(workspace, "logs")
    os.makedirs(logs, exist_ok=True)
    path = os.path.join(logs, "hyatt_crawler.log")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(process)d] %(levelname)s %(message)s"))
    log.addHandler(fh)
    log.propagate = False
    return path


def say(msg: str) -> None:
    print(msg, flush=True)
    log.info(msg)


class Console:
    """Milestone-only console: one summary line per `every` hotels plus one line per failure."""

    def __init__(self, total: int, label: str, every: int = 50):
        self.total, self.label, self.every = total, label, every
        self.done = 0
        self.counts: Counter = Counter()
        self.rows = 0
        self.t0 = time.time()

    def hotel(self, sc: str, res: "HotelResult", session) -> None:
        self.done += 1
        self.counts[res.status] += 1
        self.rows += res.rows
        status_tag = f"[{res.status}]"
        detail_msg = f"{res.rows} rows" if res.status == "OK" else f"{res.reason}"
        say(f"  [{self.label}] #{self.done}/{self.total} {status_tag} {sc.upper()} -> {detail_msg}")
        if res.status in ("FAILED", "PARTIAL"):
            say(f"  [{res.status}] {sc}  {res.reason}  {(res.detail or '')[:220]}  {res.url or ''}")
        if self.done % self.every == 0 or self.done == self.total:
            el = time.time() - self.t0
            eta = el / self.done * (self.total - self.done)
            c = self.counts
            say(f"[{self.label}] {self.done}/{self.total} hotels  ok {c['OK']}  no-avail {c['NO_AVAILABILITY']}  "
                f"partial {c['PARTIAL']}  failed {c['FAILED']}  rows {self.rows:,}  requests {session.requests}  "
                f"recycles {session.recycles}  {el/60:.1f} min  eta {eta/60:.1f} min")


# ── Chrome over CDP (Kasada: a real Chrome, not a bare HTTP client) ─────────────────────────────
_LIVE_SESSIONS: List["HyattCDPSession"] = []


def _close_all_sessions() -> None:
    for s in list(_LIVE_SESSIONS):
        try:
            s.close()
        except Exception:
            pass


atexit.register(_close_all_sessions)


class HyattCDPSession:
    """One real Chrome (own temp profile, own debugging port) that we run fetch() inside.

    Every Chrome we start is killed (whole process tree) and its temp profile removed on close()/exit."""

    def __init__(self, port: int = 9322, tag: str = "avail", max_reqs: Tuple[int, int] = (110, 150),
                 chrome_bin: str = None):
        self.port, self.tag = port, tag
        self.chrome_bin = chrome_bin or CHROME_BIN
        self.max_reqs_range = max_reqs
        self.temp_dir = self.proc = self.playwright = self.browser = self.page = None
        self.req_count = 0
        self.max_reqs = random.randint(*max_reqs)
        self.requests = 0        # lifetime counters, for the efficiency report
        self.recycles = 0
        self.broken = False

    # -- lifecycle -------------------------------------------------------------------------
    def _cdp_up(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1.5):
                return True
        except Exception:
            return False

    def start(self) -> None:
        from playwright.sync_api import sync_playwright
        if self._cdp_up():
            raise RuntimeError(f"debugging port {self.port} is already in use (a Chrome from another run?); "
                               f"pick another --port")
        self.temp_dir = tempfile.mkdtemp(prefix=f"hyatt_{self.tag}_p{self.port}_")
        log.debug("launching Chrome on port %s, profile %s", self.port, self.temp_dir)
        launched = time.time()
        # A real (headed) Chrome is required - Kasada answers plain HTTP and headless Chrome with blocks. So the
        # window is opened OFF-SCREEN instead of hidden: it never appears on the user's desktop (--visible undoes it).
        offscreen = ["--window-position=-32000,-32000", "--window-size=1366,768"] if OFFSCREEN else ["--window-size=1440,900"]
        cflags = 0x08000000 if OFFSCREEN else 0
        si = None
        if sys.platform == "win32" and OFFSCREEN:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE: natively hides window & taskbar icon
        self.proc = subprocess.Popen([
            self.chrome_bin, f"--remote-debugging-port={self.port}", f"--user-data-dir={self.temp_dir}",
            "--no-first-run", "--no-default-browser-check", "--disable-blink-features=AutomationControlled",
            *offscreen, f"{BASE}",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=si, creationflags=cflags)
        if self not in _LIVE_SESSIONS:
            _LIVE_SESSIONS.append(self)
        for _ in range(60):                      # wait for the debugging endpoint instead of a fixed sleep
            if self._cdp_up():
                break
            time.sleep(0.5)
        else:
            self.close()
            raise RuntimeError(f"Chrome did not open debugging port {self.port} within 30 s")
        # Do NOT attach Playwright yet. Observed 2026-09-21: sessions attached ~1 s after launch were answered
        # HTTP 429 on their first request, also when the fetch was delayed by 10 s AFTER attaching; the same code
        # with the attach delayed until 8 s after launch got 200 on every later session (Kasada probably
        # inspects the page while its script runs at load; this is an inference, not proven). The old code
        # slept a fixed 6 s before connecting, which is why it never hit this.
        wait = KASADA_WARMUP_SECONDS - (time.time() - launched)
        if wait > 0:
            time.sleep(wait)
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        ctx = self.browser.contexts[0]
        self.page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for attempt in range(5):
            try:
                if "hyatt.com" not in self.page.url:
                    self.page.goto(BASE, wait_until="domcontentloaded", timeout=45000)
                break
            except Exception as ex:
                log.warning("navigation retry %s/5: %s", attempt + 1, ex)
                time.sleep(6)
        self.page.wait_for_timeout(1500)
        self.req_count = 0
        self.max_reqs = random.randint(*self.max_reqs_range)
        self.broken = False
        log.debug("session ready on port %s, url %s", self.port, self.page.url)

    def close(self) -> None:
        for obj, meth in ((self.browser, "close"), (self.playwright, "stop")):
            try:
                if obj:
                    getattr(obj, meth)()
            except Exception:
                pass
        self.browser = self.playwright = self.page = None
        if self.proc:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        if self.temp_dir:
            for _ in range(5):                   # Chrome may still hold the profile for a moment
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                if not os.path.exists(self.temp_dir):
                    break
                time.sleep(0.6)
            self.temp_dir = None
        if self in _LIVE_SESSIONS:
            _LIVE_SESSIONS.remove(self)

    def recycle(self, why: str = "") -> None:
        log.info("recycling Chrome on port %s (%s)", self.port, why)
        self.recycles += 1
        self.close()
        time.sleep(2)
        self.start()

    # -- requests --------------------------------------------------------------------------
    JS_FETCH = """
        async ([url, timeoutMs]) => {
            const ctl = new AbortController();
            const timer = setTimeout(() => ctl.abort(), timeoutMs);
            const t0 = performance.now();
            try {
                const r = await fetch(url, {credentials: 'include', signal: ctl.signal,
                    headers: {'Accept': 'application/json, text/plain, */*', 'X-Requested-With': 'XMLHttpRequest'}});
                const text = await r.text();
                return {status: r.status, text: text, ms: Math.round(performance.now() - t0)};
            } catch (e) {
                return {error: String(e), ms: Math.round(performance.now() - t0)};
            } finally { clearTimeout(timer); }
        }"""

    def fetch(self, url: str, timeout_ms: int = 60000) -> Dict:
        """{'status', 'text', 'ms'} or {'error', 'ms'}. Never raises for network/page problems."""
        if self.page is None or self.req_count >= self.max_reqs:
            self.recycle("request budget" if self.page is not None else "no session")
        self.req_count += 1
        self.requests += 1
        try:
            return self.page.evaluate(self.JS_FETCH, [url, timeout_ms])
        except Exception as ex:                  # tab crashed / context destroyed
            self.broken = True
            return {"error": f"BROWSER: {ex}"[:300], "ms": 0}


# ── catalog ─────────────────────────────────────────────────────────────────────────────────
_CAT_ORDER = {"8": 0, "7": 1, "A5": 2, "A4": 3, "6": 4, "A3": 5, "5": 6, "A2": 7, "4": 8, "A1": 9,
              "3": 10, "A0": 11, "2": 12, "1": 13}


def load_redeemable_hotels(spirit_filter=None, cat_filter=None, catalog_path: str = CATALOG_PATH) -> List[dict]:
    """Award-redeemable Hyatt properties: has an awardCategory, is not Mr & Mrs Smith."""
    with open(catalog_path, encoding="utf-8") as f:
        cat = json.load(f)
    hotels = []
    for spirit_code, h in cat.items():
        brand = h.get("brand", {})
        brand_label = brand.get("label", "") if isinstance(brand, dict) else str(brand)
        if "Mr" in brand_label and "Smith" in brand_label:
            continue
        ac = h.get("awardCategory")
        if not ac or not isinstance(ac, dict) or not ac.get("key"):
            continue
        loc = h.get("location", {})
        country = ""
        if isinstance(loc, dict):
            c = loc.get("country", {})
            country = c.get("name", "") if isinstance(c, dict) else str(c)
        hotels.append({"spirit_code": spirit_code, "hotel_id": f"hyatt_{spirit_code}", "name": h.get("name", spirit_code),
                       "country": country, "brand": brand_label, "award_cat": ac["key"]})
    if spirit_filter:
        want = {s.lower().strip() for s in spirit_filter}
        hotels = [h for h in hotels if h["spirit_code"].lower() in want]
    if cat_filter:
        hotels = [h for h in hotels if h["award_cat"] in cat_filter]
    hotels.sort(key=lambda h: (0 if "Indonesia" in h["country"] else 1, _CAT_ORDER.get(h["award_cat"], 99),
                               h["country"], h["name"]))
    return hotels


def select_hotels(hotels, states, *, spirit=None, force=False, retry_failed=False, refresh_days=None, limit=None):
    """Which hotels to attempt. Named hotels and --force ignore state; --retry-failed = FAILED/PARTIAL now;
    default = never seen, or not OK and past its retry_after (harvest_state.is_due), or OK but stale."""
    if spirit or force:
        todo = list(hotels)
    elif retry_failed:
        todo = [h for h in hotels if (states.get(h["hotel_id"]) or {}).get("status") in ("FAILED", "PARTIAL")]
    else:
        todo = harvest_state.due_hotels(hotels, states, key="hotel_id", refresh_days=refresh_days)
    return todo[:limit] if limit else todo


# ── windows ─────────────────────────────────────────────────────────────────────────────────
def plan_windows(today: date, months: int) -> List[Tuple[date, date]]:
    """One window [today, today+months] (end inclusive), capped at MAX_WINDOW_DAYS."""
    end = min(today + relativedelta(months=months), today + timedelta(days=MAX_WINDOW_DAYS))
    return [(today, end)]


def split_window(a: date, b: date, chunk_days: int = None) -> List[Tuple[date, date]]:
    chunk_days = chunk_days or CHUNK_DAYS
    out, cur = [], a
    while cur <= b:
        end = min(cur + timedelta(days=chunk_days - 1), b)
        out.append((cur, end))
        cur = end + timedelta(days=1)
    return out


def award_url(spirit: str, a, b) -> str:
    return f"{BASE}/explore-hotels/service/avail/days?spiritCode={spirit}&startDate={a}&endDate={b}"


# ── one hotel ───────────────────────────────────────────────────────────────────────────────
@dataclass
class Cfg:
    workspace: str
    months: int = 12
    today: date = field(default_factory=date.today)
    dry_run: bool = False
    pace: Tuple[float, float] = (0.3, 0.6)
    max_attempts: int = 3
    cooldown: float = 45.0          # seconds x attempt after an HTTP 429
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = datetime.now


@dataclass
class Outcome:
    window: Tuple[date, date]
    url: str
    text: str
    verdict: hx.Verdict
    status: Optional[int] = None
    attempts: int = 1


@dataclass
class HotelResult:
    status: str = "FAILED"
    reason: Optional[str] = None
    detail: Optional[str] = None
    url: Optional[str] = None
    rows: int = 0
    dates_ok: int = 0
    dates_total: int = 0
    horizon_last_ok: Optional[str] = None
    rejected: Counter = field(default_factory=Counter)
    requests: int = 0
    grid_id: Optional[str] = None      # harvest_status.grid_id: 'span:N' = window length that works for this hotel
    evidence: List[str] = field(default_factory=list)


def fetch_definitive(session, url: str, classify, cfg: Cfg, res: HotelResult, retry_transient: bool = True) -> Outcome:
    """Fetch with retry/backoff. Kasada-type blocks recycle the Chrome; transient errors just back off.
    Returns the last answer (OK / SOLD_OUT are definitive; anything else is a failure with its cause)."""
    attempt = 0
    while True:
        attempt += 1
        r = session.fetch(url)
        res.requests += 1
        v = classify(r.get("status"), r.get("text"), r.get("error"))
        log.debug("GET %s -> status=%s len=%s %sms verdict=%s/%s (attempt %s)", url, r.get("status"),
                  len(r.get("text") or ""), r.get("ms"), v.kind, v.reason, attempt)
        if (v.kind in ("OK", "SOLD_OUT") or v.kind == "BAD" or attempt >= cfg.max_attempts
                or (v.kind == "RETRY" and not retry_transient)):
            return Outcome((None, None), url, r.get("text") or "", v, r.get("status"), attempt)
        if v.reason == "HTTP_429":
            # Kasada rate limit: a fresh Chrome does not lift it, time does. Wait, then start clean.
            log.warning("HTTP 429 (Kasada rate limit) on %s: cooling down %ss", url, cfg.cooldown * attempt)
            cfg.sleep(cfg.cooldown * attempt)
            session.recycle("HTTP_429 cooldown")
        else:
            if v.kind == "BLOCKED" or getattr(session, "broken", False):
                session.recycle(f"{v.reason} on {url}")
            cfg.sleep(2.0 * attempt + random.uniform(0, 1.5))       # backoff 2-3.5 s, 4-5.5 s


def _win(session, spirit, w, cfg, res, retry_transient: bool = True) -> Outcome:
    o = fetch_definitive(session, award_url(spirit, *w), hx.classify_award_response, cfg, res, retry_transient)
    o.window = w
    return o


def harvest_award_hotel(session, conn, hotel: dict, cfg: Cfg) -> HotelResult:
    """Fetch, parse, write and record one hotel. `conn` may be None with cfg.dry_run."""
    sc, hid = hotel["spirit_code"], hotel["hotel_id"]
    res = HotelResult()
    outs: List[Outcome] = []
    hint = hotel.get("span_hint")                       # a span that timed out on a previous run: start narrow
    for w in plan_windows(cfg.today, cfg.months):
        span = (w[1] - w[0]).days + 1
        if hint and hint < span:
            outs += [_win(session, sc, c, cfg, res) for c in split_window(*w, hint)]
            res.grid_id = f"span:{hint}"
            continue
        # A long window on a slow hotel is answered 504 after ~50 s: do not repeat it, go to short windows.
        o = _win(session, sc, w, cfg, res, retry_transient=span <= CHUNK_DAYS)
        cfg.sleep(random.uniform(*cfg.pace))
        if o.verdict.kind in ("RETRY", "BAD") and span > CHUNK_DAYS:      # never chunk a block: it only multiplies the hits
            log.warning("%s: window %s..%s failed (%s); retrying as %d-day chunks", sc, w[0], w[1], o.verdict.reason, CHUNK_DAYS)
            outs += [_win(session, sc, c, cfg, res) for c in split_window(*w)]
            res.grid_id = f"span:{CHUNK_DAYS}"
        elif o.verdict.kind == "SOLD_OUT" and span > CONFIRM_DAYS + 1:
            # "soldOutHotel" is also Hyatt's answer for an unknown code or a window past its horizon:
            # confirm with a short window before believing that the hotel has no award nights.
            conf = _win(session, sc, (w[0], w[0] + timedelta(days=CONFIRM_DAYS)), cfg, res)
            if conf.verdict.kind == "SOLD_OUT":
                outs.append(o)
            elif conf.verdict.kind == "OK":
                log.warning("%s: wide window said soldOutHotel but the next %d days have availability; using chunks", sc, CONFIRM_DAYS)
                outs += [_win(session, sc, c, cfg, res) for c in split_window(*w)]
                res.grid_id = f"span:{CHUNK_DAYS}"
            else:
                o.verdict = hx.Verdict("RETRY", "SOLD_OUT_UNCONFIRMED", f"{conf.verdict.reason}: {conf.verdict.detail}")
                o.url = conf.url
                outs.append(o)
        else:
            outs.append(o)

    res.dates_total = sum((o.window[1] - o.window[0]).days + 1 for o in outs)
    res.url = outs[0].url
    good = [o for o in outs if o.verdict.kind in ("OK", "SOLD_OUT")]
    bad = [o for o in outs if o.verdict.kind not in ("OK", "SOLD_OUT")]
    days_seen = 0
    try:
        for o in good:
            if o.verdict.kind != "OK":
                continue
            raw = o.text.encode("utf-8")
            rows = hx.parse_award_evidence(raw)
            days_seen += len(json.loads(raw).get("days", {}))
            res.rows += len(rows)
            if cfg.dry_run or not rows:
                res.dates_ok += len(rows)
                if rows:
                    res.horizon_last_ok = max(res.horizon_last_ok or "", rows[-1].stay_date)
                continue
            stamp = cfg.now().strftime("%Y%m%dT%H%M%S")
            rel = f"evidence/hyatt/avail_days/hyatt_{sc}_{o.window[0]}_{o.window[1]}_{stamp}.json"
            wr = write_rate_batch(conn, hotel_id=hid, source_type=SOURCE_TYPE, source_url=o.url, rows=rows,
                                  evidence_relpath=rel, evidence_bytes=raw, evidence_grade="RAW",
                                  workspace_dir=cfg.workspace, today=cfg.today, commit=False)
            res.evidence.append(rel)
            res.dates_ok += wr.written
            for _, why in wr.rejected:
                res.rejected[why] += 1
            if wr.written:
                res.horizon_last_ok = max(res.horizon_last_ok or "", max(r.stay_date for r in rows))
        res.rows = res.dates_ok
    except Exception as ex:
        if conn is not None:
            conn.rollback()
        res.status, res.reason, res.detail = "FAILED", "DB_OR_PARSE_ERROR", f"{type(ex).__name__}: {ex}"
        log.exception("%s: write failed", sc)
        _record(conn, hid, res, cfg)
        return res

    rej = ("; rejected: " + ", ".join(f"{k}={v}" for k, v in sorted(res.rejected.items()))) if res.rejected else ""
    if not bad:
        if res.rows:
            res.status, res.detail = "OK", f"{res.rows} award nights{rej}"
        elif days_seen:
            res.status, res.reason = "NO_AVAILABILITY", "NO_STANDARD_ROOM"
            res.detail = f"{days_seen} days list award rooms but none is a standard room (suites/clubs only){rej}"
        else:
            res.status, res.reason = "NO_AVAILABILITY", "SOLD_OUT_HOTEL"
            res.detail = f"soldOutHotel on {len(outs)} window(s)" + ("" if len(outs) == 1 else f" of {CHUNK_DAYS} days") + " and on the confirmation window" * (len(outs) == 1)
    else:
        first = bad[0]
        res.reason = first.verdict.reason
        res.url = first.url
        res.detail = " | ".join(
            f"{o.window[0]}..{o.window[1]} {'HTTP ' + str(o.status) if o.status else 'no HTTP response'} {o.verdict.reason} after {o.attempts} tries: "
            f"{(o.verdict.detail or o.text or '')[:100]!r}" for o in bad) + rej
        res.status = "PARTIAL" if good else "FAILED"
    _record(conn, hid, res, cfg)
    return res


def _record(conn, hotel_id: str, res: HotelResult, cfg: Cfg, source: str = SOURCE) -> None:
    """State + the rows written above commit together (one transaction per hotel)."""
    if cfg.dry_run or conn is None:
        return
    harvest_state.record(conn, source, hotel_id, res.status, reason=res.reason, detail=res.detail, url=res.url,
                         dates_ok=res.dates_ok, dates_total=res.dates_total, horizon_last_ok=res.horizon_last_ok,
                         grid_id=res.grid_id, commit=False)
    for attempt in range(6):
        try:
            conn.commit()
            break
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < 5:
                time.sleep(0.5 * (2 ** attempt) + random.uniform(0.1, 0.5))
                continue
            raise


# ── database ────────────────────────────────────────────────────────────────────────────────
def open_db(path: str, read_only_if_dry: bool = False):
    import sqlite3
    if read_only_if_dry:
        if not os.path.exists(path):
            return None
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    conn = sqlite3.connect(path, timeout=60)
    from engine.schema import require_v2
    require_v2(conn, "Hyatt harvester")   # before any request or Chrome launch
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute(HARVEST_STATUS_DDL)
    conn.commit()
    return conn


def hotels_missing_from_db(conn, hotels) -> List[dict]:
    have = {r[0] for r in conn.execute("SELECT id FROM hotels WHERE id LIKE 'hyatt\\_%' ESCAPE '\\'")}
    return [h for h in hotels if h["hotel_id"] not in have]


# ── run ─────────────────────────────────────────────────────────────────────────────────────
def run(args) -> int:
    workspace = os.path.abspath(args.workspace_dir)
    db_path = args.db or os.path.join(workspace, "hotel_stays.db")
    logfile = setup_logging(workspace)
    spirit = [s.strip().lower() for s in args.spirit.split(",")] if args.spirit else None
    cats = [s.strip() for s in args.cat.split(",")] if args.cat else None
    hotels = load_redeemable_hotels(spirit, cats)
    if args.total_workers > 1:
        hotels = hotels[args.worker_id - 1::args.total_workers]
    conn = open_db(db_path, read_only_if_dry=args.dry_run)
    states = harvest_state.load_all(conn, SOURCE) if conn is not None and _has_status(conn) else {}
    todo = select_hotels(hotels, states, spirit=spirit, force=args.force, retry_failed=args.retry_failed,
                         refresh_days=args.refresh_days, limit=args.limit)
    if conn is not None and _has_status(conn):
        for hid, grid in conn.execute("SELECT hotel_id, grid_id FROM harvest_status WHERE source = ? AND grid_id LIKE 'span:%'", (SOURCE,)):
            for h in todo:
                if h["hotel_id"] == hid:
                    h["span_hint"] = int(grid.split(":")[1])
    if conn is not None and not args.dry_run:
        missing = hotels_missing_from_db(conn, todo)
        for h in missing:
            harvest_state.record(conn, SOURCE, h["hotel_id"], "FAILED", reason="HOTEL_NOT_IN_DB",
                                 detail="hotel row is missing from `hotels`; import the catalog first", retry_days=7)
            say(f"  [FAILED] {h['spirit_code']}  HOTEL_NOT_IN_DB")
        skip = {h["hotel_id"] for h in missing}
        todo = [h for h in todo if h["hotel_id"] not in skip]
    cfg = Cfg(workspace=workspace, months=min(args.months, 12), dry_run=args.dry_run)
    if args.months > 12:
        say(f"[!] --months {args.months} > 12: capped at {MAX_WINDOW_DAYS} days (Hyatt's booking horizon)")
    say(f"[HYATT_AWARD w{args.worker_id}/{args.total_workers}] {len(todo)} hotels to do (catalog {len(hotels)}), "
        f"window {cfg.today} .. {plan_windows(cfg.today, cfg.months)[0][1]}, db={db_path}, log={logfile}"
        f"{'  DRY-RUN' if args.dry_run else ''}")
    if not todo:
        return 0
    session = HyattCDPSession(port=args.port, tag="avail", max_reqs=(args.max_reqs, args.max_reqs + 40))
    console = Console(len(todo), f"HYATT_AWARD w{args.worker_id}")
    blocked_streak = 0
    rc = 0
    t0 = time.time()
    try:
        session.start()
        for hotel in todo:
            res = harvest_award_hotel(session, conn, hotel, cfg)
            console.hotel(hotel["spirit_code"], res, session)
            blocked_streak = blocked_streak + 1 if res.status == "FAILED" else 0
            if blocked_streak >= args.abort_after:
                say(f"[!] {blocked_streak} hotels in a row FAILED - Hyatt is blocking us; stopping. "
                    f"Re-run later with --retry-failed.")
                rc = 2
                break
            cfg.sleep(random.uniform(*cfg.pace))
    except KeyboardInterrupt:
        say("[!] interrupted; finishing")
        rc = 130
    except RuntimeError as ex:                     # Chrome could not be (re)started
        say(f"[!] fatal: {ex}")
        rc = 3
    finally:
        session.close()
        if conn is not None:
            conn.close()
    el = time.time() - t0
    c = console.counts
    say(f"[HYATT_AWARD w{args.worker_id}] DONE {console.done} hotels in {el/60:.1f} min ({el/max(console.done,1):.1f} s/hotel): "
        f"ok {c['OK']}  no-avail {c['NO_AVAILABILITY']}  partial {c['PARTIAL']}  failed {c['FAILED']}  "
        f"rows {console.rows:,}  requests {session.requests} ({session.requests/max(console.done,1):.2f}/hotel)  "
        f"chrome recycles {session.recycles}")
    return rc


def _has_status(conn) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name='harvest_status'").fetchone() is not None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Hyatt award calendar harvester (avail/days, one request per hotel)")
    p.add_argument("--months", type=int, default=12, help="months ahead from today (max 12, default 12)")
    p.add_argument("--spirit", help="comma-separated spirit codes (processed regardless of state)")
    p.add_argument("--cat", help="comma-separated award categories, e.g. 3,4,5")
    p.add_argument("--limit", type=int, help="max hotels this run")
    p.add_argument("--dry-run", action="store_true", help="fetch and parse, write nothing (no DB, no evidence, no state)")
    p.add_argument("--retry-failed", action="store_true", help="only hotels whose state is FAILED/PARTIAL, now")
    p.add_argument("--refresh-days", type=int, help="also redo OK hotels last done more than N days ago")
    p.add_argument("--force", action="store_true", help="every hotel, ignoring harvest_status")
    p.add_argument("--resume", action="store_true", help="(kept for old command lines; resuming from harvest_status is now the default)")
    p.add_argument("--workers", type=int, default=1, help="parallel Chromes (spawns worker processes on ports port..port+N-1)")
    p.add_argument("--visible", action="store_true",
                   help="show the Chrome window (default: opened off-screen so it never pops up on the desktop)")
    p.add_argument("--worker-id", type=int, default=1)
    p.add_argument("--total-workers", type=int, default=1)
    p.add_argument("--port", type=int, default=9322, help="Chrome remote-debugging port (first one with --workers)")
    p.add_argument("--max-reqs", type=int, default=110, help="requests per Chrome before a proactive recycle (+0..40 jitter)")
    p.add_argument("--abort-after", type=int, default=4, help="stop after this many consecutive FAILED hotels")
    p.add_argument("--db", help="database file (default <workspace>/hotel_stays.db)")
    p.add_argument("--workspace-dir", default=ROOT, help="where evidence/, logs/ and hotel_stays.db live (default: project root)")
    return p


def spawn_workers(args, script: str) -> int:
    """--workers N: N child processes, each with its own Chrome, hotel partition and port."""
    passthrough, skip = [], False
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if skip:
            skip = False
            continue
        if a == "--workers":
            skip = True
            continue
        if a.startswith("--workers="):
            continue
        passthrough.append(a)
    procs = []
    for i in range(args.workers):
        cmd = [sys.executable, script, *passthrough, "--worker-id", str(i + 1), "--total-workers", str(args.workers),
               "--port", str(args.port + i)]
        procs.append(subprocess.Popen(cmd))
        time.sleep(3)                                     # stagger the Chrome launches
    try:
        return max(p.wait() for p in procs)
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()
        return 130


def _disable_quick_edit() -> None:
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


def main(argv=None) -> int:
    _disable_quick_edit()
    global OFFSCREEN
    args = build_parser().parse_args(argv)
    OFFSCREEN = not args.visible
    if args.workers > 1:
        return spawn_workers(args, os.path.abspath(__file__))
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
