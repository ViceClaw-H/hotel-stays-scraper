# -*- coding: utf-8 -*-
"""Hyatt Mr & Mrs Smith Fast Harvester with Smart Horizon Cutoff.
Adapted from Marriott Recovery (In-Page CDP) & Accor Fast Harvester (Smart Horizon Cutoff).
Targets all unharvested hyatt_mXXXX boutique properties.
"""
import argparse
import atexit
import json
import logging
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dateutil.relativedelta import relativedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass

from engine.extractors import hyatt as hx
from engine.rate_writer import write_rate_batch
from engine import harvest_state

SOURCE = "HYATT_AWARD"
SOURCE_TYPE = "OFFICIAL_HYATT_AVAIL_DAYS"
DB_PATH = os.path.join(ROOT, "hotel_stays.db")
BASE = "https://www.hyatt.com"
CHROME_BIN = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
KASADA_WARMUP_SECONDS = 8.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("hyatt_smith")

_LIVE_PROCS = []

def _cleanup_procs():
    for proc in _LIVE_PROCS:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except:
            pass

atexit.register(_cleanup_procs)


class SmithCDPSession:
    def __init__(self, port: int = 9222, visible: bool = False):
        self.port = port
        self.visible = visible
        self.temp_dir = None
        self.proc = None
        self.playwright = None
        self.browser = None
        self.page = None
        self.requests = 0

    def start(self):
        from playwright.sync_api import sync_playwright
        self.temp_dir = tempfile.mkdtemp(prefix=f"hyatt_smith_p{self.port}_")
        offscreen = [] if self.visible else ["--window-position=-32000,-32000"]
        cmd = [
            CHROME_BIN, f"--remote-debugging-port={self.port}", f"--user-data-dir={self.temp_dir}",
            "--no-first-run", "--no-default-browser-check", "--disable-blink-features=AutomationControlled",
            "--window-size=1440,900", *offscreen, BASE
        ]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _LIVE_PROCS.append(self.proc)
        
        # Wait for CDP endpoint
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1.0):
                    break
            except:
                time.sleep(0.5)
        else:
            raise RuntimeError(f"Chrome port {self.port} failed to open within 15s")

        # Kasada warmup
        time.sleep(KASADA_WARMUP_SECONDS)
        
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        ctx = self.browser.contexts[0]
        self.page = ctx.pages[0] if ctx.pages else ctx.new_page()
        
        # Verify page is on hyatt
        if "hyatt.com" not in self.page.url:
            self.page.goto(BASE, wait_until="domcontentloaded", timeout=45000)
            time.sleep(2.0)
            
        log.info(f"Worker on port {self.port} ready and warmed up.")

    def fetch_window(self, spirit_code: str, start_date: str, end_date: str) -> dict:
        url = f"{BASE}/explore-hotels/service/avail/days?spiritCode={spirit_code}&startDate={start_date}&endDate={end_date}"
        js_code = """async (url) => {
            try {
                const t0 = performance.now();
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 18000);
                const res = await fetch(url, { signal: controller.signal, headers: { 'Accept': 'application/json' } });
                clearTimeout(timeoutId);
                const text = await res.text();
                return {
                    status: res.status,
                    text: text,
                    ms: Math.round(performance.now() - t0)
                };
            } catch(e) {
                return { status: 500, error: e.message };
            }
        }"""
        for attempt in range(3):
            try:
                self.requests += 1
                return self.page.evaluate(js_code, url)
            except Exception as e:
                if any(k in str(e).lower() for k in ["context was destroyed", "navigation", "frame was detached"]):
                    time.sleep(2.0)
                    continue
                return {"status": 500, "error": str(e)}
        return {"status": 500, "error": "max attempts exceeded"}

    def close(self):
        for obj, m in ((self.browser, "close"), (self.playwright, "stop")):
            try:
                if obj: getattr(obj, m)()
            except: pass
        if self.proc:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except: pass
            if self.proc in _LIVE_PROCS:
                _LIVE_PROCS.remove(self.proc)
            self.proc = None
        if self.temp_dir:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.temp_dir = None


def generate_monthly_windows(today: date, months: int = 12) -> List[Tuple[date, date]]:
    windows = []
    # Month 1: from today to end of current month
    m1_first = today
    m1_next = (today.replace(day=1) + relativedelta(months=1))
    m1_end = m1_next - timedelta(days=1)
    windows.append((m1_first, m1_end))
    
    for m in range(1, months):
        start = today.replace(day=1) + relativedelta(months=m)
        nxt = start + relativedelta(months=1)
        end = nxt - timedelta(days=1)
        windows.append((start, end))
    return windows


