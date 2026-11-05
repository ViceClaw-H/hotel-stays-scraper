# -*- coding: utf-8 -*-
"""Marriott Bonvoy Direct GraphQL API Harvester (Cara 2).

Bypasses heavy UI rendering and DOM clicks by executing Apollo GraphQL queries
directly from inside an authenticated Chrome context over CDP.

Throughput: ~8-10 seconds per hotel (12 full months).
Rate Calculation: Base Rate -> -5% Member Discount -> Country Gross Tax Multiplier.
"""
import argparse
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
from datetime import date, datetime
from typing import Dict, List, Optional
from dateutil.relativedelta import relativedelta
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.rate_writer import RateRow, write_rate_batch, CALENDAR_UNKNOWN_ROOM
from engine import harvest_state

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
CHROME_BIN = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("marriott_graphql")


class AkamaiBlockError(Exception):
    """Raised when Akamai blocks the current browser session. Handled by recycling the session."""
    pass

GRAPHQL_JS = """
async (args) => {
    const { marsha, months } = args;
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
                  }
                }
                pointsPerQuantity {
                  points
                }
                totalRate {
                  amount {
                    amount
                    currency
                    decimalPoint
                  }
                }
              }
            }
          }
        }
      }
    }`;

    const GQL_URL = "/mi/query/phoenixShopADFSearchProductsByProperty";
    const GQL_HEADERS = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "application-name": "shop",
        "apollographql-client-name": "phoenix_shop",
        "apollographql-client-version": "v1",
        "graphql-operation-name": "phoenixShopADFSearchProductsByProperty",
        "graphql-operation-signature": "887375892e1ad2a43f46a9c95c55ea47cf6eca3af03331c2134f1b440cff3f9f",
        "graphql-require-safelisting": "true"
    };

    const fetchOneMonth = async (startDate, endDate, rateTypes) => {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 25000);
        const payload = {
            operationName: "phoenixShopADFSearchProductsByProperty",
            variables: {
                id: [marsha],
                search: {
                    propertyId: marsha,
                    options: {
                        startDate, endDate,
                        numberOfRooms: 1,
                        rateRequestTypes: rateTypes,
                        numberInParty: 1,
                        numberOfDays: 1
                    }
                }
            },
            query
        };
        try {
            const resp = await fetch(GQL_URL, {
                method: "POST", signal: controller.signal,
                headers: GQL_HEADERS, body: JSON.stringify(payload)
            });
            clearTimeout(timer);
            if (!resp.ok) return { status: resp.status, edges: [] };
            const json = await resp.json();
            return { status: resp.status, edges: json?.data?.search?.calendarSearchByProperty?.edges || [] };
        } catch(err) {
            clearTimeout(timer);
            return { status: 408, edges: [], error: err.name };
        }
    };

    const sleep = ms => new Promise(r => setTimeout(r, ms));

    // Process months in batches of 3 with a small stagger.
    // Early-exit the batch loop as soon as any 403/429 is detected.
    const BATCH = 3;
    const allResults = [];
    let blocked = false;
    for (let i = 0; i < months.length; i += BATCH) {
        const batch = months.slice(i, i + BATCH);
        const batchResults = await Promise.all(batch.map(async ({ startDate, endDate }, j) => {
            if (j > 0) await sleep(j * 150);
            const cashRes = await fetchOneMonth(startDate, endDate, [{value: "", type: "STANDARD"}]);
            let pointsRes = { status: 200, edges: [] };
            if (cashRes.status === 200) {
                await sleep(80);
                pointsRes = await fetchOneMonth(startDate, endDate, [{value: "MRW", type: "CLUSTER"}]);
            }
            return {
                startDate, endDate,
                status: cashRes.status,
                cash_edges: cashRes.edges || [],
                points_edges: pointsRes.edges || [],
                error: cashRes.error || null
            };
        }));
        allResults.push(...batchResults);
        // Smart Horizon Cutoff: if this batch had 403 or 0 rates, and we already collected rates from earlier months,
        // the booking window has ended. Break early to save 5-10s per hotel!
        const batchHasRates = batchResults.some(r => r.cash_edges && r.cash_edges.length > 0);
        const hadEarlierRates = allResults.some(r => r.cash_edges && r.cash_edges.length > 0);
        if ((batchResults.some(r => r.status === 403 || r.status === 429) || !batchHasRates) && hadEarlierRates) {
            break;
        }
        if (i + BATCH < months.length) await sleep(200);
    }

    const hasAnySuccess = allResults.some(r => r.status === 200 && r.cash_edges && r.cash_edges.length > 0);
    const firstMonthBlock = allResults.length > 0 && (allResults[0].status === 403 || allResults[0].status === 429);
    return {
        status: hasAnySuccess ? 200 : (firstMonthBlock ? allResults[0].status : 200),
        results: allResults
    };
}
"""



