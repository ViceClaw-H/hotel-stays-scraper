"""Shangri-La Group (Shangri-La, Kerry, JEN, Traders) all-in cash harvester - schema v2 contract.

(File name kept for the .bat / manual; it is no longer a "365 calendar + 5 percentiles" crawler - see below.)

Source: Shangri-La's own booking gateway, plain HTTPS (no browser, no login):
    POST https://www.shangri-la.com/v1/website      header  x-sl-service: hotelDetailService.queryHotelDetail(query)
    body {"service": ..., "query": {hotelCode, checkInDate, checkOutDate, peopleCondition, roomNum, currency,
                                    taxModel: "INCLUDED"}, "context": {...}}
It is the call behind the room-rate page; one request = ONE stay date, ALL rooms x ALL rate plans, in the
hotel's own currency, with service charge + tax + fees when taxModel is INCLUDED (the site's
"Tax & Fee Incl." toggle). Details, request/response evidence and limits: engine/extractors/shangrila.py.

WHY NOT THE CALENDAR (searchSuggestService.queryCalendarPrice)?  It is the cheapest call (one request = up
to ~90 days) but (1) it prices only today..today+91 whatever startDate is (a full year needs no more calls,
it simply does not exist), (2) its amount is the lowest rate WITHOUT service charge and tax, (3) it names no
room and ignores every tax / room / rate filter. Storing it would break the contract (an excl. price as
final, no room). The old quarterly windows failed for a different reason: the request lacked the
`x-sl-service` header, so the gateway answered {"status":403,...} inside an HTTP 200.

What this script does, per hotel (every decision is traced in logs/shangrila_crawler.log):
  1. dates: a FIXED grid (same family as the Wyndham harvester, so stay dates line up across chains):
     W24 = next Wednesday + Saturday of 12 monthly anchors (24 dates, --grid weekly = 104, --grid daily =
     every night of the 363-day booking window). Nearest date first; dates the CRS refuses (status 21000
     "expired" = past the booking window) end the hotel early - that IS the horizon.
     The first 3 dates are the probes: if all three come back sold-out the hotel is stopped as
     NO_AVAILABILITY (retry in 14 days) instead of spending 21 more calls.
  2. per date: cheapest all-in cash rate of the site's "Standard" rate tab -> one row (room = the room card
     title verbatim). Transient failures (timeout, 5xx, 201, 429) are retried twice, then recorded as failed
     dates (PARTIAL); a blocked gateway (403) slows every worker down and stops the run if it persists.
  3. evidence: every raw response, unmodified, in ONE gzip JSON document per hotel and run
     (evidence/shangrila/raw/<hotel_id>__<timestamp>.json.gz). Rows are derived from that document with
     engine.extractors.shangrila.parse_evidence - exactly what the offline verifier replays.
  4. ONE database transaction per hotel: rows + evidence registry via engine.rate_writer.write_rate_batch
     and the state via engine.harvest_state.record (harvest_status, source 'SHANGRILA'): reason, verbatim
     error, the URL where it got stuck, an expiring retry_after. Writer rejections are recorded, never dropped.

Usage (from the project root):
    python crawlers\\shangrila_master_365_and_percentiles_crawler.py                 # every hotel that is due
    python crawlers\\shangrila_master_365_and_percentiles_crawler.py --limit 5
    python crawlers\\shangrila_master_365_and_percentiles_crawler.py --hotel SLS shang_jakarta_shangrila
    python crawlers\\shangrila_master_365_and_percentiles_crawler.py --retry-failed  # FAILED / PARTIAL now
    python crawlers\\shangrila_master_365_and_percentiles_crawler.py --grid weekly
    python crawlers\\shangrila_master_365_and_percentiles_crawler.py --dry-run --limit 2   # no DB writes
"""
import argparse
import concurrent.futures
import json
import logging
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine import harvest_state                                    # noqa: E402
from engine.extractors import shangrila as sx                       # noqa: E402
from engine.provenance_gate import check_row                        # noqa: E402
from engine.rate_writer import write_rate_batch                     # noqa: E402
from engine.schema import schema_version                            # noqa: E402

