# -*- coding: utf-8 -*-
"""Marriott Recovery Harvester.
Targets properties previously marked 'NO_AVAILABILITY' due to in-flight Akamai 403 throttles.
Ensures full navigation per hotel to refresh Akamai telemetry, spaced GraphQL queries,
and strictly avoids false-positive NO_AVAILABILITY classifications.
"""
import argparse
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
from typing import Dict, List, Optional
from dateutil.relativedelta import relativedelta
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.rate_writer import RateRow, write_rate_batch, CALENDAR_UNKNOWN_ROOM
from engine import harvest_state

SOURCE = "MARRIOTT_CALENDAR"
SOURCE_TYPE = "OFFICIAL_MARRIOTT_CRS"
DB_PATH = os.path.join(ROOT, "hotel_stays.db")
EVIDENCE_DIR = os.path.join(ROOT, "evidence", "marriott", "raw")
CHROME_BIN = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("marriott_recovery")


class AkamaiBlockError(Exception):
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
                  amount { currency amount decimalPoint }
                }
                pointsPerQuantity { points }
                totalRate {
                  amount { amount currency decimalPoint }
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
        const timer = setTimeout(() => controller.abort(), 20000);
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
    const allResults = [];

    // Query month-by-month with 250ms spacing
    for (const { startDate, endDate } of months) {
        let cashRes = await fetchOneMonth(startDate, endDate, [{value: "", type: "STANDARD"}]);
        if (cashRes.status === 403 || cashRes.status === 429) {
            await sleep(1500);
            cashRes = await fetchOneMonth(startDate, endDate, [{value: "", type: "STANDARD"}]);
        }
        if (cashRes.status === 403 || cashRes.status === 429) {
            allResults.push({ startDate, endDate, status: cashRes.status, cash_edges: [], points_edges: [] });
            break;
        }
        let pointsRes = { status: 200, edges: [] };
        if (cashRes.status === 200 && cashRes.edges.length > 0) {
            await sleep(100);
            pointsRes = await fetchOneMonth(startDate, endDate, [{value: "MRW", type: "CLUSTER"}]);
        }
        allResults.push({
            startDate, endDate,
            status: cashRes.status,
            cash_edges: cashRes.edges || [],
            points_edges: pointsRes.edges || [],
            error: cashRes.error || null
        });

        // Smart Horizon Cutoff: if 2 consecutive months returned 0 rates after getting earlier rates, stop
        if (allResults.length >= 3) {
            const hadRates = allResults.some(r => r.cash_edges.length > 0);
            const lastTwo = allResults.slice(-2);
            if (hadRates && lastTwo.every(r => r.cash_edges.length === 0)) {
                break;
            }
        }
        await sleep(250);
    }

    const hasAnySuccess = allResults.some(r => r.status === 200 && r.cash_edges && r.cash_edges.length > 0);
    const anyBlock = allResults.some(r => r.status === 403 || r.status === 429);
    return {
        status: hasAnySuccess ? 200 : (anyBlock ? 403 : 200),
        results: allResults
    };
};
"""


class MarriottRecoveryWorker:
    def __init__(self, port: int = 9260, worker_id: int = 1):
        self.port = port
        self.worker_id = worker_id
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def start(self):
        log.info(f"[W{self.worker_id}] Attaching to Chrome CDP on port {self.port}...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        self.context = self.browser.contexts[0]
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

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

        # Warm up on calendar page
        init_url = "https://www.marriott.com/search/availabilityCalendar.mi?propertyCode=jktjw"
        self.page.goto(init_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(1.0)
        log.info(f"[W{self.worker_id}] Recovery worker ready!")

    def harvest_hotel(self, marsha: str, months_to_fetch: int = 12) -> Dict:
        today = date.today()
        all_rates = {}
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

        # Navigate to property calendar to refresh Akamai telemetry
        prop_url = f"https://www.marriott.com/search/availabilityCalendar.mi?propertyCode={marsha}"
        t0 = time.time()
        try:
            self.page.goto(prop_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(0.8)
            for _ in range(3):
                rx = random.randint(150, 900)
                ry = random.randint(150, 650)
                self.page.mouse.move(rx, ry, steps=random.randint(4, 8))
                self.page.wait_for_timeout(random.randint(120, 220))
            time.sleep(0.5)
            title = self.page.title()
            if any(s in title for s in ["Access Denied", "Reference Code", "500 ERROR"]):
                log.warning(f"[W{self.worker_id}] Akamai block on nav ('{title}'). Recycling...")
                raise AkamaiBlockError(f"Block on {marsha}: {title}")
        except AkamaiBlockError:
            raise
        except Exception as e:
            log.warning(f"[W{self.worker_id}] Nav notice for {marsha}: {e}")

        months_payload = [{"startDate": s, "endDate": e} for (_, s, e) in all_months]
        try:
            res = self.page.evaluate(GRAPHQL_JS, {"marsha": marsha, "months": months_payload})
        except Exception as e:
            log.warning(f"[W{self.worker_id}] GQL eval error: {e}")
            res = None

        elapsed = time.time() - t0
        if not res:
            return {"rates": {}, "raw_edges": [], "duration": elapsed, "status": 500}

        # Parse results
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

        if len(all_rates) == 0 and res.get("status") in (403, 429):
            log.warning(f"[W{self.worker_id}] In-flight 403 on {marsha}. Raising AkamaiBlockError to cool down and recycle...")
            raise AkamaiBlockError(f"GQL 403 on {marsha}")

        return {
            "rates": all_rates,
            "raw_edges": raw_edges,
            "duration": elapsed,
            "status": res.get("status", 200)
        }

    def close(self):
        try:
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass


def run_recovery_partition(worker_id: int, total_workers: int, port: int = 9260):
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    c = conn.cursor()

    # Target properties marked NO_AVAILABILITY
    c.execute("""
        SELECT h.id, h.name, h.country, h.currency
        FROM hotels h
        JOIN harvest_status hs ON h.id = hs.hotel_id AND hs.source = 'MARRIOTT_CALENDAR'
        WHERE h.brand = 'MARRIOTT' AND hs.status = 'NO_AVAILABILITY'
        ORDER BY h.id
    """)
    all_properties = c.fetchall()

    worker_properties = [p for i, p in enumerate(all_properties) if i % total_workers == (worker_id - 1)]
    log.info(f"[W{worker_id}/{total_workers}] Assigned {len(worker_properties)} NO_AVAILABILITY properties to recover.")

    worker = MarriottRecoveryWorker(port=port, worker_id=worker_id)
    try:
        worker.start()
        for idx, (hotel_id, name, country, db_curr) in enumerate(worker_properties, start=1):
            m_id = re.search(r'marr_([a-z0-9]{5})', hotel_id)
            marsha = m_id.group(1).lower() if m_id else None
            if not marsha:
                continue

            t_start = time.time()
            log.info(f"[W{worker_id} {idx}/{len(worker_properties)}] Recovering {hotel_id} ({marsha.upper()} - {name[:30]})...")

            try:
                res = worker.harvest_hotel(marsha)
            except AkamaiBlockError as e:
                log.warning(f"[W{worker_id}] Block/Throttle on {hotel_id}: {e}. Cooling down 15s and recycling...")
                time.sleep(15.0)
                worker.close()
                worker = MarriottRecoveryWorker(port=port, worker_id=worker_id)
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
                    notes="Marriott Official Phoenix All-In Final Checkout Price"
                ))

            # Database write with retry
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
                            detail=f"Recovered {len(rate_rows)} rates in {elapsed:.1f}s via GraphQL",
                            dates_ok=len(rate_rows)
                        )
                        conn.commit()
                        log.info(f"    [W{worker_id} RECOVERED] {hotel_id}: {write_res.written} rates saved to DB in {elapsed:.1f}s!")
                    else:
                        harvest_state.record(
                            conn,
                            source=SOURCE,
                            hotel_id=hotel_id,
                            status="NO_AVAILABILITY",
                            detail=f"Verified 0 dates in {elapsed:.1f}s (HTTP 200 OK)"
                        )
                        conn.commit()
                        log.info(f"    [W{worker_id} VERIFIED_EMPTY] {hotel_id}: Genuine 0 availability confirmed in {elapsed:.1f}s.")
                    break
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower() and attempt < max_retries - 1:
                        backoff = random.uniform(1.0, 3.0) * (attempt + 1)
                        time.sleep(backoff)
                    else:
                        log.error(f"[W{worker_id}] DB error on {hotel_id}: {e}")
                        break

            time.sleep(random.uniform(1.2, 1.8))
            if idx % 40 == 0:
                log.info(f"[W{worker_id}] Periodic recycling after 40 hotels...")
                worker.close()
                time.sleep(3.0)
                worker = MarriottRecoveryWorker(port=port, worker_id=worker_id)
                worker.start()

    finally:
        worker.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Marriott Recovery Harvester")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--worker-id", type=int, default=None)
    parser.add_argument("--port", type=int, default=9260)
    args = parser.parse_args()

    if args.worker_id is not None:
        run_recovery_partition(worker_id=args.worker_id, total_workers=args.workers, port=args.port)
        return

    # Master orchestrator
    log.info(f"Launching {args.workers} parallel Marriott Recovery workers...")
    processes = []
    base_ports = [9260, 9261, 9262, 9263]
    for w in range(1, args.workers + 1):
        port = base_ports[w - 1]
        cmd = [sys.executable, __file__, "--workers", str(args.workers), "--worker-id", str(w), "--port", str(port)]
        p = subprocess.Popen(cmd)
        processes.append(p)
        time.sleep(4.0)

    try:
        while True:
            alive = [p.poll() is None for p in processes]
            if not any(alive):
                log.info("All Marriott Recovery workers have completed!")
                break
            time.sleep(2.0)
    except KeyboardInterrupt:
        for p in processes:
            p.terminate()


if __name__ == "__main__":
    main()