def get_smith_todo(conn, worker_id: int = 1, total_workers: int = 1, limit: Optional[int] = None) -> List[dict]:
    c = conn.cursor()
    c.execute("""
    SELECT h.id, h.name, h.city, h.country
    FROM hotels h
    LEFT JOIN (
        SELECT rc.hotel_id, COUNT(rr.id) as rate_count
        FROM room_categories rc
        JOIN rate_records rr ON rc.id = rr.room_id
        GROUP BY rc.hotel_id
    ) r ON h.id = r.hotel_id
    LEFT JOIN harvest_status hs ON h.id = hs.hotel_id AND hs.source = 'HYATT_AWARD'
    WHERE h.id LIKE 'hyatt_m%' 
      AND (r.rate_count IS NULL OR r.rate_count = 0)
      AND (hs.status IS NULL OR hs.status NOT IN ('OK', 'NO_AVAILABILITY'))
    ORDER BY h.id
    """)
    rows = c.fetchall()
    
    # Sharding
    sharded = [r for i, r in enumerate(rows) if (i % total_workers) == (worker_id - 1)]
    if limit:
        sharded = sharded[:limit]
        
    todo = []
    for r in sharded:
        spirit = r[0].replace("hyatt_", "")
        todo.append({
            "hotel_id": r[0],
            "spirit_code": spirit,
            "name": r[1],
            "city": r[2],
            "country": r[3]
        })
    return todo


def harvest_smith_hotel(session: SmithCDPSession, conn, hotel: dict, today: date, windows: List[Tuple[date, date]]) -> dict:
    spirit = hotel["spirit_code"]
    hid = hotel["hotel_id"]
    
    consecutive_empty = 0
    all_rows = []
    all_evidence = []
    dates_ok = 0
    
    for w_start, w_end in windows:
        # Smart Horizon Cutoff: if 2 consecutive future months have 0 availability, cutoff remainder
        if consecutive_empty >= 2:
            break
            
        res = session.fetch_window(spirit, w_start.isoformat(), w_end.isoformat())
        st = res.get("status")
        txt = res.get("text", "")
        
        if st == 429:
            log.warning(f"[{spirit}] HTTP 429 Kasada block! Backing off 20s...")
            time.sleep(20.0)
            res = session.fetch_window(spirit, w_start.isoformat(), w_end.isoformat())
            st = res.get("status")
            txt = res.get("text", "")
            
        if st != 200 or not txt:
            consecutive_empty += 1
            time.sleep(0.5)
            continue
            
        raw = txt.encode("utf-8")
        rows = hx.parse_award_evidence(raw)
        
        if rows:
            consecutive_empty = 0
            dates_ok += len(rows)
            all_rows.extend(rows)
            # Save raw evidence
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            rel = f"evidence/hyatt/avail_days/hyatt_{spirit}_{w_start}_{w_end}_{stamp}.json"
            wr = write_rate_batch(conn, hotel_id=hid, source_type=SOURCE_TYPE,
                                  source_url=f"{BASE}/explore-hotels/service/avail/days?spiritCode={spirit}&startDate={w_start}&endDate={w_end}",
                                  rows=rows, evidence_relpath=rel, evidence_bytes=raw, evidence_grade="RAW",
                                  workspace_dir=ROOT, today=today, commit=False)
            all_evidence.append(rel)
        else:
            consecutive_empty += 1
            
        # Pacing
        time.sleep(random.uniform(0.4, 0.7))
        
    # Record harvest status
    status = "OK" if dates_ok > 0 else "NO_AVAILABILITY"
    reason = "SMITH_DYNAMIC_POINTS" if dates_ok > 0 else "NO_ROOMS_PUBLISHED"
    detail = f"{dates_ok} award nights recorded with Smart Horizon Cutoff"
    
    for attempt in range(5):
        try:
            harvest_state.record(conn, SOURCE, hid, status, reason=reason, detail=detail,
                                 dates_ok=dates_ok, dates_total=len(windows) * 30, commit=False)
            conn.commit()
            break
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(1.0 + random.uniform(0.5, 1.5))
            else:
                raise
    
    return {"status": status, "rates": dates_ok}


def main():
    parser = argparse.ArgumentParser(description="Hyatt Mr & Mrs Smith Fast Harvester")
    parser.add_argument("--worker-id", type=int, default=1)
    parser.add_argument("--total-workers", type=int, default=1)
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--visible", action="store_true")
    args = parser.parse_args()
    
    today = date.today()
    windows = generate_monthly_windows(today, months=12)
    
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    
    todo = get_smith_todo(conn, worker_id=args.worker_id, total_workers=args.total_workers, limit=args.limit)
    log.info(f"[Worker {args.worker_id}/{args.total_workers}] Loaded {len(todo)} Mr & Mrs Smith hotels to harvest.")
    
    if not todo:
        log.info("Queue is empty! All Smith hotels already harvested.")
        conn.close()
        return
        
    session = SmithCDPSession(port=args.port, visible=args.visible)
    try:
        session.start()
        t0 = time.time()
        completed = 0
        total_rates = 0
        
        for h in todo:
            try:
                res = harvest_smith_hotel(session, conn, h, today, windows)
                completed += 1
                total_rates += res["rates"]
                
                el = time.time() - t0
                rate_per_min = (completed / el) * 60 if el > 0 else 0
                eta_min = (len(todo) - completed) / rate_per_min if rate_per_min > 0 else 0
                
                log.info(f"[{completed}/{len(todo)}] {h['spirit_code']} ({h['name'][:25]}): {res['status']} ({res['rates']} rates) | "
                         f"{rate_per_min:.1f} hot/min | ETA: {eta_min:.1f}m | Total Rates: {total_rates:,}")
            except Exception as e:
                log.warning(f"Error harvesting {h['spirit_code']}: {e}")
                time.sleep(2.0)
            
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    except Exception as e:
        log.exception(f"Fatal error: {e}")
    finally:
        session.close()
        conn.close()

if __name__ == "__main__":
    main()
