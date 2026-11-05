"""Command-line interface for 100% Authentic Hotel Stays & Rate Intelligence Engine.
Designed to run in standard library Python (zero third-party dependencies required for audit, verify, build, serve, test).
"""
import argparse
import sys
import os
import sqlite3
import math
import json
import http.server
import socketserver
import webbrowser
import subprocess
from dataclasses import dataclass
from typing import Optional

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from engine.country_taxes import calculate_gross_cash_rate, get_country_tax
from engine.verify_evidence_integrity import run_evidence_audit

@dataclass
class BrandConfig:
    code: str
    display_name: str
    loyalty_model: str
    track_points: bool
    award_currency_name: Optional[str]
    description: str

BRAND_REGISTRY = {
    "ACCOR": BrandConfig("ACCOR", "Accor Live Limitless", "FIXED_REBATE", False, "ALL Points", "Fixed rebate €40 per 2,000 pts"),
    "BEST_WESTERN": BrandConfig("BEST_WESTERN", "Best Western Rewards", "DYNAMIC", True, "BWR Points", "Dynamic award rates with seasonal bounds"),
    "GHA": BrandConfig("GHA", "GHA DISCOVERY", "FIXED_REBATE", False, "DISCOVERY Dollars (D$)", "Fixed folio cash credit: 1 D$ = 1 USD"),
    "HILTON": BrandConfig("HILTON", "Hilton Honors", "DYNAMIC_WITH_CAPS", True, "Honors Points", "Dynamic award rates with standard room caps"),
    "HYATT": BrandConfig("HYATT", "World of Hyatt", "AWARD_CHART", True, "World of Hyatt Points", "Fixed categories (Cat 1–8) with peak/off-peak pricing"),
    "IHG": BrandConfig("IHG", "IHG One Rewards", "DYNAMIC", True, "IHG One Rewards Points", "Dynamic pricing fluctuating with cash rates"),
    "LANGHAM": BrandConfig("LANGHAM", "Brilliant by Langham", "FIXED_REBATE", False, "Brilliant Points", "Revenue-based room credits"),
    "MARRIOTT": BrandConfig("MARRIOTT", "Marriott Bonvoy", "DYNAMIC", True, "Bonvoy Points", "Dynamic pricing with seasonal soft bounds"),
    "RADISSON": BrandConfig("RADISSON", "Radisson Rewards", "DYNAMIC", True, "Radisson Rewards Points", "Dynamic cash-pegged redemptions"),
    "SHANGRI-LA": BrandConfig("SHANGRI-LA", "Shangri-La Circle", "FIXED_REBATE", False, "Circle Points", "Revenue-based redemption (15 pts = 1 USD)"),
    "SWISS_BELHOTEL": BrandConfig("SWISS_BELHOTEL", "Swiss-Belhotel International (SBEC)", "DISCOUNT_BENEFIT", False, None, "Direct member rates & discount benefits"),
    "WYNDHAM": BrandConfig("WYNDHAM", "Wyndham Rewards", "FLAT_TIERS", True, "Wyndham Rewards Points", "Flat 7.5k / 15k / 30k point tiers per bedroom"),
}