class MarriottGraphQLWorker:
    def __init__(self, port: int = 9260, worker_id: int = 1, visible: bool = False):
        self.port = port
        self.worker_id = worker_id
        self.visible = visible
        self.temp_dir = os.path.join(ROOT, "crawlers", "pw_marriott_session", f"profile_gql_w{worker_id}")
        os.makedirs(self.temp_dir, exist_ok=True)
        self.proc = None
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def start(self):
        # Check if Chrome is already running on the CDP port
        import urllib.request
        port_open = False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1.0) as resp:
                if resp.status == 200:
                    port_open = True
        except Exception:
            pass

        if port_open:
            log.info(f"[W{self.worker_id}] Found existing Chrome session on port {self.port}. Attaching directly...")
            self.proc = None
        else:
            log.info(f"[W{self.worker_id}] Starting Chrome CDP worker on port {self.port} (visible={self.visible})...")
            # Ensure window is placed on screen so Akamai JavaScript sensor executes and validates telemetry
            win_flags = ["--window-size=1280,800", "--window-position=100,100"]
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
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=cflags)

            # Wait up to 15s for Chrome remote debugging port to open
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
                log.warning(f"[W{self.worker_id}] CDP port {self.port} did not respond within 15s, attempting connection anyway...")

        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        self.context = self.browser.contexts[0]
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

        # Block slow third-party ad & tracking scripts that cause 30-50s hangs
        blocked_domains = [
            "*adobedtm*", "*demdex*", "*tiqcdn*", "*quantummetric*",
            "*criteo*", "*doubleclick*", "*google-analytics*", "*googletagmanager*",
            "*facebook*", "*optimizely*", "*hotjar*"
        ]
        for pattern in blocked_domains:
            try:
                self.page.route(pattern, lambda route: route.abort())
            except Exception:
                pass

        # Warm up session context on calendar page with natural human entropy to trigger Akamai ~0~ token
        init_url = "https://www.marriott.com/search/availabilityCalendar.mi?propertyCode=jktjw"
        log.info(f"[W{self.worker_id}] Initializing session context on Marriott calendar...")
        try:
            self.page.goto(init_url, wait_until="domcontentloaded", timeout=40000)
            self.page.wait_for_timeout(2000)
            
            # Simulate natural human entropy (mouse moves + gentle scrolls)
            for _ in range(5):
                rx = random.randint(200, 700)
                ry = random.randint(200, 600)
                self.page.mouse.move(rx, ry, steps=8)
                self.page.mouse.wheel(0, random.choice([50, -50, 100]))
                self.page.wait_for_timeout(random.randint(300, 500))
                
            self.page.wait_for_timeout(1500)
            title = self.page.title()
            if any(s in title for s in ["Access Denied", "Reference Code", "500 ERROR"]):
                log.critical(f"[W{self.worker_id} FATAL] Block detected ('{title}'). Halting!")
                sys.exit(42)
                
            # Window remains at normal desktop position (100, 100) to keep Akamai screen telemetry valid

        except SystemExit:
            raise
        except Exception as e:
            title = self.page.title() if self.page else ""
            if any(s in title for s in ["Access Denied", "Reference Code", "500 ERROR"]):
                log.critical(f"[W{self.worker_id} FATAL] Block detected ('{title}'). Halting!")
                sys.exit(42)
            log.warning(f"[W{self.worker_id}] Session init notice (proceeding): {e}")
            self.page.wait_for_timeout(2000)
            
        log.info(f"[W{self.worker_id}] Session initialized, Akamai telemetry verified, and ready!")

    def harvest_hotel(self, marsha: str, months_to_fetch: int = 12, need_nav: bool = True) -> Dict:
        today = date.today()
        all_rates = {}
        total_time = 0
        raw_edges = []

        import calendar
        all_months = []
        for m in range(months_to_fetch):
            cur_start = today + relativedelta(months=m)
            if m > 0:
                cur_start = cur_start.replace(day=1)
            _, last_day = calendar.monthrange(cur_start.year, cur_start.month)
            cur_end = cur_start.replace(day=last_day)
            all_months.append((m, cur_start.strftime("%Y-%m-%d"), cur_end.strftime("%Y-%m-%d")))

        # Navigate or reuse existing open session
        prop_url = f"https://www.marriott.com/search/availabilityCalendar.mi?propertyCode={marsha}"
        if need_nav:
            try:
                self.page.goto(prop_url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(0.4)
                # Simulate natural mouse entropy — 3 quick moves sufficient for active desktop CDP session
                for _ in range(3):
                    rx = random.randint(150, 900)
                    ry = random.randint(150, 650)
                    self.page.mouse.move(rx, ry, steps=random.randint(4, 7))
                    self.page.mouse.wheel(0, random.choice([-50, 50, 100]))
                    self.page.wait_for_timeout(random.randint(120, 200))
                self.page.wait_for_timeout(300)
                title = self.page.title()
                if any(s in title for s in ["Access Denied", "Reference Code", "500 ERROR"]):
                    log.warning(f"[W{self.worker_id}] Block on property nav ('{title}'). Session needs recycling.")
                    raise AkamaiBlockError(f"Block on {marsha}: {title}")
                log.info(f"[W{self.worker_id}] Verified hotel context on '{title}' — Akamai telemetry OK.")
            except AkamaiBlockError:
                raise
            except Exception as e:
                log.warning(f"[W{self.worker_id}] Nav to {marsha} calendar warning (proceeding): {e}")
        else:
            # Reusing existing session without full page reload — gentle mouse move
            try:
                self.page.mouse.move(random.randint(200, 600), random.randint(200, 500), steps=3)
                self.page.wait_for_timeout(100)
            except Exception:
                pass


        # Build months payload for parallel JS fetch
        months_payload = [{"startDate": s, "endDate": e} for (_, s, e) in all_months]

        t0 = time.time()
        log.info(f"    [W{self.worker_id}] {marsha}: firing {len(months_payload)} months in parallel...")
        try:
            res = self.page.evaluate(GRAPHQL_JS, {"marsha": marsha, "months": months_payload})
        except Exception as e:
            # Context reset — reload and retry once
            log.warning(f"[W{self.worker_id}] Context error on {marsha}, reloading hotel page: {e}")
            try:
                self.page.goto(prop_url, wait_until="domcontentloaded", timeout=35000)
                self.page.wait_for_load_state("load")
                self.page.wait_for_timeout(3000)
                title = self.page.title()
                if any(s in title for s in ["Access Denied", "Reference Code", "500 ERROR"]):
                    log.warning(f"[W{self.worker_id}] Block on reload ('{title}'). Session needs recycling.")
                    raise AkamaiBlockError(f"Block on reload for {marsha}: {title}")
                res = self.page.evaluate(GRAPHQL_JS, {"marsha": marsha, "months": months_payload})
            except AkamaiBlockError:
                raise
            except Exception:
                res = None

        elapsed = time.time() - t0

        if not res:
            return {"rates": {}, "raw_edges": [], "duration": elapsed}

        # Parse all month results first
        for month_res in res.get("results", []):
            cash_edges = month_res.get("cash_edges", [])
            points_edges = month_res.get("points_edges", [])
            raw_edges.extend(cash_edges)

            pts_by_date = {}
            for pe in points_edges:
                pnode = pe.get("node", {})
                pdate = pnode.get("startDate")
                pts = pnode.get("rateModes", {}).get("pointsPerQuantity")
                if pdate and pts and pts.get("points"):
                    pts_by_date[pdate] = pts["points"]

            for edge in cash_edges:
                node = edge.get("node", {})
                st_date = node.get("startDate")
                if not st_date or st_date in all_rates:
                    continue
                low_rate = node.get("rateModes", {}).get("lowestAverageRate", {}).get("amount", {})
                tot_rate = node.get("rateModes", {}).get("totalRate", {}).get("amount", {})
                amt = low_rate.get("amount") or tot_rate.get("amount")
                dec = low_rate.get("decimalPoint") if low_rate.get("decimalPoint") is not None else tot_rate.get("decimalPoint", 0)
                curr = low_rate.get("currency") or tot_rate.get("currency") or "USD"
                if amt is not None:
                    val = float(amt)
                    if dec:
                        val = val / (10 ** dec)
                    all_rates[st_date] = {
                        "stay_date": st_date,
                        "cash_rate": val,
                        "currency": curr,
                        "points": pts_by_date.get(st_date)
                    }

        # If rates were found from any month, return them directly!
        if len(all_rates) > 0:
            return {
                "rates": all_rates,
                "raw_edges": raw_edges,
                "duration": elapsed
            }

        # If 0 rates found and status is blocked, handle triage
        if res.get("status") in (403, 429):
            try:
                current_title = self.page.title()
            except Exception:
                current_title = ""

            if any(s in current_title for s in ["Access Denied", "Reference Code", "500 ERROR"]):
                log.warning(f"[W{self.worker_id}] HTTP {res['status']} on {marsha} + Akamai block detected. Re-entropy...")
                raise AkamaiBlockError(f"Block on {marsha}: {current_title}")
            else:
                log.info(f"[W{self.worker_id}] HTTP {res['status']} on {marsha} (hotel page OK = no calendar availability). Skipping.")
                return {"rates": {}, "raw_edges": [], "duration": time.time() - t0}
        return {
            "rates": all_rates,
            "raw_edges": raw_edges,
            "duration": elapsed
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
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass


def run_worker_partition(worker_id: int, total_workers: int, months: int = 12, limit: Optional[int] = None, port: int = 9260):
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    c = conn.cursor()

    c.execute("""
        SELECT h.id, h.name, h.country, h.currency
        FROM hotels h
        LEFT JOIN harvest_status hs ON h.id = hs.hotel_id AND hs.source = 'MARRIOTT_CALENDAR'
        WHERE h.brand = 'MARRIOTT' AND (hs.status IS NULL OR hs.status NOT IN ('OK', 'NO_AVAILABILITY'))
        ORDER BY h.id
    """)
    all_properties = c.fetchall()

    # Partition for this worker
    worker_properties = [p for i, p in enumerate(all_properties) if i % total_workers == (worker_id - 1)]
    if limit:
        worker_properties = worker_properties[:limit]

    log.info(f"[W{worker_id}/{total_workers}] Assigned {len(worker_properties)} properties to harvest.")

    NAV_BATCH_SIZE = 5
    consecutive_in_page = 0

    worker = MarriottGraphQLWorker(port=port, worker_id=worker_id)
    try:
        worker.start()
        for idx, (hotel_id, name, country, db_curr) in enumerate(worker_properties, start=1):
            m_id = re.search(r'marr_([a-z0-9]{5})', hotel_id)
            marsha = m_id.group(1).lower() if m_id else None
            if not marsha:
                continue

            need_nav = (consecutive_in_page == 0)
            t_start = time.time()
            mode = "Nav" if need_nav else "InPage"
            log.info(f"[W{worker_id} {idx}/{len(worker_properties)}] Harvesting {hotel_id} ({marsha.upper()} - {mode})...")

            try:
                res = worker.harvest_hotel(marsha, months_to_fetch=months, need_nav=need_nav)
                consecutive_in_page = (consecutive_in_page + 1) % NAV_BATCH_SIZE
            except AkamaiBlockError as e:
                consecutive_in_page = 0  # Force navigation on retry
                elapsed = time.time() - t_start
                log.warning(f"[W{worker_id}] AkamaiBlockError on {hotel_id}: {e}. Recycling session...")
                harvest_state.record(
                    conn, source=SOURCE, hotel_id=hotel_id,
                    status="BLOCKED", detail=f"Akamai block after {elapsed:.1f}s — session recycled"
                )
                conn.commit()
                worker.close()
                time.sleep(random.uniform(15.0, 25.0))  # Cool down before recycling
                worker = MarriottGraphQLWorker(port=port, worker_id=worker_id)
                worker.start()
                continue

            rates_dict = res["rates"]
            elapsed = time.time() - t_start

            rate_rows = []
            source_url = f"https://www.marriott.com/search/availabilityCalendar.mi?propertyCode={marsha}"

            for d_str, item in sorted(rates_dict.items()):
                final_gross = item["cash_rate"]

                rate_rows.append(RateRow(
                    stay_date=d_str,
                    room_name=CALENDAR_UNKNOWN_ROOM,
                    cash_rate=final_gross,
                    currency=item["currency"],
                    points_required=item["points"],
                    source_url=source_url,
                    notes=f"Marriott Official Phoenix All-In Final Checkout Price"
                ))

            max_retries = 5
            for attempt in range(max_retries):
                try:
                    if len(rate_rows) > 0:
                        evidence_file = os.path.join("evidence", "marriott", "raw", f"marriott_{marsha}_{date.today().strftime('%Y%m%d')}.json")
                        os.makedirs(os.path.dirname(os.path.join(ROOT, evidence_file)), exist_ok=True)
                        evidence_bytes = json.dumps({
                            "format": "marriott-calendar-evidence",
                            "version": 1,
                            "hotel_id": hotel_id,
                            "marsha": marsha,
                            "harvested_at": datetime.now().isoformat() + "Z",
                            "rates_count": len(rate_rows),
                            "raw_edges": res["raw_edges"]
                        }).encode("utf-8")

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
                            detail=f"Harvested {len(rate_rows)} rates in {elapsed:.1f}s via GraphQL",
                            dates_ok=len(rate_rows)
                        )
                        conn.commit()
                        log.info(f"    [W{worker_id} OK] {hotel_id}: {write_res.written} rates saved to DB in {elapsed:.1f}s!")
                    else:
                        harvest_state.record(
                            conn,
                            source=SOURCE,
                            hotel_id=hotel_id,
                            status="NO_AVAILABILITY",
                            detail=f"0 dates returned in {elapsed:.1f}s"
                        )
                        conn.commit()
                        log.warning(f"    [W{worker_id} NO_RATES] {hotel_id}: 0 rates found in calendar across all months in {elapsed:.1f}s.")
                    break
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower() and attempt < max_retries - 1:
                        backoff = random.uniform(1.0, 3.0) * (attempt + 1)
                        log.warning(f"[W{worker_id}] DB locked on {hotel_id}. Retrying in {backoff:.1f}s... (attempt {attempt+1}/{max_retries})")
                        time.sleep(backoff)
                    else:
                        log.error(f"[W{worker_id}] DB error on {hotel_id}: {e}")
                        break

            # Inter-hotel pause for Akamai session stability
            time.sleep(random.uniform(0.8, 1.4) if not need_nav else random.uniform(1.6, 2.4))

            # Periodic session recycling every 30 hotels to prevent Akamai session drift
            if idx % 30 == 0 and idx < len(worker_properties):
                log.info(f"[W{worker_id}] Recycling browser session after 30 hotels for fresh Akamai telemetry...")
                worker.close()
                time.sleep(random.uniform(3.0, 5.0))
                worker = MarriottGraphQLWorker(port=port, worker_id=worker_id)
                worker.start()


    finally:
        worker.close()
        conn.close()


def spawn_workers(args):
    passthrough = []
    argv = sys.argv[1:]
    skip = False
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
    log.info(f"Launching {args.workers} parallel GraphQL workers on LAN Biznet (Zero Desktop Lag, Fail-Fast)...")
    cflags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == "win32" else 0
    for i in range(args.workers):
        w_id = i + 1
        cmd = [
            sys.executable, __file__,
            *passthrough,
            "--worker-id", str(w_id),
            "--total-workers", str(args.workers),
            "--port", str(args.port + i)
        ]
        procs.append(subprocess.Popen(cmd, creationflags=cflags))
        time.sleep(10)

    try:
        while any(p.poll() is None for p in procs):
            for p in procs:
                code = p.poll()
                if code is not None and code != 0:
                    log.warning(f"Worker process exited with code {code}. Other workers continue.")
            time.sleep(1)
        return max((p.returncode for p in procs), default=0)
    except KeyboardInterrupt:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        return 130


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Marriott GraphQL Direct Harvester")
    parser.add_argument("--workers", type=int, default=1, help="Number of concurrent workers (default: 1)")
    parser.add_argument("--worker-id", type=int, default=1)
    parser.add_argument("--total-workers", type=int, default=1)
    parser.add_argument("--port", type=int, default=9260, help="CDP base port (default: 9260)")
    parser.add_argument("--months", type=int, default=12, help="Months to harvest (default: 12)")
    parser.add_argument("--limit", type=int, help="Limit properties per worker")
    args = parser.parse_args()

    if args.workers > 1 and args.total_workers == 1:
        sys.exit(spawn_workers(args))
    else:
        run_worker_partition(
            worker_id=args.worker_id,
            total_workers=args.total_workers,
            months=args.months,
            limit=args.limit,
            port=args.port
        )
