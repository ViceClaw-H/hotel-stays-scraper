# -*- coding: utf-8 -*-
"""Marriott Bonvoy Flexible Calendar Harvester (Schema v2).

Harvests daily fully-taxed room rates and points from Marriott's official availability calendar:
    Cash:   https://www.marriott.com/search/availabilityCalendar.mi?propertyCode={marsha}&flexibleDateSearch=true&isSearch=true&costTab=total
    Points: https://www.marriott.com/search/availabilityCalendar.mi?propertyCode={marsha}&flexibleDateSearch=true&isSearch=true&useRewardsPoints=true

Features:
- Connects via Chrome CDP with persistent user session & Akamai cookie injection (_abck).
- Isolates Phoenix inventory session (PIM-SESSION-ID) between Cash and Points modes while preserving _abck.
- Waits deterministically for GraphQL/Phoenix rate grid population (wait_for_rates).
- Captures 100% all-in room cost ("1 Night Room Total", tax inclusive).
- Captures Marriott Bonvoy Award Points per night.
- Isolates rate amounts cleanly from DOM (.price-section), avoiding day-number concatenation.
- Saves verbatim evidence JSON under evidence/marriott/raw/.
- Validates cryptographic provenance via engine.rate_writer.write_rate_batch().
- Tracks per-hotel state in harvest_status (OK, PARTIAL, NO_AVAILABILITY).
- Notes restricted/minimum stay dates cleanly without inserting synthetic rates.
"""
import argparse
import atexit
import json
import logging
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from playwright.sync_api import sync_playwright

from engine import harvest_state
from engine.extractors.marriott import (
    EVIDENCE_FORMAT,
    EVIDENCE_VERSION,
    detect_currency_code,
    parse_evidence,
    parse_price_amount,
    parse_points_amount,
)
from engine.rate_writer import RateRow, write_rate_batch
from engine.schema import HARVEST_STATUS_DDL

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass

SOURCE = "MARRIOTT_CALENDAR"
SOURCE_TYPE = "OFFICIAL_MARRIOTT_CRS"
DB_PATH = os.path.join(ROOT, "hotel_stays.db")
EVIDENCE_DIR = os.path.join(ROOT, "evidence", "marriott", "raw")
COOKIE_FILE = os.path.join(ROOT, "crawlers", "pw_marriott_session", "marriott_cookies.json")

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("marriott")