SOURCE = "SHANGRILA"
SOURCE_TYPE = "OFFICIAL_SHANGRILA_CRS"
DEFAULT_DB = os.path.join(ROOT, "hotel_stays.db")
DEFAULT_LOG = os.path.join(ROOT, "logs", "shangrila_crawler.log")
CODES_FILE = os.path.join(ROOT, "catalogs", "shangrila", "shangrila_hotel_codes.json")
EVIDENCE_REL_DIR = "evidence/shangrila/raw"
BRANDS = ("SHANGRI-LA", "SHANGRI_LA", "JEN", "KERRY", "TRADERS")

# Catalog ids that are NOT in the codes file although the same physical hotel is (under another id). Each code was
# confirmed live against the CRS on 2026-09-21 (hotelDetail name matched, or "HOTEL_CLOSE ... ceased operation").
# They are harvested once, under the id that is in the codes file; these ids become DUPLICATE in harvest_status.
ID_ALIASES = {
    "shang_shanghai_tradershongqiaoairport": "CNSHA007",       # CRS name: Traders Hongqiao Airport, Shanghai
    "shang_shanghai_shangrilahongqiaoairport": "CNSHA005",     # Shangri-La Hongqiao Airport, Shanghai
    "shang_male_villingiliresort": "SLMD",                     # Shangri-La Villingili, Maldives
    "shang_jakarta_shangrilaresidences": "SLJR",               # CRS: HOTEL_CLOSE (ceased operation)
    "shang_yangon_shangrilaservicedapartments": "SLYR",        # CRS: HOTEL_CLOSE
    "shang_yangon_suleshangrila": "SLMY",                      # CRS: HOTEL_CLOSE
    "shang_singapore_shangrilaapartment": "SSAR",              # CRS: HOTEL_CLOSE
}

# ------------------------------------------------------------------------------------------------
# The date grid. FIXED (not derived from today) so every run - and every row already in the database -
# refers to the same stay dates. Same construction as the Wyndham harvester (W24 / weekly).
# ------------------------------------------------------------------------------------------------
ANCHOR = date(2026, 9, 21)
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
    return [(start + timedelta(days=i)).isoformat() for i in range(52 * 7)
            if (start + timedelta(days=i)).weekday() in (_WED, _SAT)]


def make_grid(kind: str = "stratified", today: Optional[date] = None) -> Tuple[str, List[str]]:
    """(grid id, dates in the CRS booking window today+1 .. today+HORIZON_DAYS)."""
    today = today or date.today()
    lo, hi = today + timedelta(days=1), today + timedelta(days=sx.HORIZON_DAYS)
    if kind == "daily":
        dates = [(lo + timedelta(days=i)).isoformat() for i in range((hi - lo).days + 1)]
        return "DAILY", dates
    raw = weekly_dates() if kind == "weekly" else stratified_dates()
    dates = [d for d in raw if lo <= date.fromisoformat(d) <= hi]
    return f"W{len(raw)}-{ANCHOR.isoformat()}", dates


# ------------------------------------------------------------------------------------------------
# Catalog
# ------------------------------------------------------------------------------------------------
def _slugs(url: Optional[str], city: str, entry: dict) -> Tuple[str, str]:
    if entry.get("city_slug") and entry.get("brand_slug"):
        return entry["city_slug"], entry["brand_slug"]
    m = re.search(r"shangri-la\.com/en/([^/]+)/([^/]+)/", url or "")
    if m:
        return m.group(1), m.group(2)
    return re.sub(r"[^a-z]", "", (city or "").lower()) or "hotel", "shangrila"


def load_catalog(conn: sqlite3.Connection, codes_path: str = CODES_FILE) -> List[dict]:
    with open(codes_path, "r", encoding="utf-8") as fh:
        codes = json.load(fh)
    marks = ",".join("?" * len(BRANDS))
    rows = conn.execute(
        f"SELECT id, name, city, country, currency, official_url, brand FROM hotels WHERE brand IN ({marks}) "
        "ORDER BY country, city, name", BRANDS).fetchall()
    out = []
    canonical: Dict[str, str] = {}                     # CRS code -> catalog id that carries it
    for hid, name, city, country, cur, url, brand in sorted(rows, key=lambda r: (r[0] not in codes,)):   # codes-file ids first
        entry = codes.get(hid) or {}
        code = entry.get("code") or ID_ALIASES.get(hid)
        city_slug, brand_slug = _slugs(url, city, entry)
        dup = canonical.get(code) if code else None
        if code and dup is None:
            canonical[code] = hid
        out.append({"id": hid, "name": name, "city": city, "country": country, "currency": cur, "brand": brand,
                    "code": code, "city_slug": city_slug, "brand_slug": brand_slug, "duplicate_of": dup})
    out.sort(key=lambda h: (h["country"], h["city"], h["name"], h["id"]))
    return out


