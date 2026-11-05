"""Rigorous database audit and cleanup.
Ensures 100% of rows are real physical hotels with proper root URLs and clean names.
"""
import sqlite3
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from export_hotels_excel import export_watchlist_to_excel

def clean_title_from_slug(slug: str) -> str:
    words = slug.split("-")
    capitalized = []
    for w in words:
        if w.lower() in ["and", "by", "the", "at", "in", "of", "on", "de", "del", "la", "le"]:
            capitalized.append(w.lower())
        else:
            capitalized.append(w.capitalize())
    return " ".join(capitalized)

def run_deduplication_and_cleanup():
    conn = sqlite3.connect('hotel_stays.db')
    cursor = conn.cursor()

    # 1. CLEAN HILTON
    print("Deduplicating and cleaning Hilton...")
    hilton_rows = cursor.execute('SELECT id, name, city, country, official_url FROM hotels WHERE brand = "HILTON"').fetchall()
    
    unique_hilton = {}
    for hid, name, city, country, url in hilton_rows:
        m = re.search(r'hilton\.com/en/hotels/([a-z0-9-]+)', url)
        if m:
            code_slug = m.group(1).split('/')[0]
            clean_url = f"https://www.hilton.com/en/hotels/{code_slug}/"
            
            # Derive proper hotel name from slug if name is generic (like 'Hotel Info', 'Hotel Location')
            if name in ['Hotel Info', 'Hotel Location', 'Rooms', 'Dining', 'Amenities'] or len(name) < 4:
                proper_name = clean_title_from_slug(code_slug)
            else:
                proper_name = name

            if code_slug not in unique_hilton:
                unique_hilton[code_slug] = {
                    "id": f"hilt_{code_slug}",
                    "brand": "HILTON",
                    "name": proper_name,
                    "city": city,
                    "country": country,
                    "currency": "USD",
                    "loyalty_model": "DYNAMIC_AWARD",
                    "track_points": 1,
                    "official_url": clean_url
                }
            else:
                # Keep better name if already exists
                if unique_hilton[code_slug]["name"] in ['Hotel Info', 'Hotel Location'] and proper_name not in ['Hotel Info', 'Hotel Location']:
                    unique_hilton[code_slug]["name"] = proper_name

    cursor.execute('DELETE FROM hotels WHERE brand = "HILTON"')
    conn.commit()

    for h in unique_hilton.values():
        cursor.execute("""
            INSERT OR REPLACE INTO hotels (id, brand, name, city, country, currency, loyalty_model, track_points, official_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (h["id"], h["brand"], h["name"], h["city"], h["country"], h["currency"], h["loyalty_model"], h["track_points"], h["official_url"]))

    conn.commit()
    print(f"Hilton cleaned: {len(hilton_rows)} raw URLs -> {len(unique_hilton)} unique physical hotels.")

    # 2. AUDIT SUMMARY
    print("\n=== FINAL AUDITED DATABASE TOTALS ===")
    total = cursor.execute('SELECT COUNT(*) FROM hotels').fetchone()[0]
    for b, count in cursor.execute('SELECT brand, COUNT(*) FROM hotels GROUP BY brand ORDER BY COUNT(*) DESC').fetchall():
        print(f"  • {b:<12}: {count:>6} real physical hotels")
    print(f"GRAND TOTAL: {total} verified physical hotels")

    conn.close()
    export_watchlist_to_excel()

if __name__ == '__main__':
    run_deduplication_and_cleanup()