def parse_day_picker_date(aria_label: str) -> Optional[str]:
    """Parse 'Thu Oct 01 2026' into '2026-10-01'."""
    if not aria_label:
        return None
    m = re.search(r"\b([A-Za-z]{3})\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})\b", aria_label)
    if not m:
        return None
    _, month_name, day_num, year_num = m.groups()
    try:
        dt = datetime.strptime(f"{month_name} {day_num} {year_num}", "%b %d %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def wait_for_rates(page, max_wait_sec: float = 12.0) -> int:
    """Poll until rate elements are populated by Marriott's GraphQL/Phoenix backend."""
    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        prices = [el.inner_text().strip() for el in page.query_selector_all(".price-section")]
        num_rates = sum(1 for pr in prices if any(c.isdigit() for c in pr) and "not available" not in pr.lower())
        if num_rates > 0:
            return num_rates
        page.wait_for_timeout(250)
    return 0


DUAL_GQL_JS = """
async (args) => {
    const { marsha, windows } = args;
    const query = `query phoenixShopADFSearchProductsByProperty($search: CalendarSearchByPropertyInput!, $id: [ID!]!) {
  search {
    calendarSearchByProperty(search: $search) {
      total
      edges {
        node {
          endDate
          startDate
          rateModes {
            lowestAverageRate {
              amount {
                currency
                amount
                decimalPoint
                __typename
              }
              __typename
            }
            pointsPerQuantity {
              points
              __typename
            }
            totalRate {
              amount {
                amount
                currency
                decimalPoint
                __typename
              }
              __typename
            }
            sourceOfRate
            __typename
          }
          __typename
        }
        __typename
      }
      __typename
    }
    __typename
  }
  propertiesByIds(ids: $id) {
    basicInformation {
      isAdultsOnly
      descriptions(
        filter: [RESORT_FEE_DESCRIPTION, DESTINATION_FEE_DESCRIPTION, SURCHARGE_ORDINANCE_COST_DESCRIPTION]
      ) {
        type {
          enumCode
          __typename
        }
        __typename
      }
      resort
      __typename
    }
    __typename
  }
}
`;

    const fetchGql = async (startDate, endDate, rateTypes) => {
        const payload = {
            operationName: "phoenixShopADFSearchProductsByProperty",
            variables: {
                id: [marsha.toLowerCase()],
                search: {
                    propertyId: marsha.toLowerCase(),
                    options: {
                        startDate: startDate,
                        endDate: endDate,
                        numberOfRooms: 1,
                        rateRequestTypes: rateTypes,
                        numberInParty: 1,
                        numberOfDays: 1
                    }
                }
            },
            query: query
        };

        const doFetch = async () => {
            return await fetch("/mi/query/phoenixShopADFSearchProductsByProperty", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "application-name": "shop",
                    "apollographql-client-name": "phoenix_shop",
                    "apollographql-client-version": "v1",
                    "graphql-operation-name": "phoenixShopADFSearchProductsByProperty",
                    "graphql-operation-signature": "887375892e1ad2a43f46a9c95c55ea47cf6eca3af03331c2134f1b440cff3f9f",
                    "graphql-require-safelisting": "true"
                },
                body: JSON.stringify(payload)
            });
        };

        let resp = await doFetch();
        if (resp.status === 429 || resp.status === 403) {
            await new Promise(r => setTimeout(r, 1200));
            resp = await doFetch();
        }

        if (resp.status !== 200) {
            return { errorStatus: resp.status };
        }
        try {
            return await resp.json();
        } catch (e) {
            return { errorStatus: 500, error: e.toString() };
        }
    };

    // Fetch both cash and points concurrently for a window with polite stagger
    const fetchWindow = async (w, delayMs) => {
        if (delayMs > 0) await new Promise(r => setTimeout(r, delayMs));
        const [c, p] = await Promise.all([
            fetchGql(w[0], w[1], [{value: "", type: "STANDARD"}]),
            fetchGql(w[0], w[1], [{value: "MRW", type: "CLUSTER"}])
        ]);
        return { startDate: w[0], endDate: w[1], cash: c, points: p };
    };

    // Process windows in batches of 4 with an 80ms stagger to prevent Akamai rate limits
    const results = [];
    const BATCH_SIZE = 4;
    for (let i = 0; i < windows.length; i += BATCH_SIZE) {
        const batch = windows.slice(i, i + BATCH_SIZE);
        const batchPromises = batch.map((w, idx) => fetchWindow(w, idx * 80));
        const batchResults = await Promise.all(batchPromises);
        results.push(...batchResults);
        if (i + BATCH_SIZE < windows.length) {
            await new Promise(r => setTimeout(r, 200));
        }
    }

    return results;
}
"""


class MarriottCDPSession:
    def __init__(self, port: int = 9235, visible: bool = False, worker_id: int = 1, profile_dir: Optional[str] = None, proxy: Optional[str] = None):
        self.port = port
        self.visible = visible
        self.worker_id = worker_id
        self.proxy = proxy
        if profile_dir:
            self.temp_dir = profile_dir
        else:
            self.temp_dir = os.path.join(ROOT, "crawlers", "pw_marriott_session", f"profile_w{worker_id}")
        os.makedirs(self.temp_dir, exist_ok=True)
        self.proc: Optional[subprocess.Popen] = None
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._session_initialized = False

    def start(self):
        proxy_info = f" (proxy={self.proxy})" if self.proxy else ""
        log.info(f"Starting Chrome CDP worker on port {self.port} (visible={self.visible}){proxy_info}...")
        offscreen = [] if self.visible else ["--window-position=-32000,-32000", "--window-size=1366,768"]
        args = [
            CHROME_BIN,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.temp_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            *offscreen
        ]
        if self.proxy:
            args.append(f"--proxy-server={self.proxy}")

        cflags = 0x08000000 if not self.visible else 0
        si = None
        if sys.platform == "win32" and not self.visible:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE: natively hides window & taskbar icon
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=si, creationflags=cflags)

        self.playwright = sync_playwright().start()
        for attempt in range(15):
            try:
                self.browser = self.playwright.chromium.connect_over_cdp(f"http://localhost:{self.port}")
                break
            except Exception:
                time.sleep(1.0)

        if not self.browser:
            raise RuntimeError(f"Could not connect to Chrome CDP on port {self.port} after 15s")

        self.context = self.browser.contexts[0]
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

        self._inject_saved_cookies()

        init_url = "https://www.marriott.com/search/availabilityCalendar.mi?propertyCode=jktjw&flexibleDateSearch=true&isSearch=true&costTab=total"
        try:
            log.info(f"[W{self.worker_id}] Pre-warming calendar session context...")
            self.page.goto(init_url, timeout=35000, wait_until="domcontentloaded")
            self.page.wait_for_timeout(2000)
            self._session_initialized = True
            log.info(f"[W{self.worker_id}] Calendar session context pre-warmed & ready.")
        except Exception as e:
            log.warning(f"[W{self.worker_id}] Initial page pre-warm notice: {e}")

    def set_window_visible(self, visible: bool):
        """Move Chrome window between foreground screen (100, 100) and offscreen (-32000, -32000)."""
        try:
            cdp = self.context.new_cdp_session(self.page)
            windows = cdp.send("Browser.getWindowForTarget")
            window_id = windows["windowId"]
            bounds = {
                "left": 100 if visible else -32000,
                "top": 100 if visible else -32000,
                "width": 1440,
                "height": 900,
                "windowState": "normal"
            }
            cdp.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": bounds})
            self.visible = visible
            log.info(f"Chrome window visibility toggled: {'FOREGROUND' if visible else 'OFFSCREEN'}")
        except Exception as e:
            log.warning(f"Could not change window visibility: {e}")

    def save_current_cookies(self):
        """Extract all current live cookies from Chrome context and persist to disk."""
        try:
            cookies = self.context.cookies()
            os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)
            log.info(f"Saved {len(cookies)} live cookies to {COOKIE_FILE}")
        except Exception as e:
            log.warning(f"Failed to save cookies: {e}")

    def prompt_session_refresh(self, marsha: str = "jktjw", timeout_sec: int = 30) -> bool:
        """Autonomously simulate human entropy & mouse movement to solve Akamai challenge without human intervention."""
        log.info(f"[W{self.worker_id}] Refreshing Akamai session autonomously...")
        test_url = f"https://www.marriott.com/search/availabilityCalendar.mi?propertyCode={marsha}&flexibleDateSearch=true&isSearch=true&costTab=total"
        try:
            self.page.goto(test_url, timeout=30000, wait_until="domcontentloaded")
            for _ in range(8):
                rx = random.randint(150, 850)
                ry = random.randint(150, 650)
                self.page.mouse.move(rx, ry, steps=10)
                self.page.mouse.wheel(0, random.choice([-80, 80, 150]))
                self.page.wait_for_timeout(random.randint(400, 700))
        except Exception:
            pass

        try:
            title = self.page.title()
            if "Access Denied" not in title and "expiredSession" not in self.page.url:
                day_picker = self.page.query_selector(".DayPicker-Month")
                if day_picker:
                    log.info("✅ Verified fresh Marriott session detected autonomously!")
                    self.save_current_cookies()
                    return True
        except Exception:
            pass

        log.warning(f"[W{self.worker_id}] Session challenge not cleared immediately; cooling down 15s...")
        time.sleep(15)
        return False

    def _inject_saved_cookies(self):
        target_cookie_file = COOKIE_FILE
        if self.proxy and "8001" in self.proxy:
            hp_cookie = os.path.join(ROOT, "crawlers", "pw_marriott_session", "marriott_cookies_hp.json")
            if os.path.exists(hp_cookie):
                target_cookie_file = hp_cookie

        if not os.path.exists(target_cookie_file):
            log.warning(f"Cookie file not found at {target_cookie_file}")
            return
        try:
            with open(target_cookie_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            pw_cookies = []
            for c in saved:
                item = {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", ".marriott.com"),
                    "path": c.get("path", "/"),
                }
                if "secure" in c:
                    item["secure"] = c["secure"]
                if "httpOnly" in c:
                    item["httpOnly"] = c["httpOnly"]
                pw_cookies.append(item)
            self.context.add_cookies(pw_cookies)
            log.info(f"Injected verified cookies into Chrome CDP context.")
        except Exception as e:
            log.warning(f"Failed to inject cookies: {e}")

    def _reset_session_inventory(self):
        """Clear session cookies & storage so mode switches (cash <-> points) are clean while preserving Akamai bot tokens."""
        try:
            keep_names = {'_abck', 'ak_bmsc', 'bm_sz', 'bm_s', 'bm_sc', 'bm_so', 'bm_lso'}
            all_c = self.context.cookies()
            kept = [c for c in all_c if c.get('name') in keep_names]
            self.context.clear_cookies()
            if kept:
                self.context.add_cookies(kept)
            if "marriott.com" in self.page.url:
                self.page.evaluate("() => { try { sessionStorage.clear(); localStorage.clear(); } catch(e){} }")
        except Exception:
            pass

    def fetch_hotel_calendar(
        self,
        marsha: str,
        months_to_fetch: int = 3,
        default_currency: Optional[str] = None,
        fetch_points: bool = True
    ) -> Dict:
        """Navigate to hotel availability calendar and collect months data for cash & points."""
        today_obj = date.today()
        today_iso = today_obj.isoformat()
        cal_url = f"https://www.marriott.com/search/availabilityCalendar.mi?propertyCode={marsha}&flexibleDateSearch=true&isSearch=true&costTab=total"

        # Construct monthly 34-day windows matching Marriott ADF query bounds
        windows = []
        cur_start = today_obj
        for _ in range(months_to_fetch):
            cur_end = cur_start + relativedelta(days=34)
            windows.append((cur_start.isoformat(), cur_end.isoformat()))
            cur_start = cur_end + relativedelta(days=1)

        # -------------------------------------------------------------
        # FAST PATH: In-Page Batched Concurrent Apollo GraphQL
        # -------------------------------------------------------------
        t_start = time.time()
        try:
            for nav_try in range(3):
                try:
                    self.page.goto(cal_url, timeout=30000, wait_until="domcontentloaded")
                    break
                except Exception as e:
                    if "net::ERR_" in str(e) and nav_try < 2:
                        log.warning(f"Network jitter ({e}), retrying navigation in 2s...")
                        time.sleep(2)
                        continue
                    raise

            if "expiredSession" in self.page.url or "Access Denied" in self.page.title():
                self.prompt_session_refresh(marsha=marsha)
                self.page.goto(cal_url, timeout=30000, wait_until="domcontentloaded")

            # Allow Akamai telemetry & sensor script 1.2s to compute dynamic tokens
            self.page.wait_for_timeout(1200)

            gql_results = None
            for eval_try in range(2):
                try:
                    gql_results = self.page.evaluate(DUAL_GQL_JS, {
                        "marsha": marsha,
                        "windows": windows
                    })
                    break
                except Exception as eval_err:
                    if "context was destroyed" in str(eval_err).lower() and eval_try == 0:
                        self.page.wait_for_timeout(1500)
                        continue
                    raise

            # Detect if session was invalidated or blocked (all windows returning 403 or 429)
            all_blocked = gql_results and all(
                (item.get("cash", {}).get("errorStatus") in (403, 429)) or 
                (item.get("points", {}).get("errorStatus") in (403, 429))
                for item in gql_results
            )
            if all_blocked:
                log.warning(f"    [W{self.worker_id}] Session challenge / rate limit detected for {marsha}. Refreshing session...")
                self.prompt_session_refresh(marsha=marsha)
                self.page.goto(cal_url, timeout=35000, wait_until="domcontentloaded")
                self.page.wait_for_timeout(2000)
                gql_results = self.page.evaluate(DUAL_GQL_JS, {
                    "marsha": marsha,
                    "windows": windows
                })
                still_blocked = gql_results and all(
                    (item.get("cash", {}).get("errorStatus") in (403, 429)) or
                    (item.get("points", {}).get("errorStatus") in (403, 429))
                    for item in gql_results
                )
                if still_blocked:
                    # v9f: v9e fell through to the DOM path here; the calendar then rendered with no prices
                    # and the hotel was labelled 'min stay / restricted'. A blocked answer is a failure.
                    statuses = sorted({str(item.get("cash", {}).get("errorStatus")) for item in gql_results})
                    log.warning(f"    [W{self.worker_id}] Still blocked after session refresh for {marsha} "
                                f"(HTTP {','.join(statuses)}): recording FAILED, not 'no availability'.")
                    return {
                        "error": "BLOCKED_AFTER_REFRESH",
                        "detail": f"Marriott calendar GraphQL answered HTTP {','.join(statuses)} in every window, "
                                  f"also after a session refresh; no price was read",
                        "months": [],
                        "url": cal_url,
                    }

            cash_map = {}
            pts_map = {}
            detected_curr = default_currency
            had_valid_response = False

            for item in (gql_results or []):
                c_res = item.get("cash", {})
                p_res = item.get("points", {})

                c_cal = c_res.get("data", {}).get("search", {}).get("calendarSearchByProperty")
                p_cal = p_res.get("data", {}).get("search", {}).get("calendarSearchByProperty")

                if c_cal is not None or p_cal is not None:
                    had_valid_response = True

                c_edges = c_cal.get("edges", []) if c_cal else []
                p_edges = p_cal.get("edges", []) if p_cal else []

                for e in c_edges:
                    node = e.get("node", {})
                    s_date = node.get("startDate")
                    if not s_date:
                        continue
                    tot_rate = node.get("rateModes", {}).get("totalRate", {}).get("amount", {})
                    low_rate = node.get("rateModes", {}).get("lowestAverageRate", {}).get("amount", {})
                    amt = tot_rate.get("amount") or low_rate.get("amount")
                    curr = tot_rate.get("currency") or low_rate.get("currency") or default_currency
                    if amt is not None and curr:      # no currency named by the source -> value skipped, never a default
                        dec = tot_rate.get("decimalPoint", 2)
                        cash_val = amt / (10 ** dec)
                        detected_curr = curr
                        cash_map[s_date] = (cash_val, curr)

                for e in p_edges:
                    node = e.get("node", {})
                    s_date = node.get("startDate")
                    if not s_date:
                        continue
                    p_info = node.get("rateModes", {}).get("pointsPerQuantity", {})
                    if p_info and p_info.get("points"):
                        pts_map[s_date] = p_info.get("points")

            elapsed_sec = time.time() - t_start
            if had_valid_response and (cash_map or pts_map):
                all_dates = sorted(set(list(cash_map.keys()) + list(pts_map.keys())))
                months_dict = {}
                for s_date in all_dates:
                    dt = datetime.strptime(s_date, "%Y-%m-%d")
                    cap = dt.strftime("%B %Y")
                    if cap not in months_dict:
                        months_dict[cap] = []

                    c_val, c_curr = cash_map.get(s_date, (None, None))
                    p_val = pts_map.get(s_date)
                    parts = []
                    if c_val is not None:
                        parts.append(f"Cash: {c_curr} {c_val:.2f}")
                    if p_val is not None:
                        parts.append(f"Pts: {p_val:,}")

                    months_dict[cap].append({
                        "stay_date": s_date,
                        "cash_rate": c_val,
                        "currency": c_curr,
                        "points_required": p_val,
                        "available": (c_val is not None) or (p_val is not None),
                        "is_low": False,
                        "raw_text": " | ".join(parts) if parts else "N/A"
                    })

                months_data = [{"caption": cap, "days": days} for cap, days in months_dict.items() if days]
                log.info(f"    [FAST GQL] Extracted {len(all_dates)} dates ({len(cash_map)} cash, {len(pts_map)} pts) in {elapsed_sec:.2f}s!")
                return {
                    "currency": detected_curr,
                    "months": months_data,
                    "url": cal_url
                }
            elif had_valid_response and not cash_map and not pts_map:
                log.info(f"    [FAST GQL] Property returned 0 dates across all {len(windows)} windows in {elapsed_sec:.2f}s.")
                return {
                    "currency": detected_curr,
                    "months": [],
                    "url": cal_url
                }
        except Exception as e:
            log.warning(f"Fast In-Page GraphQL failed for {marsha}: {e}, falling back to DOM click path...")

        # -------------------------------------------------------------
        # FALLBACK PATH: DOM Click Scraper
        # -------------------------------------------------------------
        # 1. HARVEST CASH
        log.info(f"    -> Loading Cash Calendar ({marsha.upper()})...")
        self._reset_session_inventory()
        cash_url = f"https://www.marriott.com/search/availabilityCalendar.mi?propertyCode={marsha}&flexibleDateSearch=true&isSearch=true&costTab=total&useRewardsPoints=false"
        try:
            self.page.goto(cash_url, timeout=40000, wait_until="domcontentloaded")
            try:
                self.page.wait_for_load_state("load", timeout=5000)
            except Exception:
                pass
        except Exception as e:
            log.warning(f"Failed to load calendar for {marsha}: {e}. Retrying with cookie injection...")
            self._inject_saved_cookies()
            self.page.goto(cash_url, timeout=40000, wait_until="domcontentloaded")

        if "expiredSession" in self.page.url or "Access Denied" in self.page.title():
            log.warning(f"Detected session/access issue on {marsha}. Requesting interactive session refresh...")
            success = self.prompt_session_refresh(marsha=marsha)
            if not success:
                return {
                    "error": "SESSION_EXPIRED",
                    "detail": "Failed to refresh session via interactive gate",
                    "months": []
                }
            self.page.goto(cash_url, timeout=40000, wait_until="domcontentloaded")

        try:
            self.page.wait_for_selector(".DayPicker-Month", timeout=20000)
            wait_for_rates(self.page, max_wait_sec=10.0)
        except Exception:
            body_text = self.page.inner_text("body")
            return {
                "error": "CALENDAR_NOT_RENDERED",
                "detail": body_text[:200],
                "months": []
            }

        # Detect currency from header
        header_text = ""
        try:
            tab_elem = self.page.query_selector(".cost-tab-header, .search-header, #cost_tab")
            if tab_elem:
                header_text = tab_elem.inner_text()
            else:
                header_text = self.page.inner_text("body")
        except Exception:
            pass

        detected_curr = detect_currency_code(header_text, default_currency=default_currency) or default_currency

        cash_by_date: Dict[str, Dict] = {}
        month_captions: List[str] = []

        for m_idx in range(months_to_fetch):
            wait_for_rates(self.page, max_wait_sec=8.0)
            try:
                caption_elem = self.page.query_selector(".DayPicker-Caption")
                caption = caption_elem.inner_text().strip() if caption_elem else f"Month {m_idx+1}"
            except Exception:
                caption = f"Month {m_idx+1}"
            if caption not in month_captions:
                month_captions.append(caption)

            cells = self.page.query_selector_all(".DayPicker-Day")
            for cell in cells:
                aria = cell.get_attribute("aria-label") or ""
                stay_date = parse_day_picker_date(aria)
                if not stay_date or stay_date < today_iso:
                    continue

                price_elem = cell.query_selector(".price-section")
                is_low = bool(cell.query_selector(".low-label-adf")) or "LOW" in cell.inner_text().upper()

                if not price_elem or "not available" in price_elem.inner_text().lower() or "not available" in cell.inner_text().lower():
                    cash_by_date[stay_date] = {
                        "amount": None,
                        "currency": None,
                        "available": False,
                        "is_low": False,
                        "raw_text": cell.inner_text().strip().replace("\n", " | "),
                        "caption": caption
                    }
                else:
                    raw_price = price_elem.inner_text().strip()
                    amount = parse_price_amount(raw_price)
                    cash_by_date[stay_date] = {
                        "amount": amount,
                        "currency": detected_curr if amount else None,
                        "available": (amount is not None),
                        "is_low": is_low,
                        "raw_text": raw_price,
                        "caption": caption
                    }

            if m_idx < months_to_fetch - 1:
                next_btn = self.page.query_selector(".DayPicker-NavButton--next")
                if next_btn:
                    try:
                        old_caption = caption
                        self.page.wait_for_timeout(random.randint(800, 1100))
                        next_btn.click()
                        self.page.wait_for_timeout(1000)
                        for _ in range(25):
                            c_elem = self.page.query_selector(".DayPicker-Caption")
                            new_c = c_elem.inner_text().strip() if c_elem else ""
                            if new_c and new_c != old_caption:
                                break
                            self.page.wait_for_timeout(200)
                        wait_for_rates(self.page, max_wait_sec=8.0)
                    except Exception:
                        break
                else:
                    break

        # 2. HARVEST POINTS
        points_by_date: Dict[str, Dict] = {}
        if fetch_points:
            pts_url = f"https://www.marriott.com/search/availabilityCalendar.mi?propertyCode={marsha}&flexibleDateSearch=true&isSearch=true&costTab=total&useRewardsPoints=true"
            log.info(f"    -> Loading Points Calendar ({marsha.upper()})...")
            try:
                self._reset_session_inventory()

                self.page.goto(pts_url, timeout=40000, wait_until="domcontentloaded")
                try:
                    self.page.wait_for_load_state("load", timeout=5000)
                except Exception:
                    pass
                if "expiredSession" in self.page.url or "Access Denied" in self.page.title():
                    log.warning(f"Detected session issue on points calendar for {marsha}. Requesting interactive session refresh...")
                    self.prompt_session_refresh(marsha=marsha)
                    self.page.goto(pts_url, timeout=40000, wait_until="domcontentloaded")
                self.page.wait_for_selector(".DayPicker-Month", timeout=20000)
                wait_for_rates(self.page, max_wait_sec=12.0)

                for m_idx in range(months_to_fetch):
                    wait_for_rates(self.page, max_wait_sec=8.0)
                    try:
                        caption_elem = self.page.query_selector(".DayPicker-Caption")
                        caption = caption_elem.inner_text().strip() if caption_elem else f"Month {m_idx+1}"
                    except Exception:
                        caption = f"Month {m_idx+1}"

                    cells = self.page.query_selector_all(".DayPicker-Day")
                    for cell in cells:
                        try:
                            aria = cell.get_attribute("aria-label") or ""
                        except Exception:
                            continue
                        stay_date = parse_day_picker_date(aria)
                        if not stay_date or stay_date < today_iso:
                            continue

                        try:
                            price_elem = cell.query_selector(".price-section")
                            is_low = bool(cell.query_selector(".low-label-adf")) or "LOW" in cell.inner_text().upper()

                            if not price_elem or "not available" in price_elem.inner_text().lower() or "not available" in cell.inner_text().lower():
                                points_by_date[stay_date] = {
                                    "points": None,
                                    "available": False,
                                    "is_low": False,
                                    "raw_text": cell.inner_text().strip().replace("\n", " | ")
                                }
                            else:
                                raw_pts = price_elem.inner_text().strip()
                                pts_num = parse_points_amount(raw_pts)
                                if not pts_num and not any(sym in raw_pts for sym in ["$", "€", "£", "¥", "Rp"]):
                                    parsed_f = parse_price_amount(raw_pts)
                                    if parsed_f and parsed_f >= 1000:
                                        pts_num = int(parsed_f)

                                points_by_date[stay_date] = {
                                    "points": pts_num,
                                    "available": (pts_num is not None),
                                    "is_low": is_low,
                                    "raw_text": raw_pts
                                }
                        except Exception:
                            pass

                    if m_idx < months_to_fetch - 1:
                        next_btn = self.page.query_selector(".DayPicker-NavButton--next")
                        if next_btn:
                            try:
                                old_caption = caption
                                self.page.wait_for_timeout(random.randint(800, 1100))
                                next_btn.click()
                                self.page.wait_for_timeout(1000)
                                for _ in range(25):
                                    c_elem = self.page.query_selector(".DayPicker-Caption")
                                    new_c = c_elem.inner_text().strip() if c_elem else ""
                                    if new_c and new_c != old_caption:
                                        break
                                    self.page.wait_for_timeout(200)
                                wait_for_rates(self.page, max_wait_sec=8.0)
                            except Exception:
                                break
                        else:
                            break
            except Exception as e:
                log.warning(f"Points calendar retrieval failed or partial for {marsha}: {e}")
            finally:
                self._reset_session_inventory()

        # 3. MERGE CASH & POINTS
        months_dict: Dict[str, List[Dict]] = {c: [] for c in month_captions}
        all_dates = sorted(set(list(cash_by_date.keys()) + list(points_by_date.keys())))

        for sdate in all_dates:
            c_info = cash_by_date.get(sdate, {})
            p_info = points_by_date.get(sdate, {})

            c_amt = c_info.get("amount")
            c_curr = c_info.get("currency") or (detected_curr if c_amt else None)
            p_pts = p_info.get("points")

            is_avail = (c_amt is not None) or (p_pts is not None)
            is_low = c_info.get("is_low", False) or p_info.get("is_low", False)

            parts = []
            if c_info.get("raw_text"):
                parts.append(f"Cash: {c_info.get('raw_text')}")
            if p_info.get("raw_text"):
                parts.append(f"Pts: {p_info.get('raw_text')}")
            comb_text = " | ".join(parts) if parts else "N/A"

            caption = c_info.get("caption") or (month_captions[0] if month_captions else "Unknown Month")
            if caption not in months_dict:
                months_dict[caption] = []

            months_dict[caption].append({
                "stay_date": sdate,
                "cash_rate": c_amt,
                "currency": c_curr,
                "points_required": p_pts,
                "available": is_avail,
                "is_low": is_low,
                "raw_text": comb_text
            })

        months_data = [{"caption": cap, "days": days} for cap, days in months_dict.items() if days]

        n_priced = sum(1 for m in months_data for d in m["days"]
                       if d.get("cash_rate") is not None or d.get("points_required") is not None)
        if n_priced == 0:
            # v9f: the DOM fallback cannot tell 'sold out' from 'prices never loaded' (blocked API, slow page).
            # Only the GraphQL path, which reads the server's answer, may conclude 'no availability'.
            return {
                "error": "DOM_FALLBACK_NO_PRICE_UNVERIFIED",
                "detail": f"DOM calendar fallback showed {sum(len(m['days']) for m in months_data)} day cell(s) "
                          f"and none with a price; cannot prove the hotel is unavailable",
                "months": [],
                "url": cash_url,
            }

        return {
            "currency": detected_curr,
            "months": months_data,
            "url": cash_url
        }

    def close(self):
        try:
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except Exception:
                pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)


