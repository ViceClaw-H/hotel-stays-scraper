"""Hilton Honors Flexible Calendar Multi-Worker Harvester.

Harvests full flexible calendar availability for Cash and Hilton Honors Reward Points
across all 9,761 physical Hilton properties worldwide into hotel_stays.db (Schema v2).

Architecture:
  - Direct CDP connection to Chrome instance
  - Official Hilton flexible date calendar:
      Cash:   /en/book/reservation/flexibledates/?ctyhocn={ctyhocn}&arrivalDate=...
      Points: /en/book/reservation/flexibledates/?ctyhocn={ctyhocn}&arrivalDate=...&redeemPts=true
  - Deterministic React selectors: button[data-testid^="arrival-YYYY-MM-DD"]
  - Rapid in-page month tab switching (~0.8s / month)
  - Full Schema v2 write via engine.rate_writer.write_rate_batch()
  - Raw evidence persisted with SHA-256 hash verification
"""
import argparse
import gzip
import hashlib
import json
import logging
import os
import random
import re
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from playwright.sync_api import sync_playwright

from engine import harvest_state
from engine.extractors.hilton import (
    EVIDENCE_FORMAT,
    EVIDENCE_VERSION,
    detect_currency_code,
    parse_evidence,
    parse_points_amount,
    parse_price_amount,
)
from engine.rate_writer import RateRow, write_rate_batch
from engine.schema import HARVEST_STATUS_DDL

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass

SOURCE = "HILTON_CALENDAR"
SOURCE_TYPE = "OFFICIAL_HILTON_CRS"
DB_PATH = os.path.join(ROOT, "hotel_stays.db")
EVIDENCE_DIR = os.path.join(ROOT, "evidence", "hilton", "raw")
COOKIE_FILE = os.path.join(ROOT, "crawlers", "pw_hilton_session", "hilton_cookies.json")

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

GRAPHQL_URL = "https://www.hilton.com/graphql/customer?appName=dx-res-ui&appVersion=dx-res-ui%3A1060844&operationName=hotel_shopAvailOptions_shopCalendarPropAvail&originalOpName=getShopAvailCalendar&bl=en&ctyhocn="

GRAPHQL_QUERY = """query hotel_shopAvailOptions_shopCalendarPropAvail($arrivalDate: String!, $ctyhocn: String!, $language: String!, $guestLocationCountry: String, $numAdults: Int!, $numChildren: Int!, $numRooms: Int!, $displayCurrency: String, $lengthOfStay: Int!, $guestId: BigInt, $specialRates: ShopSpecialRateInput, $rateCategoryTokens: [String], $ratePlanCodes: [String], $offerId: BigInt, $pnd: String, $childAges: [Int], $modifyingReservation: Boolean, $programAccountId: BigInt) {
  hotel(ctyhocn: $ctyhocn, language: $language) {
    ctyhocn
    shopAvailOptions(input: {offerId: $offerId, pnd: $pnd}) {
      maxNumChildren
      altCorporateAccount {
        name
      }
      contentOffer {
        name
      }
    }
    shopCalendarAvail(
      input: {guestLocationCountry: $guestLocationCountry, arrivalDate: $arrivalDate, displayCurrency: $displayCurrency, numAdults: $numAdults, numChildren: $numChildren, numRooms: $numRooms, lengthOfStay: $lengthOfStay, displayRateType: average, guestId: $guestId, specialRates: $specialRates, rateCategoryTokens: $rateCategoryTokens, ratePlanCodes: $ratePlanCodes, childAges: $childAges, modifyingReservation: $modifyingReservation, programAccountId: $programAccountId}
    ) {
      statusCode
      currencyCode
      notifications {
        subText
        subType
        title
        text
      }
      calendars {
        arrivalDate
        arrivalDateFmt
        departureDate
        departureDateFmt
        roomRate {
          dailyRmPointsRate
          dailyRmPointsRateFmt
          depositAmount
          depositAmountFmt
          numRoomsAvail
          rateAmount(strategy: ceiling)
          rateAmountFmt(decimal: 0, strategy: ceiling)
          rateChangeIndicator
          feeTransparencyIndicator
          cmaTotalPriceIndicator
          ratePlan {
            confidentialRates
            ratePlanName
            ratePlanDesc
            specialRateType
            serviceChargesAndTaxesIncluded
          }
          ratePlanCode
          roomTypeCode
        }
      }
    }
  }
}"""