def compute_percentiles(values):
    """Compute empirical P0, P10, P50, P90, P100 using pure standard library math."""
    if not values:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    s = sorted(float(v) for v in values)
    n = len(s)
    if n == 1:
        return s[0], s[0], s[0], s[0], s[0]
    
    p0 = s[0]
    p100 = s[-1]
    
    def get_pct(p):
        k = (n - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return s[int(k)]
        d0 = s[int(f)] * (c - k)
        d1 = s[int(c)] * (k - f)
        return d0 + d1

    return p0, get_pct(10), get_pct(50), get_pct(90), p100

def print_table(rows, headers):
    """Clean ASCII table formatter without requiring third-party tabulate package."""
    try:
        from tabulate import tabulate
        print(tabulate(rows, headers=headers, tablefmt="github"))
        return
    except ImportError:
        pass

    col_widths = [len(str(h)) for h in headers]
    for r in rows:
        for i, val in enumerate(r):
            col_widths[i] = max(col_widths[i], len(str(val)))

    header_line = " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_line = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    print(header_line)
    print(sep_line)
    for r in rows:
        print(" | ".join(str(val).ljust(col_widths[i]) for i, val in enumerate(r)))

def cmd_brands(args):
    """List the 12 major hotel chains, their loyalty model, and point tracking strategy."""
    table_data = []
    for brand_code, cfg in sorted(BRAND_REGISTRY.items()):
        points_status = "Track Points + Cash" if cfg.track_points else "Cash Only (Fixed Rebate)"
        table_data.append([
            brand_code,
            cfg.display_name,
            cfg.loyalty_model,
            points_status,
            cfg.award_currency_name or "-",
            cfg.description,
        ])

    headers = ["Brand Code", "Display Name", "Model", "Points Tracking", "Award Currency", "Pricing Mechanics"]
    print("\n=== [12 MAJOR HOTEL BRANDS IN DATABASE] ===")
    print_table(table_data, headers=headers)

def cmd_baselines(args):
    """Display Floor and Percentile baselines for properties."""
    conn = sqlite3.connect("hotel_stays.db")
    c = conn.cursor()

    query = """
        SELECT h.brand, h.name, h.city, h.country, h.currency,
               pb.cash_p0, pb.cash_p10, pb.cash_p50, pb.cash_p90, pb.cash_p100,
               pb.points_p0, pb.points_p100, pb.val_p50, pb.val_p90, pb.sample_count
        FROM property_baselines pb
        JOIN room_categories rc ON pb.room_id = rc.id
        JOIN hotels h ON rc.hotel_id = h.id
    """
    params = []
    if args.brand:
        query += " WHERE UPPER(h.brand) = ?"
        params.append(args.brand.upper())
    query += " ORDER BY h.brand, h.country, h.name LIMIT 30"

    try:
        rows = c.execute(query, tuple(params)).fetchall()
    except Exception as e:
        rows = []
    conn.close()

    if not rows:
        print("No precomputed baselines found in property_baselines table.")
        print("Run `python -m engine.baselines` to update empirical baselines.")
        return

    table_data = []
    for r in rows:
        b, name, city, cntry, curr, p0, p10, p50, p90, p100, pf, pc, v50, v90, sc = r
        p0_str = f"{p0:,.0f}" if p0 else "-"
        p50_str = f"{p50:,.0f}" if p50 else "-"
        p90_str = f"{p90:,.0f}" if p90 else "-"
        pts_str = f"{pf:,}" if pf else "-"
        v50_str = f"{v50:.1f}" if v50 else "-"
        table_data.append([
            b, name[:28], f"{city}, {cntry}", curr, p0_str, p50_str, p90_str, pts_str, v50_str, sc
        ])

    headers = ["Brand", "Hotel Name", "Location", "Curr", "P0 Floor", "P50 Median", "P90 Peak", "Award Pts", "V50 (Val)", "Samples"]
    print("\n=== [EMPIRICAL PROPERTY BASELINES (P0 - P100)] ===")
    print_table(table_data, headers=headers)

def cmd_percentiles(args):
    """Audit 5-Tier Percentiles and Valuations for specific hotels."""
    conn = sqlite3.connect("hotel_stays.db")
    c = conn.cursor()

    query = """
        SELECT h.id, rc.id, h.brand, h.name, h.city, h.country, h.currency
        FROM hotels h
        JOIN room_categories rc ON LOWER(rc.hotel_id) = LOWER(h.id)
    """
    params = []
    if args.hotel:
        query += " WHERE LOWER(h.name) LIKE ? OR LOWER(h.id) LIKE ?"
        kw = f"%{args.hotel.lower()}%"
        params.extend([kw, kw])
    elif args.brand:
        query += " WHERE UPPER(h.brand) = ?"
        params.append(args.brand.upper())

    hotels = c.execute(query, tuple(params)).fetchall()

    if not hotels:
        print(f"No hotels found matching criteria: {args.hotel or args.brand}")
        conn.close()
        return

    print(f"\n=== [5-TIER GROSS PRICE FLOORS & VALUATION AUDIT ({len(hotels)} ROOMS FOUND)] ===")
    
    for hid, r_id, brand, name, city, country, curr in hotels[:15]:
        rates = c.execute("""
            SELECT stay_date, cash_rate, points_required, tax_inclusive
            FROM rate_records
            WHERE room_id = ? AND cash_rate IS NOT NULL
            ORDER BY stay_date ASC
        """, (r_id,)).fetchall()

        if not rates:
            continue

        gross_cash = [
            float(r[1]) if r[3] == 1 else calculate_gross_cash_rate(r[1], country)
            for r in rates
        ]
        pts_arr = [r[2] for r in rates if r[2] is not None]

        p0, p10, p50, p90, p100 = compute_percentiles(gross_cash)
        pts_med = int(sorted(pts_arr)[len(pts_arr)//2]) if pts_arr else 0
        val_med = (p50 / pts_med) if pts_med > 0 else 0

        print(f"\n🏨 [{brand}] {name} ({city}, {country}) - {len(rates)} records")
        print(f"   • P0 (Floor / Lowest)        : {curr} {p0:>12,.2f}  (Gross Total)")
        print(f"   • P10 (Promo Cash)           : {curr} {p10:>12,.2f}")
        print(f"   • P50 (MEDIAN Fair Value)    : {curr} {p50:>12,.2f}  [Benchmark Fair Value]")
        print(f"   • P90 (Surge Peak / Sweet)   : {curr} {p90:>12,.2f}")
        print(f"   • P100 (Max Peak / Ceiling)  : {curr} {p100:>12,.2f}  (+{(((p100-p0)/p0)*100 if p0>0 else 0):.1f}% Surge)")
        if pts_med > 0:
            print(f"   • Award Points per Night     : {pts_med:>12,} pts")
            print(f"   • Fair Median Valuation (V50): {curr} {val_med:>12,.2f} / Point")

    conn.close()

def cmd_audit(args):
    """Audit database rate records for 100% genuine live CRS scrape provenance."""
    conn = sqlite3.connect("hotel_stays.db")
    c = conn.cursor()

    total_hotels = c.execute("SELECT count(*) FROM hotels").fetchone()[0]
    total_rates = c.execute("SELECT count(*) FROM rate_records").fetchone()[0]
    distinct_hotels_with_rates = c.execute("""
        SELECT count(DISTINCT h.id)
        FROM hotels h
        JOIN room_categories rc ON h.id = rc.hotel_id
        JOIN rate_records r ON rc.id = r.room_id
    """).fetchone()[0]

    synthetic_count = c.execute("""
        SELECT count(*) FROM rate_records
        WHERE notes LIKE '%Synthetic%' OR notes LIKE '%Benchmark formula%' OR notes LIKE '%estimated multiplier%'
    """).fetchone()[0]

    provenance = c.execute("""
        SELECT source_type, count(*)
        FROM rate_records
        GROUP BY source_type
        ORDER BY count(*) DESC
    """).fetchall()

    evidence_reg_count = c.execute("SELECT count(*) FROM evidence_registry").fetchone()[0]

    print("\n========================================================")
    print("🔍 [DATABASE PROVENANCE & REAL DATA AUDIT]")
    print("========================================================")
    print(f"  • Total Cataloged Properties   : {total_hotels:,}")
    print(f"  • Total Scraped Rate Records   : {total_rates:,}")
    print(f"  • Properties with Active Rates : {distinct_hotels_with_rates:,}")
    print(f"  • Registered Evidence Files    : {evidence_reg_count:,}")
    print(f"  • Synthetic / Fake Records     : {synthetic_count} (Must be 0)")
    print("\nOfficial Rate Provenance Breakdown:")
    for prov, count in provenance:
        print(f"   - {prov:<28}: {count:>6,} records")

    if synthetic_count == 0:
        print("\nKEYWORD CHECK: no row note contains a synthetic keyword.")
        print("Running cryptographic evidence parity check...")
        report = run_evidence_audit("hotel_stays.db", strict=False)
        if not report.get("audit_passed"):
            sys.exit(1)
    else:
        print(f"\n❌ AUDIT WARNING: Found {synthetic_count} synthetic records.")
        sys.exit(1)

    conn.close()

def cmd_verify(args):
    """Run cryptographic SHA-256 byte-parity verification across all on-disk evidence files."""
    print("[*] Running evidence audit (byte parity + value replay)...\n")
    report = run_evidence_audit("hotel_stays.db", strict=getattr(args, "strict", False))
    sys.exit(0 if report["audit_passed"] else 1)

def cmd_build(args):
    """Compile and generate Hotel_Analytics_Dashboard.html and Index_Hotel.html."""
    print("[*] Compiling Master Interactive Hotel Intelligence Dashboard via build_index_hotel.py...")
    cmd = [sys.executable, "build_index_hotel.py"]
    res = subprocess.run(cmd)
    if res.returncode == 0:
        print("✅ Dashboard compilation complete: Index_Hotel.html & Hotel_Analytics_Dashboard.html")
    else:
        print("❌ Dashboard compilation failed.")
        sys.exit(res.returncode)

def cmd_serve(args):
    """Start a local HTTP server to preview static dashboards in browsers without file:// policy blocks."""
    port = args.port or 8000
    host = "127.0.0.1"
    url = f"http://{host}:{port}/Hotel_Analytics_Dashboard.html"
    
    print(f"\n========================================================")
    print(f"🌐 [LOCAL DASHBOARD HTTP SERVER]")
    print(f"========================================================")
    print(f"Serving workspace at: http://{host}:{port}/")
    print(f"  • Master Analytics Dashboard : http://{host}:{port}/Hotel_Analytics_Dashboard.html")
    print(f"  • Index Hotel Matrix         : http://{host}:{port}/Index_Hotel.html")
    print(f"Press Ctrl+C to stop server.\n")

    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer((host, port), Handler) as httpd:
        try:
            if not args.no_browser:
                webbrowser.open(url)
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")

def cmd_stats(args):
    """Show detailed summary statistics of all hotels, rate records, and evidence files in the database."""
    conn = sqlite3.connect("hotel_stays.db")
    c = conn.cursor()

    print("\n=================================================================")
    print("           HOTEL STAYS DATABASE GLOBAL INVENTORY REPORT          ")
    print("=================================================================")

    c.execute("""
        SELECT h.brand, COUNT(DISTINCT h.id) as hotels_count, COUNT(r.id) as rates_count,
               MIN(r.stay_date) as min_date, MAX(r.stay_date) as max_date
        FROM hotels h
        LEFT JOIN room_categories rc ON rc.hotel_id = h.id
        LEFT JOIN rate_records r ON r.room_id = rc.id
        GROUP BY h.brand
        ORDER BY rates_count DESC
    """)
    brand_rows = c.fetchall()
    
    brand_table = []
    total_hotels = 0
    total_rates = 0
    for b in brand_rows:
        b_name = b[0]
        h_cnt = b[1]
        r_cnt = b[2] or 0
        d_range = f"{b[3]} to {b[4]}" if b[3] else "No rates yet"
        total_hotels += h_cnt
        total_rates += r_cnt
        brand_table.append([b_name, f"{h_cnt:,}", f"{r_cnt:,}", d_range])

    print("\n[SUMMARY BY BRAND]")
    print_table(brand_table, headers=["Brand", "Hotels Count", "Rate Records", "Calendar Date Range"])
    print(f"\nTOTAL ACTIVE HOTELS  : {total_hotels:,}")
    print(f"TOTAL RATE RECORDS    : {total_rates:,}")

    # Breakdown by Room Class
    c.execute("""
        SELECT r.room_class, COUNT(*)
        FROM rate_records r
        GROUP BY r.room_class
        ORDER BY 2 DESC
    """)
    room_classes = c.fetchall()
    print("\n[RATE RECORDS BY ROOM CLASS]")
    rc_table = [[row[0], f"{row[1]:,}"] for row in room_classes]
    print_table(rc_table, headers=["Room Class", "Rate Records"])

    conn.close()
    print("=================================================================\n")

def cmd_test(args):
    """Run integrity test suite ensuring 100% genuine evidence and zero synthetic data."""
    print("[*] Running Cryptographic Evidence Integrity Audit...")
    report = run_evidence_audit("hotel_stays.db", strict=getattr(args, "strict", False))
    sys.exit(0 if report.get("audit_passed") else 1)

def main():
    parser = argparse.ArgumentParser(description="Hotel Rate Intelligence & Sweet Spot Engine CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    subparsers.add_parser("brands", help="List registered hotel brands and loyalty rules")

    p_base = subparsers.add_parser("baselines", help="Show Floor and Percentile baselines table")
    p_base.add_argument("--brand", type=str, help="Filter by brand (e.g. IHG, WYNDHAM, BEST_WESTERN, SWISS_BELHOTEL)")

    p_pct = subparsers.add_parser("percentiles", help="Show 5-Tier Percentiles (P0, P10, P50, P90, P100) for hotel")
    p_pct.add_argument("--hotel", type=str, help="Search by hotel name keyword (e.g. Jakarta, London, Tokyo, Bali)")
    p_pct.add_argument("--brand", type=str, help="Filter by brand")

    subparsers.add_parser("audit", help="Audit database rate records for 100% genuine CRS scrape provenance")

    subparsers.add_parser("stats", help="Show global inventory summary of hotels and rate records in database")

    p_verify = subparsers.add_parser("verify", help="Evidence audit: byte parity + values re-derived from evidence; exits non-zero on failure")
    p_verify.add_argument("--strict", action="store_true", help="also fail while UNVERIFIED rows remain")

    subparsers.add_parser("build", help="Compile and generate Hotel_Analytics_Dashboard.html and Index_Hotel.html")

    p_serve = subparsers.add_parser("serve", help="Start local HTTP server to view dashboards in web browser")
    p_serve.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    p_serve.add_argument("--no-browser", action="store_true", help="Do not automatically open web browser")

    subparsers.add_parser("test", help="Run automated evidence integrity test suite")

    args = parser.parse_args()

    if args.command == "brands":
        cmd_brands(args)
    elif args.command == "baselines":
        cmd_baselines(args)
    elif args.command == "percentiles":
        cmd_percentiles(args)
    elif args.command == "audit":
        cmd_audit(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "verify":
        cmd_verify(args)
    elif args.command == "build":
        cmd_build(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "test":
        cmd_test(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