MAX_CONSECUTIVE_BLOCKED = 3
BLOCK_CODES = ("BLOCKED_AFTER_REFRESH", "SESSION_EXPIRED", "ACCESS_DENIED", "DOM_FALLBACK_NO_PRICE_UNVERIFIED")


def harvest_marriott(
    marshas: Optional[List[str]] = None,
    limit: Optional[int] = None,
    months: int = 12,
    dry_run: bool = False,
    visible: bool = False,
    port: int = 9235,
    fetch_points: bool = True,
    worker_id: int = 1,
    total_workers: int = 1,
    proxy: Optional[str] = None,
    force: bool = False,
):
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.execute(HARVEST_STATUS_DDL)
    conn.commit()

    c = conn.cursor()
    if marshas:
        rows = c.execute(
            f"SELECT id, name, official_url, currency FROM hotels WHERE brand = 'MARRIOTT' AND ("
            + " OR ".join(f"id LIKE '%{m}%' OR official_url LIKE '%{m}%'" for m in marshas)
            + ")",
        ).fetchall()
    elif force:
        rows = c.execute("""
            SELECT h.id, h.name, h.official_url, h.currency
            FROM hotels h
            WHERE h.brand = 'MARRIOTT'
            ORDER BY h.id ASC
        """).fetchall()
    else:
        rows = c.execute("""
            SELECT h.id, h.name, h.official_url, h.currency
            FROM hotels h
            LEFT JOIN harvest_status hs ON hs.hotel_id = h.id AND hs.source = 'MARRIOTT_CALENDAR'
            WHERE h.brand = 'MARRIOTT' AND (hs.status IS NULL OR hs.status NOT IN ('OK'))
            ORDER BY h.id ASC
        """).fetchall()

    if limit and limit > 0:
        rows = rows[:limit]

    if total_workers > 1:
        rows = rows[worker_id - 1::total_workers]

    log.info(f"[Worker {worker_id}/{total_workers}] Target properties to process: {len(rows)}")
    if not rows:
        log.info(f"[Worker {worker_id}/{total_workers}] No properties due for harvesting.")
        conn.close()
        return 0

    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    session = MarriottCDPSession(port=port, visible=visible, worker_id=worker_id, proxy=proxy)
    session.start()
    atexit.register(session.close)

    total_rates_written = 0
    failed_hotels = 0          # v9f
    consecutive_blocked = 0    # v9f
    stopped_early = False      # v9f

    # Stagger worker entry by 2 seconds each so workers don't hit Marriott at the exact same moment
    if worker_id > 1:
        entry_delay = (worker_id - 1) * 2.0
        log.info(f"[W{worker_id}] Stagger delay: waiting {entry_delay:.1f}s before starting navigation...")
        time.sleep(entry_delay)

    try:
        for idx, (hotel_id, name, official_url, hotel_curr) in enumerate(rows, 1):
            if idx > 1:
                time.sleep(random.uniform(3.0, 4.5))

            m = re.search(r'/hotels/([a-z0-9]{5})-', official_url or "")
            marsha = m.group(1).lower() if m else None
            if not marsha:
                m_id = re.search(r'marr_([a-z0-9]{5})', hotel_id)
                marsha = m_id.group(1).lower() if m_id else None

            if not marsha:
                log.warning(f"[W{worker_id} {idx}/{len(rows)}] Skipping {hotel_id}: unable to determine 5-letter MARSHA code")
                continue

            log.info(f"[W{worker_id} {idx}/{len(rows)}] Processing {hotel_id} ({marsha.upper()} - {name[:35]})...")

            result = session.fetch_hotel_calendar(
                marsha,
                months_to_fetch=months,
                default_currency=hotel_curr if (isinstance(hotel_curr, str) and len(hotel_curr) == 3 and hotel_curr.isalpha() and hotel_curr.isupper()) else None,
                fetch_points=fetch_points
            )

            if "error" in result:
                err_code = result.get("error", "")
                err_detail = result.get("detail", "")
                log.warning(f"    [W{worker_id}] Calendar failed for {marsha}: {err_code}")
                harvest_state.record(
                    conn,
                    source=SOURCE,
                    hotel_id=hotel_id,
                    status="FAILED",
                    reason=err_code,
                    detail=err_detail,
                    url=result.get("url")
                )
                conn.commit()

                failed_hotels += 1
                consecutive_blocked = consecutive_blocked + 1 if err_code in BLOCK_CODES else 0
                if consecutive_blocked >= MAX_CONSECUTIVE_BLOCKED:
                    log.error(f"    [W{worker_id}] Marriott blocked {consecutive_blocked} hotels in a row: stopping now "
                              f"(continuing only lengthens the block). Wait several hours, then retry.")
                    stopped_early = True
                    break
                if err_code in ("SESSION_EXPIRED", "ACCESS_DENIED") or "Access Denied" in err_detail:
                    log.warning(f"    [W{worker_id}] Rate-limit or session challenge encountered. Cooling down 20s before next property...")
                    time.sleep(20)
                    session._inject_saved_cookies()
                continue
            consecutive_blocked = 0

            now_iso = datetime.now().isoformat(timespec="seconds") + "Z"
            evidence_dict = {
                "format": EVIDENCE_FORMAT,
                "version": EVIDENCE_VERSION,
                "hotel_id": hotel_id,
                "marsha": marsha,
                "source_url": result.get("url"),
                "harvested_at": now_iso,
                "currency": result.get("currency"),
                "tax_inclusive": 1,
                "months": result.get("months", [])
            }

            evidence_bytes = json.dumps(evidence_dict, ensure_ascii=False, indent=2).encode("utf-8")
            evidence_file = f"evidence/marriott/raw/marriott_{marsha}_{date.today().strftime('%Y%m%d')}.json"

            rate_rows = parse_evidence(evidence_bytes)

            final_rows = []
            for r in rate_rows:
                final_rows.append(RateRow(
                    stay_date=r.stay_date,
                    room_name=r.room_name,
                    cash_rate=r.cash_rate,  # Native All-In Total Rate from Marriott CRS (Zero Formula)
                    currency=r.currency,
                    points_required=r.points_required,
                    notes="Marriott Official Phoenix All-In Final Checkout Price"
                ))
            rate_rows = final_rows

            pts_count = sum(1 for r in rate_rows if r.points_required)
            cash_count = sum(1 for r in rate_rows if r.cash_rate)
            log.info(f"    [W{worker_id} +] Extracted {len(rate_rows)} bookable dates ({cash_count} cash, {pts_count} points, curr: {result.get('currency')})")

            if dry_run:
                log.info(f"    [W{worker_id} DRY-RUN] Would write {len(rate_rows)} rates to {evidence_file}")
                continue

            if not rate_rows:
                log.info(f"    [W{worker_id} *] Property has 0 bookable dates in window (min stay / restricted).")
                harvest_state.record(
                    conn,
                    source=SOURCE,
                    hotel_id=hotel_id,
                    status="NO_AVAILABILITY",
                    reason="MIN_STAY_OR_RESTRICTED",
                    detail="All dates in window returned unavailable / not open for check-in",
                    url=result.get("url"),
                    dates_ok=0,
                    dates_total=sum(len(m.get("days", [])) for m in result.get("months", []))
                )
                conn.commit()
                continue

            write_res = None
            for db_try in range(5):
                try:
                    write_res = write_rate_batch(
                        conn,
                        hotel_id=hotel_id,
                        source_type=SOURCE_TYPE,
                        source_url=result.get("url") or "",
                        rows=rate_rows,
                        evidence_relpath=evidence_file,
                        evidence_bytes=evidence_bytes,
                        evidence_grade="RAW",
                        workspace_dir=ROOT,
                        notes="Marriott flexible calendar all-in total cost & award points",
                        allow_points_removal=True
                    )
                    break
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower() and db_try < 4:
                        log.warning(f"    [W{worker_id} DB LOCKED] Retrying DB write in 1-2s (attempt {db_try+1}/5)...")
                        time.sleep(random.uniform(1.0, 2.5))
                        continue
                    raise

            if not write_res:
                log.warning(f"    [W{worker_id} !] Failed to write rates after retries.")
                failed_hotels += 1
                continue

            total_rates_written += write_res.written
            horizon_last = max(r.stay_date for r in rate_rows) if rate_rows else None
            evidence_hash = write_res.evidence_sha256[:12] if write_res.evidence_sha256 else "N/A"
            if write_res.rejected:
                log.warning(f"    [W{worker_id} !] Rejected {len(write_res.rejected)} rows: {write_res.rejected[:3]}")

            harvest_state.record(
                conn,
                source=SOURCE,
                hotel_id=hotel_id,
                status="OK" if write_res.written > 0 else "PARTIAL",
                url=result.get("url"),
                dates_ok=write_res.written,
                dates_total=sum(len(m.get("days", [])) for m in result.get("months", [])),
                horizon_last_ok=horizon_last
            )
            conn.commit()
            log.info(f"    [W{worker_id} OK] DB updated: {write_res.written} rates written (SHA-256: {evidence_hash}...)")

    finally:
        session.close()
        conn.close()

    log.info(f"[W{worker_id}] Harvesting completed. Total rates written: {total_rates_written}")
    if failed_hotels or stopped_early:
        log.warning(f"[W{worker_id}] PARTIAL: {failed_hotels} hotel(s) failed"
                    f"{' (stopped early on block)' if stopped_early else ''} -> exit code 2")
        return 2
    return 0