# ------------------------------------------------------------------------------------------------
# HTTP: one shared throttle for all workers, adaptive backoff on blocks
# ------------------------------------------------------------------------------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Content-Type": "application/json", "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9", "Origin": "https://www.shangri-la.com",
}


class Throttle:
    """Min seconds between request starts (all workers) + a shared pause that grows on blocks."""

    def __init__(self, interval: float):
        self.interval = interval
        self._lock = threading.Lock()
        self._next = 0.0
        self._pause = 0.0
        self.blocks = 0          # consecutive block-like answers, across workers

    def wait(self):
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next) + self._pause
            self._next = start + self.interval
        delay = start - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def penalize(self):
        with self._lock:
            self.blocks += 1
            self._pause = min(60.0, max(2.0, self._pause * 2))

    def relax(self):
        with self._lock:
            self.blocks = 0
            self._pause = self._pause / 2 if self._pause > 1 else 0.0


class RunAborted(Exception):
    pass


_tls = threading.local()


class _StdlibResponse:
    """Small curl_cffi-compatible response shape for the official CRS fallback."""

    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self.text = body.decode("utf-8", errors="replace")


class _StdlibSession:
    """Use normal HTTPS when curl_cffi is unavailable; no synthetic or altered response data."""

    def post(self, url, *, json, headers, impersonate=None, timeout=60):
        del impersonate  # The standard client cannot impersonate a browser; request data stays identical.
        body = __import__("json").dumps(json, separators=(",", ":")).encode("utf-8")
        request = Request(url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                return _StdlibResponse(response.status, response.read())
        except HTTPError as exc:
            return _StdlibResponse(exc.code, exc.read())


def solve_acw_sc_v2(arg1: str) -> str:
    """Reverse-engineered Alibaba Cloud WAF acw_sc__v2 dynamic cookie algorithm."""
    pos_list = [
        0x0f, 0x23, 0x1d, 0x18, 0x21, 0x10, 0x01, 0x26, 0x0a, 0x09,
        0x13, 0x1f, 0x28, 0x1b, 0x16, 0x17, 0x19, 0x0d, 0x06, 0x0b,
        0x27, 0x12, 0x14, 0x08, 0x0e, 0x15, 0x20, 0x1a, 0x02, 0x1e,
        0x07, 0x04, 0x11, 0x05, 0x03, 0x1c, 0x22, 0x25, 0x0c, 0x24
    ]
    mask = "3000176000856006061501533003690027800375"
    out_put_list = ["" for _ in range(len(pos_list))]
    for i in range(len(arg1)):
        this_i = arg1[i]
        for j in range(len(pos_list)):
            if pos_list[j] == i + 1:
                out_put_list[j] = this_i
    arg2 = "".join(out_put_list)
    arg3 = ""
    for i in range(0, min(len(arg2), len(mask)), 2):
        str_char = int(arg2[i:i+2], 16)
        mask_char = int(mask[i:i+2], 16)
        xor_char = hex(str_char ^ mask_char)[2:]
        if len(xor_char) == 1:
            xor_char = "0" + xor_char
        arg3 += xor_char
    return arg3


def _session():
    if not hasattr(_tls, "s"):
        try:
            from curl_cffi import requests as cr
            _tls.s = cr.Session()
            # Initialize with homepage to bypass Alibaba Cloud WAF challenge
            try:
                r1 = _tls.s.get("https://www.shangri-la.com/en/", impersonate="chrome124", timeout=15)
                m = re.search(r"var arg1='([A-Fa-f0-9]+)';", r1.text)
                if m:
                    cookie_val = solve_acw_sc_v2(m.group(1))
                    _tls.s.cookies.set("acw_sc__v2", cookie_val, domain=".shangri-la.com")
            except Exception:
                pass
        except ImportError:
            _tls.s = _StdlibSession()
    return _tls.s


def fetch_detail(hotel: dict, stay_date: str, throttle: Throttle, log: logging.Logger, timeout: int = 60) -> dict:
    """One stay date -> evidence item (raw body kept unmodified). Retries transient failures twice."""
    cout = (date.fromisoformat(stay_date) + timedelta(days=1)).isoformat()
    query = sx.detail_query(hotel["code"], stay_date, cout)
    purl = sx.page_url(hotel["city_slug"], hotel["brand_slug"], hotel["code"], stay_date, cout)
    headers = dict(HEADERS, **{"x-sl-service": sx.SERVICE_DETAIL, "Referer": purl})
    item = {"kind": "detail", "stay_date": stay_date, "request_url": purl, "api_url": sx.API_URL,
            "service": sx.SERVICE_DETAIL, "request": query, "http_status": None, "fetched_at": None,
            "body": None, "error": None}
    for attempt in range(3):
        throttle.wait()
        t0 = time.time()
        item["fetched_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            r = _session().post(sx.API_URL, json=sx.request_envelope(sx.SERVICE_DETAIL, query), headers=headers,
                                impersonate="chrome124", timeout=timeout)
            item["http_status"], item["body"], item["error"] = r.status_code, r.text, None
        except Exception as exc:           # timeout / connection reset / TLS
            item["http_status"], item["body"], item["error"] = None, None, f"{type(exc).__name__}: {exc}"[:300]
        p = sx.parse_response(stay_date, purl, item["http_status"], item["body"], item["error"])
        log.debug("%s %s attempt %d: http=%s %.1fs %dB -> %s %s %s", hotel["code"], stay_date, attempt + 1,
                  item["http_status"], time.time() - t0, len(item["body"] or ""), p.kind, p.code,
                  (f'{p.row.cash_rate} {p.row.currency} | {p.row.room_name}' if p.row else p.message[:120]))
        if p.kind != sx.KIND_FAIL:
            throttle.relax()
            return item
        throttle.penalize()
        if p.code == "BLOCKED_403" and throttle.blocks >= 8:
            raise RunAborted(f"gateway keeps blocking (403) - stopping the run; last URL {purl}")
        if item["body"] and "var arg1=" in item["body"]:
            m = re.search(r"var arg1='([A-Fa-f0-9]+)';", item["body"])
            if m:
                cookie_val = solve_acw_sc_v2(m.group(1))
                _session().cookies.set("acw_sc__v2", cookie_val, domain=".shangri-la.com")
                time.sleep(1.0)
                continue
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    return item


# ------------------------------------------------------------------------------------------------
# One hotel: fetch (worker thread, no DB) -> HotelRun; write (main thread, one transaction)
# ------------------------------------------------------------------------------------------------
PROBES = 3
MAX_CONSECUTIVE_FAILS = 3


@dataclass
class HotelRun:
    hotel: dict
    planned: List[str]
    responses: List[dict] = field(default_factory=list)
    parsed: Dict[str, sx.ParsedResponse] = field(default_factory=dict)
    verdict: str = ""            # "", "NO_AVAILABILITY_PROBES", "INACTIVE", "HORIZON", "ABORTED_FAILS"
    seconds: float = 0.0
    calls: int = 0
    bytes: int = 0


def harvest_hotel(hotel: dict, dates: List[str], throttle: Throttle, log: logging.Logger) -> HotelRun:
    run = HotelRun(hotel, dates)
    t0 = time.time()
    consecutive_fail = 0
    for i, d in enumerate(dates):
        item = fetch_detail(hotel, d, throttle, log)
        p = sx.parse_response(d, item["request_url"], item["http_status"], item["body"], item["error"])
        run.responses.append(item)
        run.parsed[d] = p
        run.calls += 1
        run.bytes += len(item["body"] or "")
        if p.kind == sx.KIND_INACTIVE:
            run.verdict = "INACTIVE"
            break
        if p.kind == sx.KIND_HORIZON:
            run.verdict = "HORIZON"
            break
        consecutive_fail = consecutive_fail + 1 if p.kind == sx.KIND_FAIL else 0
        if consecutive_fail >= MAX_CONSECUTIVE_FAILS:
            run.verdict = "ABORTED_FAILS"
            break
        if i + 1 == PROBES and len(dates) > PROBES and all(run.parsed[x].kind == sx.KIND_NOAVAIL for x in dates[:PROBES]):
            run.verdict = "NO_AVAILABILITY_PROBES"
            break
    run.seconds = time.time() - t0
    return run


def classify(run: HotelRun, rows: list, rejected: List[Tuple[str, str]]) -> dict:
    """Machine verdict for harvest_status. 'done' = every planned window answered definitively."""
    defin = (sx.KIND_OK, sx.KIND_NOAVAIL, sx.KIND_HORIZON, sx.KIND_INACTIVE)
    answered = [d for d in run.planned if d in run.parsed and run.parsed[d].kind in defin]
    fails = [d for d in run.planned if d in run.parsed and run.parsed[d].kind == sx.KIND_FAIL]
    never = [d for d in run.planned if d not in run.parsed]
    first_url = run.parsed[run.planned[0]].url if run.planned else None
    horizon = next((run.parsed[d] for d in run.planned if d in run.parsed and run.parsed[d].kind == sx.KIND_HORIZON), None)
    last_ok = max((r.stay_date for r in rows), default=None)
    n_ok = len(rows) - len([1 for d, _ in rejected])  # rows the writer actually stored
    out = {"dates_total": len(run.planned), "horizon_last_ok": last_ok, "url": None, "reason": None, "detail": None}

    def stuck(p: sx.ParsedResponse):
        out["url"], out["reason"], out["detail"] = p.url, p.code, p.message

    if run.verdict == "INACTIVE":
        p = run.parsed[[d for d in run.planned if d in run.parsed][-1]]
        out.update(status="INACTIVE", dates_ok=len(answered)); stuck(p)
        return out
    if horizon is not None:
        # the CRS answered "expired" for this date: every later planned date is beyond the window too -> answered
        answered = answered + never
        never = []
    if fails or run.verdict == "ABORTED_FAILS":
        first_fail = run.parsed[fails[0]] if fails else None
        st = "PARTIAL" if rows else "FAILED"
        out.update(status=st, dates_ok=len(answered))
        if first_fail:
            stuck(first_fail)
            out["detail"] = f"{len(fails)} of {len(run.planned)} dates failed; first {fails[0]}: {first_fail.message}"
        return out
    if rejected:
        codes = sorted({c for _, c in rejected})
        out.update(status="PARTIAL" if n_ok > 0 else "FAILED", dates_ok=len(answered) - len(rejected),
                   reason="WRITER_REJECTED:" + ",".join(codes),
                   detail=f"{len(rejected)} rows rejected by the writer: {rejected[:5]}", url=first_url)
        return out
    if run.verdict == "NO_AVAILABILITY_PROBES" or not rows:
        p = run.parsed[run.planned[0]]
        out.update(status="NO_AVAILABILITY", dates_ok=len(answered), reason=p.code or "NO_RATES",
                   detail=f"no bookable standard rate on the {len([d for d in run.parsed])} dates asked: "
                          f"{sorted({x.code for x in run.parsed.values()})}", url=first_url)
        return out
    out.update(status="OK", dates_ok=len(answered))
    if horizon is not None:
        out["detail"] = f"booking window ends before {horizon.stay_date} ({horizon.message})"
    return out


def write_hotel(conn: sqlite3.Connection, run: HotelRun, workspace: str, stamp: str, grid_id: str,
                today: Optional[date] = None) -> dict:
    """Evidence + rows + state in ONE transaction. Returns the classification plus written/superseded counts."""
    hotel = run.hotel
    doc = sx.build_evidence(hotel["id"], hotel["code"], stamp, run.responses)
    rows = sx.parse_evidence(doc)                       # rows come from the stored bytes, nothing else
    rejected: List[Tuple[str, str]] = []
    written = superseded = 0
    rel = f"{EVIDENCE_REL_DIR}/{hotel['id']}__{stamp.replace(':', '').replace('-', '')}.json.gz"
    try:
        if not rows:
            # no row means no registry entry, but the answers that justify NO_AVAILABILITY / INACTIVE / FAILED stay on
            # disk too (unregistered: nothing in rate_records refers to them)
            full = os.path.join(workspace, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full + ".tmp", "wb") as fh:
                fh.write(doc)
            os.replace(full + ".tmp", full)
        if rows:
            res = write_rate_batch(conn, hotel_id=hotel["id"], source_type=SOURCE_TYPE, source_url=rows[0].source_url,
                                   rows=rows, evidence_relpath=rel, evidence_bytes=doc, evidence_grade="RAW",
                                   workspace_dir=workspace,
                                   notes=f"Shangri-La CRS queryHotelDetail taxModel=INCLUDED, grid {grid_id}", today=today,
                                   commit=False)
            rejected, written, superseded = res.rejected, res.written, res.superseded
        verdict = classify(run, rows, rejected)
        harvest_state.record(conn, SOURCE, hotel["id"], verdict["status"], reason=verdict["reason"], detail=verdict["detail"],
                             url=verdict["url"], grid_id=grid_id, dates_ok=verdict["dates_ok"], dates_total=verdict["dates_total"],
                             horizon_last_ok=verdict["horizon_last_ok"], commit=False)
        conn.commit()
    except Exception:
        conn.rollback()                                 # all or nothing per hotel
        raise
    verdict.update(written=written, superseded=superseded, evidence=rel, rows=len(rows), rejected=rejected)
    return verdict


def dry_run_hotel(run: HotelRun, workspace: str, stamp: str, grid_id: str, today: Optional[date] = None) -> dict:
    """Same derivation, no database: evidence goes to the temp workspace, rejections are predicted."""
    hotel = run.hotel
    doc = sx.build_evidence(hotel["id"], hotel["code"], stamp, run.responses)
    rows = sx.parse_evidence(doc)
    rejected = [(r.stay_date, why) for r in rows
                if (why := check_row(r.stay_date, r.cash_rate, r.currency, r.points_required, r.room_name, today))]
    rel = f"{EVIDENCE_REL_DIR}/{hotel['id']}__{stamp.replace(':', '').replace('-', '')}.json.gz"
    full = os.path.join(workspace, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(doc)
    verdict = classify(run, rows, rejected)
    verdict.update(written=0, superseded=0, evidence=full, rows=len(rows), rejected=rejected)
    return verdict


# ------------------------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------------------------
def setup_logging(path: str) -> logging.Logger:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    log = logging.getLogger("shangrila")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fh = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)
    return log


def say(msg: str):
    print(msg, flush=True)


def select_hotels(catalog: List[dict], states: Dict[str, dict], args) -> List[dict]:
    if args.hotel:
        wanted = {h.lower() for h in args.hotel}
        picked = [h for h in catalog if h["id"].lower() in wanted or (h["code"] or "").lower() in wanted]
        missing = wanted - {h["id"].lower() for h in picked} - {(h["code"] or "").lower() for h in picked}
        if missing:
            say(f"  not in the catalog (ignored): {sorted(missing)}")
        return picked
    pool = catalog
    if args.country:
        pool = [h for h in pool if h["country"].lower() == args.country.lower()]
    if args.retry_failed:
        return [h for h in pool if (states.get(h["id"]) or {}).get("status") in ("FAILED", "PARTIAL")]
    return harvest_state.due_hotels(pool, states, key="id", refresh_days=args.refresh_days)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Shangri-La all-in cash harvester (schema v2)")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--workspace", default=ROOT, help="directory that holds evidence/ (default: project root)")
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--limit", type=int, help="stop after N hotels")
    ap.add_argument("--hotel", nargs="+", help="hotel ids or CRS hotel codes (ignores harvest_status)")
    ap.add_argument("--country")
    ap.add_argument("--retry-failed", action="store_true", help="only FAILED / PARTIAL hotels, regardless of retry_after")
    ap.add_argument("--refresh-days", type=int, help="also re-harvest OK hotels older than N days")
    ap.add_argument("--grid", choices=("stratified", "weekly", "daily"), default="stratified")
    ap.add_argument("--dates", nargs="+", help="explicit stay dates (YYYY-MM-DD) instead of a grid")
    ap.add_argument("--workers", type=int, default=2, help="hotels fetched in parallel (writes stay single-threaded)")
    ap.add_argument("--interval", type=float, default=0.6, help="min seconds between request starts, all workers")
    ap.add_argument("--dry-run", action="store_true", help="fetch + parse, no DB writes; evidence goes to a temp dir")
    args = ap.parse_args(argv)

    log = setup_logging(args.log)
    if not os.path.exists(args.db):
        say(f"database not found: {args.db} (this script never creates one)")
        return 2
    conn = (sqlite3.connect(Path(args.db).resolve().as_uri() + "?mode=ro", uri=True) if args.dry_run
            else sqlite3.connect(args.db, timeout=60))
    has_state = bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='harvest_status'").fetchone())
    if not args.dry_run and (schema_version(conn) < 2 or not has_state):
        say(f"{args.db} is not a schema v2 database (rate_records lacks room_name / harvest_status is missing): "
            "run the contract migration first. Nothing was written.")
        conn.close()
        return 2
    catalog = load_catalog(conn)
    states = harvest_state.load_all(conn, SOURCE) if has_state else {}

    if args.dates:
        grid_id, dates = "EXPLICIT", sorted(set(args.dates))
    else:
        grid_id, dates = make_grid(args.grid)
    todo = select_hotels(catalog, states, args)
    if args.limit:
        todo = todo[: args.limit]

    workspace = tempfile.mkdtemp(prefix="shangrila_dry_") if args.dry_run else args.workspace
    say(f"Shangri-La harvest: {len(todo)} hotels of {len(catalog)} in the catalog | grid {grid_id} = {len(dates)} dates "
        f"({dates[0]} .. {dates[-1]}) | up to {len(dates)} calls/hotel" + (" | DRY RUN" if args.dry_run else ""))
    log.info("start db=%s grid=%s dates=%d hotels=%d workers=%d interval=%.2f dry=%s", args.db, grid_id, len(dates),
             len(todo), args.workers, args.interval, args.dry_run)

    throttle = Throttle(args.interval)
    stamp = datetime.now().isoformat(timespec="seconds")
    totals = {"hotels": 0, "rows": 0, "calls": 0, "bytes": 0, "seconds": 0.0}
    by_status: Dict[str, int] = {}
    problems: List[str] = []
    t_start = time.time()
    aborted = None

    runnable = []
    for h in todo:
        if h.get("duplicate_of"):
            if not args.dry_run:
                harvest_state.record(conn, SOURCE, h["id"], "DUPLICATE", reason=h["duplicate_of"],
                                     detail=f"same CRS hotel code {h['code']} as {h['duplicate_of']}, which carries the data",
                                     url=None, grid_id=grid_id, retry_days=None)
            by_status["DUPLICATE"] = by_status.get("DUPLICATE", 0) + 1
            say(f"  [--] {h['name']} ({h['id']}): DUPLICATE of {h['duplicate_of']}")
            continue
        if not h["code"]:
            v = {"status": "FAILED", "reason": "NO_HOTEL_CODE", "detail": "the catalog has no CRS hotelCode for this hotel; "
                 "add it to catalogs/shangrila/shangrila_hotel_codes.json", "url": None}
            if not args.dry_run:
                harvest_state.record(conn, SOURCE, h["id"], v["status"], reason=v["reason"], detail=v["detail"], url=None,
                                     grid_id=grid_id, dates_ok=0, dates_total=len(dates), retry_days=30)
            by_status["FAILED"] = by_status.get("FAILED", 0) + 1
            problems.append(f"{h['id']}: FAILED NO_HOTEL_CODE")
            say(f"  [--] {h['name']}: FAILED NO_HOTEL_CODE")
            continue
        runnable.append(h)

    def job(h):
        return harvest_hotel(h, dates, throttle, log)

    def handle(n: int, h: dict, fut) -> bool:
        """Consume one finished hotel (main thread: the only place that touches the database). False = stop the run."""
        nonlocal aborted
        try:
            run = fut.result()
        except RunAborted as exc:
            aborted = str(exc)
            log.error("run aborted: %s", exc)
            say(f"  RUN STOPPED: {exc}")
            return False
        except Exception as exc:                       # a bug or a network fault: never lose the rest of the run
            log.exception("hotel %s crashed", h["id"])
            if not args.dry_run:
                harvest_state.record(conn, SOURCE, h["id"], "FAILED", reason="CRASH", detail=f"{type(exc).__name__}: {exc}",
                                     url=None, grid_id=grid_id, dates_ok=0, dates_total=len(dates))
            by_status["FAILED"] = by_status.get("FAILED", 0) + 1
            problems.append(f"{h['id']}: FAILED CRASH {type(exc).__name__}: {exc}")
            say(f"  [{n}/{len(runnable)}] {h['name']}: FAILED CRASH {type(exc).__name__}: {exc}")
            return True
        try:
            v = dry_run_hotel(run, workspace, stamp, grid_id) if args.dry_run else write_hotel(conn, run, workspace, stamp, grid_id)
        except Exception as exc:
            log.exception("write failed for %s", h["id"])
            if not args.dry_run:
                harvest_state.record(conn, SOURCE, h["id"], "FAILED", reason="WRITE_ERROR", detail=f"{type(exc).__name__}: {exc}",
                                     url=None, grid_id=grid_id, dates_ok=0, dates_total=len(dates))
            by_status["FAILED"] = by_status.get("FAILED", 0) + 1
            problems.append(f"{h['id']}: FAILED WRITE_ERROR {type(exc).__name__}: {exc}")
            say(f"  [{n}/{len(runnable)}] {h['name']}: FAILED WRITE_ERROR {exc}")
            return True
        totals["hotels"] += 1
        totals["rows"] += v["rows"]
        totals["calls"] += run.calls
        totals["bytes"] += run.bytes
        totals["seconds"] += run.seconds
        by_status[v["status"]] = by_status.get(v["status"], 0) + 1
        say(f"  [{n}/{len(runnable)}] {h['name']} ({h['code']}): {v['status']}" + (f" {v['reason']}" if v.get("reason") else "")
            + f" | rows {v['rows']}/{len(run.planned)} dates, {run.calls} calls, {run.seconds:.0f}s")
        log.info("%s %s status=%s reason=%s rows=%d written=%d superseded=%d rejected=%s calls=%d bytes=%d %.1fs url=%s",
                 h["id"], h["code"], v["status"], v.get("reason"), v["rows"], v["written"], v["superseded"], v["rejected"],
                 run.calls, run.bytes, run.seconds, v.get("url"))
        if v["status"] in ("PARTIAL", "FAILED", "INACTIVE") or v["rejected"]:
            problems.append(f"{h['id']} ({h['code']}): {v['status']} {v.get('reason')} | {(v.get('detail') or '')[:200]} | {v.get('url')}")
        return True

    # Sliding window: at most 2 x workers hotels fetched-but-unwritten at once, so a full run never holds the whole
    # catalog's raw responses (about 15 MB per hotel) in memory.
    workers = max(1, args.workers)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        queue = iter(runnable)
        pending: Dict[concurrent.futures.Future, dict] = {}

        def top_up():
            while len(pending) < workers * 2:
                h = next(queue, None)
                if h is None:
                    return
                pending[ex.submit(job, h)] = h

        top_up()
        n = 0
        while pending:
            done, _ = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done:
                h = pending.pop(fut)
                n += 1
                if not handle(n, h, fut):
                    for f in pending:
                        f.cancel()
                    pending.clear()
                    break
            top_up() if not aborted else None

    conn.close()
    for h in list(log.handlers):                      # release the log file (Windows keeps it locked otherwise)
        h.close()
        log.removeHandler(h)
    elapsed = time.time() - t_start
    say("-" * 78)
    say(f"Done in {elapsed:.0f}s: {totals['hotels']} hotels, {totals['rows']} rows, {totals['calls']} calls "
        f"({(totals['calls'] / totals['hotels']) if totals['hotels'] else 0:.1f}/hotel), "
        f"{totals['bytes'] / 1e6:.1f} MB raw | status {by_status}")
    for p in problems:
        say(f"  ! {p}")
    if args.dry_run:
        say(f"  dry run: evidence in {workspace}")
    return 1 if aborted else 0


if __name__ == "__main__":
    sys.exit(main())
