import json
import sqlite3
import datetime
import re
import os
import sys
from playwright.sync_api import sync_playwright

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "hotel_stays.db")

with open(os.path.join(BASE_DIR, "scratch", "bw_destination_urls.json")) as f:
    urls = json.load(f)

search_targets = []
for u in urls:
    parts = u.replace("https://www.bestwestern.com/en-us/destinations/", "").strip("/").split("/")
    if len(parts) == 1:
        c = parts[0]
        search_targets.append(("country", c, "", f"https://www.bestwestern.com/en-us/book/search?propertyCountry={c}"))
    elif len(parts) == 2:
        c, sub = parts[0], parts[1]
        if c.lower() in ["us", "ca"]:
            search_targets.append(("state", c, sub, f"https://www.bestwestern.com/en-us/book/search?propertyState={sub}&propertyCountry={c}"))
        else:
            search_targets.append(("city", c, sub, f"https://www.bestwestern.com/en-us/book/search?propertyCity={sub}&propertyCountry={c}"))

print(f"Total search targets: {len(search_targets)}")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Get existing hotel codes/names
cur.execute("SELECT id FROM hotels WHERE brand='BEST_WESTERN'")
existing_ids = set(r[0] for r in cur.fetchall())
print(f"Existing Best Western in DB: {len(existing_ids)}")

now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
total_new = 0

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel="msedge")
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    
    for idx, (stype, country, loc, target_url) in enumerate(search_targets):
        try:
            page.goto(target_url, timeout=30000)
            page.wait_for_timeout(2500)
            
            # Scrape hotel links
            hotel_links = page.evaluate('''() => {
                return Array.from(document.querySelectorAll('a'))
                    .map(a => a.href)
                    .filter(h => h.includes('/book/hotel-rooms/'));
            }''')
            
            unique_links = set(hotel_links)
            if unique_links:
                print(f"[{idx+1}/{len(search_targets)}] {loc or country} ({country.upper()}): found {len(unique_links)} hotels")
                for h_url in unique_links:
                    # Format: https://www.bestwestern.com/en-us/book/hotel-rooms/city/hotel-slug/12345?...
                    clean_h = h_url.split("?")[0]
                    m = re.search(r'/book/hotel-rooms/([^/]+)/([^/]+)/(\d+)', clean_h)
                    if m:
                        city_slug, hotel_slug, prop_code = m.group(1), m.group(2), m.group(3)
                        h_id = f"bw_{prop_code}"
                        if h_id not in existing_ids:
                            existing_ids.add(h_id)
                            
                            # Clean name
                            words = hotel_slug.split("-")
                            name = " ".join([w.capitalize() if w.lower() not in ["and", "by", "the", "at", "in", "of", "on", "de", "del"] else w.lower() for w in words])
                            city_name = " ".join(city_slug.split("-")).title()
                            official_booking_url = f"https://www.bestwestern.com/content/best-western/en_US/booking-path/hotel-details.{prop_code}.html"
                            
                            cur.execute("""
                                INSERT INTO hotels (
                                    id, brand, name, city, country, currency, loyalty_model,
                                    award_category, track_points, official_url, created_at,
                                    lifecycle_status, status_updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                h_id, "BEST_WESTERN", name, city_name, country.upper(), "USD",
                                "BEST_WESTERN_REWARDS", "STANDARD", 1, official_booking_url,
                                now_iso, "ACTIVE", now_iso
                            ))
                            total_new += 1
                conn.commit()
        except Exception as e:
            # pass silently on timeouts
            continue
            
    browser.close()

conn.commit()
cur.execute("SELECT count(*) FROM hotels WHERE brand='BEST_WESTERN'")
final_count = cur.fetchone()[0]
conn.close()

print("=" * 65)
print(f"Finished scraping! Added {total_new} new official Best Western hotels.")
print(f"Total Best Western properties now in database: {final_count}")
print("=" * 65)