def spawn_workers(args, script: str) -> int:
    """--workers N: N child processes, each with its own Chrome profile, port, and hotel partition."""
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
    log.info(f"Spawning {args.workers} parallel Marriott workers with isolated Chrome profiles...")
    for i in range(args.workers):
        worker_cmd = [sys.executable, script, *passthrough, "--worker-id", str(i + 1), "--total-workers", str(args.workers),
                      "--port", str(args.port + i)]
        if getattr(args, "dual_ip", False):   # v9f: no longer forced for 8 workers (needs local proxies on 8001/8002)
            # Workers 1-4 via LAN (Port 8002), Workers 5-8 via HP (Port 8001)
            p_url = "http://127.0.0.1:8002" if i < 4 else "http://127.0.0.1:8001"
            worker_cmd.extend(["--proxy", p_url])
        procs.append(subprocess.Popen(worker_cmd))
        time.sleep(3)                                     # Stagger Chrome launches to prevent CPU spikes
    try:
        return max(p.wait() for p in procs)
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()
        return 130


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Marriott Bonvoy Flexible Calendar Harvester (Schema v2)")
    parser.add_argument("--marsha", type=str, help="Comma-separated 5-letter MARSHA codes (e.g. jktjw,dpswh)")
    parser.add_argument("--limit", type=int, help="Limit number of properties to process")
    parser.add_argument("--months", type=int, default=12, help="Number of months to harvest per hotel (default: 12)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse without writing to database")
    parser.add_argument("--visible", action="store_true", help="Run Chrome visibly for inspection (default is headless)")
    parser.add_argument("--workers", type=int, default=1, help="Number of concurrent workers (default: 1)")
    parser.add_argument("--worker-id", type=int, default=1)
    parser.add_argument("--total-workers", type=int, default=1)
    parser.add_argument("--port", type=int, default=9235, help="Base CDP remote debugging port (default: 9235)")
    parser.add_argument("--no-points", action="store_true", help="Skip harvesting award points")
    parser.add_argument("--proxy", type=str, default=None, help="Proxy URL (e.g. http://127.0.0.1:8001)")
    parser.add_argument("--dual-ip", action="store_true", help="Enable 2-IP load balancing across LAN and HP")
    parser.add_argument("--force", action="store_true", help="Harvest every property, ignoring existing OK status")

    args = parser.parse_args()
    if args.workers > 1:
        sys.exit(spawn_workers(args, os.path.abspath(__file__)))

    m_list = [m.strip().lower() for m in args.marsha.split(",")] if args.marsha else None

    sys.exit(harvest_marriott(
        marshas=m_list,
        limit=args.limit,
        months=args.months,
        dry_run=args.dry_run,
        visible=args.visible,
        port=args.port,
        fetch_points=not args.no_points,
        worker_id=args.worker_id,
        total_workers=args.total_workers,
        proxy=args.proxy,
        force=args.force,
    ))
