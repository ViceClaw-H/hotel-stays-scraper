import sqlite3
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

conn = sqlite3.connect('hotel_stays.db')
c = conn.cursor()

print("=" * 100)
print("📊 DISTRIBUSI PERSENTIL VALUASI EMPIRIS MURNI (HASIL SCRAPING RIIL)")
print("=" * 100)
header = f"{'Brand':<16} | {'P0 (Min)':<14} | {'P10 (Promo)':<14} | {'P50 (Median)':<16} | {'P90 (SWEET SPOT)':<20} | {'P100 (Max)':<14} | {'Sampel'}"
print(header)
print("-" * 100)

for row in c.execute('SELECT brand, val_p0, val_p10, val_p50, val_p90, val_p100, rate_count FROM brand_composites ORDER BY brand'):
    b, p0, p10, p50, p90, p100, n = row
    p0_s = f"Rp {p0:,.1f}" if p0 else "-"
    p10_s = f"Rp {p10:,.1f}" if p10 else "-"
    p50_s = f"Rp {p50:,.1f}" if p50 else "-"
    p90_s = f"Rp {p90:,.1f}" if p90 else "-"
    p100_s = f"Rp {p100:,.1f}" if p100 else "-"
    print(f"{b:<16} | {p0_s:<14} | {p10_s:<14} | {p50_s:<16} | {p90_s:<20} | {p100_s:<14} | {n:,} hari")
print("=" * 100)