BASE_VARIABLES = {
    "arrivalDate": "2026-10-01",
    "ctyhocn": "JKTDI",
    "guestLocationCountry": "GB",  # UK CMA Mandate: Native 100% All-In Final Checkout Total
    "lengthOfStay": 1,
    "numAdults": 1,
    "numChildren": 0,
    "numRooms": 1,
    "language": "en",
    "specialRates": {
        "hhonors": False,
        "aaa": False,
        "corporateId": None,
        "familyAndFriends": False,
        "senior": False,
        "governmentMilitary": False,
        "groupCode": None,
        "lta": False,
        "offerId": None,
        "owner": False,
        "ownerHGV": False,
        "pnd": None,
        "promoCode": None,
        "teamMember": False,
        "travelAgent": False,
        "specialOffer": False,
        "smb": False,
        "specialOfferName": None
    },
    "guestId": None,
    "offerId": None,
    "pnd": None,
    "displayCurrency": None,
    "modifyingReservation": False,
    "childAges": None
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("hilton")


class HiltonCDPSession:
    def __init__(self, port: int = 9275, visible: bool = False, worker_id: int = 1, profile_dir: Optional[str] = None):
        self.port = port
        self.visible = visible
        self.worker_id = worker_id
        if profile_dir:
            self.temp_dir = profile_dir
        else:
            self.temp_dir = os.path.join(ROOT, "crawlers", "pw_hilton_session", f"profile_w{worker_id}")
        os.makedirs(self.temp_dir, exist_ok=True)
        self.proc: Optional[subprocess.Popen] = None
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def start(self):
        log.info(f"Starting Chrome CDP worker on port {self.port} (visible={self.visible})...")
        if self.visible:
            x_pos = (self.worker_id - 1) * 960
            win_flags = [f"--window-position={x_pos},0", "--window-size=960,1040"]
        else:
            # Ghost Off-Screen Mode: rendered fully by Chrome window manager at off-screen coordinates (-3200,-3200).
            # Akamai sees an authentic headed browser window, but user desktop remains 100% clean and undisturbed.
            win_flags = [f"--window-position=-32000,{(self.worker_id-1)*800}", "--window-size=1366,768"]

        args = [
            CHROME_BIN,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.temp_dir}",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-component-update",
            "--disable-background-networking",
            *win_flags
        ]
        cflags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == "win32" else 0
        cflags = cflags | 0x08000000
        si = None
        if sys.platform == "win32" and not self.visible:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE: natively hides window & taskbar icon
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=si, creationflags=cflags)

        # Wait up to 15s for Chrome remote debugging port to open
        import urllib.request
        t_wait = time.time()
        ready = False
        while time.time() - t_wait < 15.0:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1.0) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.4)

        if not ready:
            log.warning(f"CDP port {self.port} did not respond within 15s, attempting connection anyway...")

        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        self.context = self.browser.contexts[0]
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

        # 1. Inject pre-warmed cookies if available
        self._inject_saved_cookies()

        # 2. Warm up front door at main entry point (hilton.com/en/) to establish authentic Akamai session
        log.info(f"[W{self.worker_id}] Establishing warm Akamai session at front door...")
        try:
            self.page.goto("https://www.hilton.com/en/", timeout=35000, wait_until="domcontentloaded")
            for _ in range(4):
                rx = random.randint(200, 800)
                ry = random.randint(200, 600)
                self.page.mouse.move(rx, ry, steps=5)
                self.page.mouse.wheel(0, random.choice([-50, 50, 100]))
                self.page.wait_for_timeout(random.randint(250, 450))
            title = self.page.title()
            if any(s in title for s in ["Access Denied", "Reference Code", "500 ERROR"]):
                log.warning(f"[W{self.worker_id}] Front door note: '{title}' (proceeding to query)")
            else:
                log.info(f"[W{self.worker_id}] Warm Akamai session ready on port {self.port} ('{title[:40]}').")
                self.save_current_cookies()
        except Exception as e:
            log.warning(f"[W{self.worker_id}] Front-door warm-up warning (proceeding): {e}")

    def _inject_saved_cookies(self):
        if not os.path.exists(COOKIE_FILE):
            log.info(f"[W{self.worker_id}] No pre-saved cookies at {COOKIE_FILE}, generating fresh...")
            return False
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            abck = next((c for c in saved if c["name"] == "_abck"), None)
            if abck and ("~0~" not in abck.get("value", "") and not abck.get("value", "").endswith("~0")):
                log.warning(f"[W{self.worker_id}] Saved cookies contain unverified/challenged token (~-1). Skipping injection to avoid 403 block.")
                return False
            pw_cookies = []
            for c in saved:
                item = {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", ".hilton.com"),
                    "path": c.get("path", "/"),
                }
                if "secure" in c:
                    item["secure"] = c["secure"]
                if "httpOnly" in c:
                    item["httpOnly"] = c["httpOnly"]
                pw_cookies.append(item)
            self.context.add_cookies(pw_cookies)
            log.info(f"[W{self.worker_id}] Successfully injected {len(pw_cookies)} warm cookies into Hilton context.")
            return True
        except Exception as e:
            log.warning(f"[W{self.worker_id}] Cookie injection warning: {e}")
            return False

    def save_current_cookies(self):
        try:
            cookies = self.context.cookies()
            os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)
            log.info(f"[W{self.worker_id}] Saved {len(cookies)} live cookies to {COOKIE_FILE}")
        except Exception as e:
            log.warning(f"[W{self.worker_id}] Failed to save cookies: {e}")

    def stop(self):
        try:
            if self.page:
                self.page.close()
        except Exception:
            pass
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None

    def prompt_session_refresh(self, ctyhocn: str = "jktdidi") -> bool:
        """Clear poisoned challenge cookies and acquire a fresh Akamai session token."""
        log.info(f"[W{self.worker_id}] Clearing cookies & refreshing Akamai session at front door...")
        try:
            self.context.clear_cookies()
        except Exception:
            pass
        test_url = "https://www.hilton.com/en/"
        try:
            self.page.goto(test_url, timeout=30000, wait_until="domcontentloaded")
            try:
                cookie_btn = self.page.query_selector("button#onetrust-accept-btn-handler, button:has-text('Accept All')")
                if cookie_btn and cookie_btn.is_visible():
                    cookie_btn.click()
                    self.page.wait_for_timeout(800)
            except Exception:
                pass
            for _ in range(4):
                rx = random.randint(150, 850)
                ry = random.randint(150, 650)
                self.page.mouse.move(rx, ry, steps=10)
                self.page.mouse.wheel(0, random.choice([-80, 80, 120]))
                self.page.wait_for_timeout(random.randint(250, 450))
            return True
        except Exception:
            return False

    def proactive_refresh(self, ctyhocn: str = "jktdidi") -> bool:
        """Proactively re-warm Akamai session before tokens expire."""
        log.info(f"[W{self.worker_id}] Proactive Akamai session refresh (renewing telemetri tokens)...")
        try:
            d_arr = (date.today() + relativedelta(days=14)).isoformat()
            d_dep = (date.today() + relativedelta(days=15)).isoformat()
            url = f"https://www.hilton.com/en/book/reservation/flexibledates/?ctyhocn={ctyhocn.upper()}&arrivalDate={d_arr}&departureDate={d_dep}&room1NumAdults=1"
            self.page.goto(url, timeout=35000, wait_until="domcontentloaded")
            try:
                self.page.wait_for_selector('button[data-testid^="arrival-"]', timeout=15000)
            except Exception:
                pass
            for _ in range(4):
                rx = random.randint(200, 800)
                ry = random.randint(200, 600)
                self.page.mouse.move(rx, ry, steps=10)
                self.page.mouse.wheel(0, random.choice([-60, 60]))
                self.page.wait_for_timeout(random.randint(200, 400))
            log.info(f"[W{self.worker_id}] Akamai session successfully refreshed.")
            return True
        except Exception as e:
            log.warning(f"[W{self.worker_id}] Proactive refresh warning: {e}")
            return False

    def fetch_hotel_calendar(

        self,
        ctyhocn: str,
        months_to_fetch: int = 3,
        default_currency: Optional[str] = None,
        fetch_points: bool = True
    ) -> Dict:
        """Harvest both Cash and Hilton Honors Points across requested months using in-browser GraphQL."""
        today_obj = date.today()
        today_iso = today_obj.isoformat()
        d_arr = (today_obj + relativedelta(days=14)).isoformat()
        d_dep = (today_obj + relativedelta(days=15)).isoformat()
        first_url = f"https://www.hilton.com/en/book/reservation/flexibledates/?ctyhocn={ctyhocn.upper()}&arrivalDate={d_arr}&departureDate={d_dep}&room1NumAdults=1"

        prop_code = ctyhocn[:5].upper()
        months_dates = [
            today_obj.strftime("%Y-%m-%d") if m == 0 else (today_obj.replace(day=1) + relativedelta(months=m)).strftime("%Y-%m-%d")
            for m in range(months_to_fetch)
        ]

        base_payload = {
            "query": GRAPHQL_QUERY,
            "operationName": "hotel_shopAvailOptions_shopCalendarPropAvail",
            "variables": BASE_VARIABLES
        }

        # Navigate to the specific hotel flexible dates page first to align Akamai telemetry & Origin
        hotel_url = f"https://www.hilton.com/en/book/reservation/flexibledates/?ctyhocn={ctyhocn.upper()}&arrivalDate={d_arr}&departureDate={d_dep}&room1NumAdults=1"
        try:
            self.page.goto(hotel_url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(1.0)
        except Exception as e:
            log.warning(f"    [W{self.worker_id}] Hotel page navigation warning: {e}")

        # Execute chunked GraphQL in-browser via evaluate
        res = {}
        blocked_status = None
        for attempt in range(3):
            res = self.page.evaluate("""async ([baseUrl, basePayload, monthDates, propCode, doPoints]) => {
                const url = baseUrl + propCode;
                const monthlyResults = {};
                
                async function fetchMonthDual(mDate) {
                    const out = { cash: [], points: [], currency: null, status: 200 };
                    
                    // Cash request
                    const pCash = JSON.parse(JSON.stringify(basePayload));
                    pCash.variables.ctyhocn = propCode;
                    pCash.variables.arrivalDate = mDate;
                    pCash.variables.specialRates.hhonors = false;
                    
                    // Points request (if enabled)
                    const pPts = JSON.parse(JSON.stringify(basePayload));
                    pPts.variables.ctyhocn = propCode;
                    pPts.variables.arrivalDate = mDate;
                    pPts.variables.specialRates.hhonors = true;
                    
                    try {
                        const rCash = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "Accept": "*/*", "x-requested-with": "XMLHttpRequest" }, body: JSON.stringify(pCash) });
                        out.status = rCash.status;
                        if (rCash.status === 200) {
                            const d1 = await rCash.json();
                            const cal1 = d1?.data?.hotel?.shopCalendarAvail;
                            if (cal1?.currencyCode) out.currency = cal1.currencyCode;
                            out.cash = cal1?.calendars || [];
                        }
                        if (doPoints && rCash.status === 200) {
                            await new Promise(r => setTimeout(r, 350));
                            const rPts = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "Accept": "*/*", "x-requested-with": "XMLHttpRequest" }, body: JSON.stringify(pPts) });
                            if (rPts.status === 200) {
                                const d2 = await rPts.json();
                                const cal2 = d2?.data?.hotel?.shopCalendarAvail;
                                out.points = cal2?.calendars || [];
                            }
                        }
                    } catch(e) {
                        out.error = e.toString();
                    }
                    return { month: mDate, data: out };
                }
                
                // Concurrency = 1 (smooth sequential 250ms throttle to prevent Akamai 403)
                const chunkSize = 1;
                let consecutiveEmpty = 0;
                for (let i = 0; i < monthDates.length; i += chunkSize) {
                    const chunk = monthDates.slice(i, i + chunkSize);
                    const chunkResults = await Promise.all(chunk.map(m => fetchMonthDual(m)));
                    for (const cr of chunkResults) {
                        monthlyResults[cr.month] = cr.data;
                        if (cr.data.cash.length === 0 && cr.data.points.length === 0) {
                            consecutiveEmpty++;
                        } else {
                            consecutiveEmpty = 0;
                        }
                    }
                    // Stop early if 2 consecutive months beyond month 4 are empty
                    if (i >= 3 && consecutiveEmpty >= 2) break;
                    if (i + chunkSize < monthDates.length) {
                        await new Promise(r => setTimeout(r, 900));
                    }
                }
                return monthlyResults;
            }""", [GRAPHQL_URL, base_payload, months_dates, prop_code, fetch_points])

            # Check for WAF/Akamai challenge
            blocked_status = next((m_res.get("status") for m_res in res.values() if m_res.get("status") in (403, 429)), None)
            if blocked_status:
                log.warning(f"    [W{self.worker_id}] Akamai challenge (HTTP {blocked_status}) on attempt {attempt+1}/3. Pausing 15s & re-warming session...")
                time.sleep(15.0)
                try:
                    self.page.goto(f"https://www.hilton.com/en/book/reservation/flexibledates/?ctyhocn={ctyhocn.upper()}&arrivalDate=2026-11-15&departureDate=2026-11-16&room1NumAdults=1", timeout=35000, wait_until="domcontentloaded")
                    self.page.wait_for_selector('button[data-testid^="arrival-"]', timeout=15000)
                    log.info(f"    [W{self.worker_id}] Session re-warmed successfully. Retrying GraphQL query...")
                except Exception as e:
                    log.warning(f"    [W{self.worker_id}] Session re-warm warning: {e}")
                continue
            
            # Clean response received
            break

        cash_by_date: Dict[str, Dict] = {}
        points_by_date: Dict[str, Optional[int]] = {}
        detected_curr = default_currency

        for m_date, m_res in res.items():
            if m_res.get("currency"):
                detected_curr = m_res["currency"]
            for c in m_res.get("cash", []):
                arr_date = c.get("arrivalDate")
                if arr_date and arr_date >= today_iso:
                    rr = c.get("roomRate", {})
                    rate_val = rr.get("rateAmount")
                    plan_name = rr.get("ratePlan", {}).get("ratePlanName", "Honors Discount")
                    cash_by_date[arr_date] = {
                        "amount": rate_val,
                        "currency": detected_curr,
                        "rate_plan": plan_name
                    }
            for p_item in m_res.get("points", []):
                arr_date = p_item.get("arrivalDate")
                if arr_date and arr_date >= today_iso:
                    rr = p_item.get("roomRate", {})
                    pts_val = rr.get("dailyRmPointsRate")
                    if pts_val:
                        points_by_date[arr_date] = pts_val

        all_dates = sorted(set(list(cash_by_date.keys()) + list(points_by_date.keys())))
        months_dict: Dict[str, List] = {}

        for s_date in all_dates:
            dt = datetime.strptime(s_date, "%Y-%m-%d")
            cap = dt.strftime("%B %Y")
            if cap not in months_dict:
                months_dict[cap] = []

            c_info = cash_by_date.get(s_date, {})
            c_val = c_info.get("amount") if detected_curr else None     # source names no currency -> no cash value (never a default)
            p_val = points_by_date.get(s_date)
            r_plan = c_info.get("rate_plan", "Honors Standard Reward")

            parts = []
            if c_val is not None:
                parts.append(f"{detected_curr} {c_val:.2f}")
            if p_val is not None:
                parts.append(f"{p_val:,} Pts")

            months_dict[cap].append({
                "stay_date": s_date,
                "cash_rate": float(c_val) if c_val is not None else None,
                "currency": detected_curr,
                "points_required": int(p_val) if p_val is not None else None,
                "available": (c_val is not None) or (p_val is not None),
                "is_low": False,
                "rate_plan": r_plan,
                "raw_text": " | ".join(parts) if parts else "N/A"
            })

        months_data = [{"caption": cap, "days": days} for cap, days in months_dict.items() if days]
        return {
            "currency": detected_curr,
            "months": months_data,
            "url": first_url,
            "blocked": bool(blocked_status) if not months_data else False
        }


def process_hotel(
    cdp: HiltonCDPSession,
    hotel: Dict,
    months: int = 6,
    dry_run: bool = False,
    fetch_points: bool = True
) -> Tuple[str, int, Optional[str]]:
    """Harvest, process evidence, and write to hotel_stays.db for a single Hilton property."""
    hotel_id = hotel["id"]
    ctyhocn = hotel["ctyhocn"]
    country = hotel.get("country", "")
    from engine.currency_source import is_iso
    default_curr = hotel.get("currency") if is_iso(hotel.get("currency")) else None   # catalog hint only; never a literal default

    t0 = time.time()
    result = cdp.fetch_hotel_calendar(
        ctyhocn=ctyhocn,
        months_to_fetch=months,
        default_currency=default_curr,
        fetch_points=fetch_points
    )
    elapsed = time.time() - t0

    months_data = result.get("months", [])
    total_dates = sum(len(m.get("days", [])) for m in months_data)

    if total_dates == 0:
        is_blocked = result.get("blocked", False)
        conn = sqlite3.connect(DB_PATH, timeout=45.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=45000")
        try:
            if is_blocked:
                log.warning(f"    [W{cdp.worker_id} !] Akamai challenge persistent for {ctyhocn.upper()} ({hotel['name'][:30]}) in {elapsed:.1f}s -> Recording as FAILED (AKAMAI_CHALLENGE)")
                harvest_state.record(
                    conn,
                    source=SOURCE,
                    hotel_id=hotel_id,
                    status="FAILED",
                    reason="AKAMAI_CHALLENGE",
                    detail="Akamai returned HTTP 403/429 across 3 retries",
                    url=result.get("url"),
                    retry_days=1
                )
            else:
                log.warning(f"    [W{cdp.worker_id} -] Zero bookable dates found for {ctyhocn.upper()} ({hotel['name'][:30]}) in {elapsed:.1f}s")
                harvest_state.record(
                    conn,
                    source=SOURCE,
                    hotel_id=hotel_id,
                    status="NO_AVAILABILITY",
                    reason="ZERO_DATES",
                    detail="No dates bookable in window (min stay / restricted / seasonal)",
                    url=result.get("url")
                )
        finally:
            conn.close()
        return hotel_id, 0, ("BLOCKED" if is_blocked else None)

    currency = result.get("currency") or default_curr
    if not currency:
        log.warning(f"    [W{cdp.worker_id} -] {hotel_id}: the source names no currency; cash values skipped (no default is assumed)")
    harvested_at = datetime.now()

    evidence_dict = {
        "format": EVIDENCE_FORMAT,
        "version": EVIDENCE_VERSION,
        "hotel_id": hotel_id,
        "ctyhocn": ctyhocn,
        "source_url": result.get("url", ""),
        "harvested_at": harvested_at.isoformat() + "Z",
        "currency": currency,
        "tax_inclusive": 1,
        "months": months_data,
    }

    raw_bytes = json.dumps(evidence_dict, ensure_ascii=False, indent=2).encode("utf-8")
    payload_hash = hashlib.sha256(raw_bytes).hexdigest()

    evidence_file = f"evidence/hilton/raw/hilton_{ctyhocn}_{date.today().strftime('%Y%m%d')}_{payload_hash[:8]}.json"

    rate_rows = parse_evidence(raw_bytes)

    final_rows = []
    for r in rate_rows:
        final_rows.append(RateRow(
            stay_date=r.stay_date,
            room_name=r.room_name,
            cash_rate=r.cash_rate,  # Native All-In Price from Hilton CRS (Zero Formula)
            currency=r.currency,
            points_required=r.points_required,
            notes="Hilton Official CRS All-In Final Checkout Price"
        ))
    rate_rows = final_rows

    cash_cnt = sum(1 for r in rate_rows if r.cash_rate is not None)
    pts_cnt = sum(1 for r in rate_rows if r.points_required is not None)

    log.info(
        f"    [W{cdp.worker_id} +] Extracted {len(rate_rows)} dates ({cash_cnt} cash, {pts_cnt} points, "
        f"curr: {currency}) in {elapsed:.1f}s"
    )

    if not dry_run and rate_rows:
        conn = sqlite3.connect(DB_PATH, timeout=45.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=45000")
        try:
            write_res = write_rate_batch(
                conn,
                hotel_id=hotel_id,
                source_type=SOURCE_TYPE,
                source_url=result.get("url") or "",
                rows=rate_rows,
                evidence_relpath=evidence_file,
                evidence_bytes=raw_bytes,
                evidence_grade="RAW",
                workspace_dir=ROOT,
                notes="Hilton flexible calendar all-in total cost & award points",
                allow_points_removal=True
            )
            harvest_state.record(
                conn,
                source=SOURCE,
                hotel_id=hotel_id,
                status="OK",
                dates_ok=write_res.written,
                dates_total=len(rate_rows),
                url=result.get("url")
            )
            log.info(f"    [W{cdp.worker_id} OK] DB updated: {write_res.written} rates written (SHA-256: {payload_hash[:12]}...)")
        except Exception as e:
            log.error(f"    [W{cdp.worker_id} ERR] DB write failed for {hotel_id}: {e}")
            return hotel_id, 0, "DB_WRITE_FAILED"
        finally:
            conn.close()

    return hotel_id, len(rate_rows), payload_hash


MAX_CONSECUTIVE_BLOCKED = 3


def harvest_hilton(
    ctyhocns: Optional[List[str]] = None,
    limit: Optional[int] = None,
    months: int = 6,
    dry_run: bool = False,
    visible: bool = False,
    port: int = 9275,
    fetch_points: bool = True,
    worker_id: int = 1,
    total_workers: int = 1,
    profile_dir: Optional[str] = None,
    recheck_unavailable: bool = False,
    force: bool = False,
):
    """Main execution controller for Hilton flexible calendar harvesting."""
    conn = sqlite3.connect(DB_PATH, timeout=45.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=45000")
    conn.execute(HARVEST_STATUS_DDL)
    conn.commit()
    c = conn.cursor()

    # Query unharvested properties
    if ctyhocns:
        placeholders = ",".join("?" for _ in ctyhocns)
        c.execute(f"""
            SELECT id, name, city, country, currency, official_url
            FROM hotels
            WHERE brand = 'HILTON' AND LOWER(REPLACE(id, 'hilt_', '')) IN ({placeholders})
            ORDER BY id
        """, [c_code.lower() for c_code in ctyhocns])
    elif force:
        c.execute("""
            SELECT h.id, h.name, h.city, h.country, h.currency, h.official_url
            FROM hotels h
            WHERE h.brand = 'HILTON'
            ORDER BY h.id
        """)
    elif recheck_unavailable:
        c.execute("""
            SELECT h.id, h.name, h.city, h.country, h.currency, h.official_url
            FROM hotels h
            JOIN harvest_status hs ON hs.hotel_id = h.id AND hs.source = 'HILTON_CALENDAR'
            WHERE h.brand = 'HILTON' AND hs.status = 'NO_AVAILABILITY'
            ORDER BY h.id
        """)
    else:
        c.execute("""
            SELECT h.id, h.name, h.city, h.country, h.currency, h.official_url
            FROM hotels h
            LEFT JOIN harvest_status hs ON hs.hotel_id = h.id AND hs.source = 'HILTON_CALENDAR'
            WHERE h.brand = 'HILTON' AND (hs.status IS NULL OR hs.status NOT IN ('OK', 'NO_AVAILABILITY'))
            ORDER BY h.id
        """)

    rows = c.fetchall()
    conn.close()

    all_hotels = []
    for r in rows:
        h_id = r[0]
        # Extract CTYHOCN from ID (e.g. hilt_jktdidi -> jktdidi)
        c_code = h_id.replace("hilt_", "").lower()
        all_hotels.append({
            "id": h_id,
            "ctyhocn": c_code,
            "name": r[1] or "",
            "city": r[2] or "",
            "country": r[3] or "",
            "currency": r[4],
            "url": r[5] or ""
        })

    # Partition across workers
    assigned = [h for i, h in enumerate(all_hotels) if i % total_workers == (worker_id - 1)]

    if limit:
        assigned = assigned[:limit]

    log.info(f"[Worker {worker_id}/{total_workers}] Target properties to process: {len(assigned)}")
    if not assigned:
        log.info(f"[Worker {worker_id}] No unharvested properties remaining in assigned partition.")
        return 0

    failed = 0            # v9f: blocked / crashed / not written -> run is PARTIAL (exit 2), never 'OK'
    consecutive_blocked = 0
    stopped_early = False

    cdp = HiltonCDPSession(port=port, visible=visible, worker_id=worker_id, profile_dir=profile_dir)
    try:
        cdp.start()
        # Stagger start to avoid initial burst
        time.sleep((worker_id - 1) * 2.0)

        for idx, hotel in enumerate(assigned, 1):
            if idx > 1 and idx % 15 == 0:
                log.info(f"[W{worker_id}] Proactive refresh milestone ({idx} hotels). Re-warming Akamai session before token decay...")
                cdp.proactive_refresh(hotel['ctyhocn'])
                time.sleep(random.uniform(2.5, 4.0))

            log.info(f"[W{worker_id} {idx}/{len(assigned)}] Processing {hotel['id']} ({hotel['ctyhocn'].upper()} - {hotel['name'][:35]})...")

            try:
                _hid, _n, marker = process_hotel(
                    cdp=cdp,
                    hotel=hotel,
                    months=months,
                    dry_run=dry_run,
                    fetch_points=fetch_points
                )
            except Exception as e:
                log.error(f"[W{worker_id}] Unexpected error processing {hotel['id']}: {e}")
                marker = "CRASH"
            if marker in ("BLOCKED", "DB_WRITE_FAILED", "CRASH"):
                failed += 1
            consecutive_blocked = consecutive_blocked + 1 if marker == "BLOCKED" else 0
            if consecutive_blocked >= MAX_CONSECUTIVE_BLOCKED:
                log.error(f"[W{worker_id}] Akamai blocked {consecutive_blocked} hotels in a row: stopping now "
                          f"(continuing only lengthens the block). Run GENERATE_HILTON_COOKIES.bat, wait, retry later.")
                stopped_early = True
                break
            time.sleep(random.uniform(3.0, 4.5))
    finally:
        cdp.stop()

    if failed or stopped_early:
        log.warning(f"[W{worker_id}] PARTIAL: {failed} of {len(assigned)} hotel(s) failed"
                    f"{' (stopped early on Akamai block)' if stopped_early else ''} -> exit code 2")
        return 2
    return 0


def spawn_workers(args, script: str) -> int:
    """--workers N: N child processes, each with isolated Chrome profile, port, and hotel partition."""
    passthrough, skip = [], False
    argv = sys.argv[1:]
    for a in argv:
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
    log.info(f"Spawning {args.workers} parallel Hilton workers with isolated Chrome profiles...")
    for i in range(args.workers):
        worker_cmd = [
            sys.executable, "-u", script, *passthrough,
            "--worker-id", str(i + 1),
            "--total-workers", str(args.workers),
            "--port", str(args.port + i)
        ]
        cflags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == "win32" else 0
        procs.append(subprocess.Popen(worker_cmd, creationflags=cflags))
        time.sleep(3.5)  # Stagger Chrome launches

    worst = 0
    try:
        while procs:
            for p in list(procs):
                ret = p.poll()
                if ret is not None:
                    procs.remove(p)
                    if ret == 42:
                        log.critical("A worker was blocked by WAF/Akamai (exit code 42). Halting all remaining workers immediately to avoid prolonging block!")
                        for other in procs:
                            try:
                                other.terminate()
                            except Exception:
                                pass
                        return 42
                    elif ret != 0:
                        log.warning(f"Worker process exited with code {ret}")
                        worst = max(worst, 2)
            time.sleep(0.5)
        return worst
    except KeyboardInterrupt:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        return 130


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hilton Honors Flexible Calendar Harvester (Schema v2)")
    parser.add_argument("--ctyhocn", type=str, help="Comma-separated 7-letter CTYHOCN codes (e.g. jktdidi,dpsuaci)")
    parser.add_argument("--limit", type=int, help="Limit number of properties to process")
    parser.add_argument("--months", type=int, default=3, help="Number of months to harvest per hotel (default: 3)")
    parser.add_argument("--visible", action="store_true", default=False, help="Run Chrome visibly on screen (default: False / Off-Screen Ghost)")
    parser.add_argument("--offscreen", dest="visible", action="store_false", help="Run Chrome in Ghost Off-Screen mode (-3200,-3200, invisible)")
    parser.add_argument("--workers", type=int, default=1, help="Number of concurrent workers (default: 1)")
    parser.add_argument("--worker-id", type=int, default=1)
    parser.add_argument("--total-workers", type=int, default=1)
    parser.add_argument("--port", type=int, default=9275, help="Base CDP remote debugging port (default: 9275)")
    parser.add_argument("--no-points", action="store_true", help="Skip harvesting award points")
    parser.add_argument("--recheck-unavailable", action="store_true", help="Re-harvest properties currently marked NO_AVAILABILITY")
    parser.add_argument("--force", action="store_true", help="Harvest every property, ignoring existing OK status")
    parser.add_argument("--dry-run", action="store_true", help="Perform discovery/API fetch without persisting to DB")


    args = parser.parse_args()
    if args.workers > 1:
        sys.exit(spawn_workers(args, os.path.abspath(__file__)))

    c_list = [c.strip().lower() for c in args.ctyhocn.split(",")] if args.ctyhocn else None

    sys.exit(harvest_hilton(
        ctyhocns=c_list,
        limit=args.limit,
        months=args.months,
        dry_run=args.dry_run,
        visible=args.visible,
        port=args.port,
        fetch_points=not args.no_points,
        worker_id=args.worker_id,
        total_workers=args.total_workers,
        recheck_unavailable=args.recheck_unavailable,
        force=args.force,
    ))
