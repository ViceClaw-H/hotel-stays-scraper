"""
All Hotel Stays - Master Unified Hotel Intelligence Engine
Single Controller & Entrypoint for:
- Scraping hotel chains (Marriott, Hilton, Accor, Hyatt, GHA)
- Dual-currency conversion & valuation (SOP: 100 USD (Rp 1.817.700))
- Point buy flash sale monitoring (Points.com net arbitrage)
- Report building (Index_Hotel.html with strict room tier matching)
- Catalog Excel export
"""

import sys
import os
import argparse
import subprocess
import time

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core.currency import get_currency_engine, format_dual
from core.catalog_exporter import export_catalog_to_excel

def run_ingest_hyatt():
    print("=" * 60)
    print("[TASK] Running World of Hyatt Sweetspots Ingestion...")
    p = os.path.join(BASE_DIR, "ingest_hyatt_sweetspots.py")
    if os.path.exists(p):
        subprocess.run([sys.executable, p], check=True)
    else:
        print(f"[WARN] File not found: {p}")

def run_watch_promos():
    print("=" * 60)
    print("[TASK] Running Points.com Buy Promo Watcher...")
    p = os.path.join(BASE_DIR, "points_buy_promo_watcher.py")
    if os.path.exists(p):
        subprocess.run([sys.executable, p], check=True)
    else:
        print(f"[WARN] File not found: {p}")

def run_build_report():
    print("=" * 60)
    print("[TASK] Building Index_Hotel.html Dashboard (Strict Room-Tier Matching)...")
    p = os.path.join(BASE_DIR, "build_index_hotel.py")
    if os.path.exists(p):
        subprocess.run([sys.executable, p], check=True)
    else:
        print(f"[WARN] File not found: {p}")

def run_export_excel():
    print("=" * 60)
    print("[TASK] Exporting Hotel Links & Catalog Status to Excel...")
    export_catalog_to_excel()

def run_serve():
    print("=" * 60)
    print("[TASK] Starting Local Web Dashboard Server (127.0.0.1:8000)...")
    p = os.path.join(BASE_DIR, "serve.py")
    if os.path.exists(p):
        subprocess.run([sys.executable, p])
    else:
        print(f"[WARN] File not found: {p}")

def run_today_pipeline():
    print("=" * 60)
    print("🏨 ANTIGRAVITY UNIFIED HOTEL ENGINE — DAILY PIPELINE")
    print("=" * 60)
    t0 = time.time()
    
    # 1. Update Promo Watcher
    run_watch_promos()
    
    # 2. Ingest Hyatt if needed
    run_ingest_hyatt()
    
    # 3. Export Catalog Excel
    run_export_excel()
    
    # 4. Build Final Index Dashboard
    run_build_report()
    
    print("=" * 60)
    print(f"[SUCCESS] All daily hotel operations completed in {time.time()-t0:.2f}s!")
    print(f"📄 Dashboard Ready: {os.path.join(BASE_DIR, 'Index_Hotel.html')}")
    print("=" * 60)

def main():
    parser = argparse.ArgumentParser(description="Antigravity Unified Hotel Intelligence Engine")
    parser.add_argument("--today", action="store_true", help="Run complete daily workflow (Promos + Hyatt + Report + Excel)")
    parser.add_argument("--build-report", action="store_true", help="Build/rebuild Index_Hotel.html")
    parser.add_argument("--watch-promos", action="store_true", help="Run Points.com buy promo watcher")
    parser.add_argument("--ingest-hyatt", action="store_true", help="Ingest Hyatt Category 1-4 sweetspots")
    parser.add_argument("--export-excel", action="store_true", help="Export All_Hotel_Scraped_Links.xlsx")
    parser.add_argument("--serve", action="store_true", help="Start local dashboard server")
    
    args = parser.parse_args()
    
    if len(sys.argv) == 1 or args.today:
        run_today_pipeline()
    elif args.build_report:
        run_build_report()
    elif args.watch_promos:
        run_watch_promos()
    elif args.ingest_hyatt:
        run_ingest_hyatt()
    elif args.export_excel:
        run_export_excel()
    elif args.serve:
        run_serve()

if __name__ == "__main__":
    main()
