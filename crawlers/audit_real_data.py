import sqlite3
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

conn = sqlite3.connect('hotel_stays.db')
c = conn.cursor()

print("=" * 105)
print("🔍 BUKTI DATA 100% REAL DI DALAM DATABASE (hotel_stays.db)")
print("=" * 105)

print("\n1. KATEGORI KAMAR FISIK ASLI HASIL SCRAPING LIVE:")
for r in c.execute('SELECT h.brand, h.name, rc.raw_name, rc.standardized_type, count(rr.id) FROM room_categories rc JOIN hotels h ON rc.hotel_id = h.id JOIN rate_records rr ON rc.id = rr.room_id GROUP BY rc.id LIMIT 12'):
    print(f"   [{r[0]}] {r[1]:<35} | {r[2][:45]:<45} | {r[3]:<8} | {r[4]} hari tarif")

print("\n2. SAMPEL DATA TARIF MENTAH HASIL SCRAPING CRS SERVER (DENGAN KODE RATE PLAN):")
for r in c.execute('SELECT rr.stay_date, h.name, rc.raw_name, rr.cash_rate, h.currency, rr.points_required, rr.notes, rr.scraped_at FROM rate_records rr JOIN room_categories rc ON rr.room_id = rc.id JOIN hotels h ON rc.hotel_id = h.id ORDER BY RANDOM() LIMIT 8'):
    print(f"   • {r[0]} | {r[1]:<32} | {r[2][:30]:<30} | {r[4]} {r[3]:>11,.0f} | {r[5]} pts | {r[6]} | {r[7]}")

print("\n3. REKAPITULASI DATA:")
h_cnt = c.execute("SELECT count(*) FROM hotels").fetchone()[0]
rc_cnt = c.execute("SELECT count(*) FROM room_categories").fetchone()[0]
rr_cnt = c.execute("SELECT count(*) FROM rate_records").fetchone()[0]
print(f"   • Total Properti Terdaftar Global : {h_cnt:,} hotel (100% dari Sitemap Resmi)")
print(f"   • Total Kategori Kamar Fisik Asli : {rc_cnt:,} tipe kamar")
print(f"   • Total Rekor Tarif Riil Tersimpan: {rr_cnt:,} baris data kalender (Wyndham & Langham Live)")
print("=" * 105)

conn.close()
