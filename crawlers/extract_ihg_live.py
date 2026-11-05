import os
import sys
import re
import json
import sqlite3
import asyncio
import httpx

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

BRAND_NAME_MAP = {
    "intercontinental": "InterContinental",
    "regent": "Regent",
    "sixsenses": "Six Senses",
    "kimptonhotels": "Kimpton",
    "vignettecollection": "Vignette Collection",
    "voco": "voco",
    "hotelindigo": "Hotel Indigo",
    "crowneplaza": "Crowne Plaza",
    "holidayinn": "Holiday Inn",
    "holidayinnexpress": "Holiday Inn Express",
    "holidayinnresorts": "Holiday Inn Resort",
    "holidayinnclubvacations": "Holiday Inn Club Vacations",
    "staybridge": "Staybridge Suites",
    "candlewood": "Candlewood Suites",
    "avidhotels": "avid hotels",
    "atwellsuites": "Atwell Suites",
    "garnerhotels": "Garner Hotels",
    "evenhotels": "EVEN Hotels",
    "iberostarselection": "Iberostar Selection",
    "iberostarjoia": "Iberostar JOIA",
    "iberostarwaves": "Iberostar Waves",
    "holidayinntheniu": "Holiday Inn the niu",
    "rubyhotels": "Ruby Hotels",
}

# Major airport / city code prefix mapping for IHG
KNOWN_IHG_LOCATIONS = {
    "jkt": ("Jakarta", "Indonesia", "IDR", "Asia"),
    "dps": ("Bali", "Indonesia", "IDR", "Asia"),
    "sub": ("Surabaya", "Indonesia", "IDR", "Asia"),
    "bdg": ("Bandung", "Indonesia", "IDR", "Asia"),
    "sin": ("Singapore", "Singapore", "SGD", "Asia"),
    "kul": ("Kuala Lumpur", "Malaysia", "MYR", "Asia"),
    "bkk": ("Bangkok", "Thailand", "THB", "Asia"),
    "hkt": ("Phuket", "Thailand", "THB", "Asia"),
    "kbv": ("Krabi", "Thailand", "THB", "Asia"),
    "tyo": ("Tokyo", "Japan", "JPY", "Asia"),
    "osa": ("Osaka", "Japan", "JPY", "Asia"),
    "sel": ("Seoul", "South Korea", "KRW", "Asia"),
    "hkg": ("Hong Kong", "Hong Kong", "HKD", "Asia"),
    "lon": ("London", "United Kingdom", "GBP", "Europe"),
    "par": ("Paris", "France", "EUR", "Europe"),
    "ber": ("Berlin", "Germany", "EUR", "Europe"),
    "rom": ("Rome", "Italy", "EUR", "Europe"),
    "mad": ("Madrid", "Spain", "EUR", "Europe"),
    "ams": ("Amsterdam", "Netherlands", "EUR", "Europe"),
    "dxb": ("Dubai", "United Arab Emirates", "AED", "Middle East"),
    "auh": ("Abu Dhabi", "United Arab Emirates", "AED", "Middle East"),
    "doh": ("Doha", "Qatar", "QAR", "Middle East"),
    "ruh": ("Riyadh", "Saudi Arabia", "SAR", "Middle East"),
    "syd": ("Sydney", "Australia", "AUD", "Oceania"),
    "mel": ("Melbourne", "Australia", "AUD", "Oceania"),
    "akl": ("Auckland", "New Zealand", "NZD", "Oceania"),
    "nyc": ("New York", "United States", "USD", "Americas"),
    "chi": ("Chicago", "United States", "USD", "Americas"),
    "lax": ("Los Angeles", "United States", "USD", "Americas"),
    "sfo": ("San Francisco", "United States", "USD", "Americas"),
    "mia": ("Miami", "United States", "USD", "Americas"),
    "mle": ("Maldives", "Maldives", "USD", "Asia"),
}

from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests

def fetch_sub_sitemap(sm_url):
    try:
        r = requests.get(sm_url, impersonate='chrome124', timeout=30)
        if r.status_code == 200:
            return re.findall(r'<loc>([^<]+)</loc>', r.text)
    except Exception:
        pass
    return []

def crawl_ihg_live():
    print("==================================================")
    print("🚀 Crawling Official IHG One Rewards Global Directory")
    print("==================================================")

    r = requests.get("https://www.ihg.com/bin/sitemapindex.xml", impersonate='chrome124', timeout=30)
    all_sitemaps = re.findall(r'<loc>([^<]+)</loc>', r.text)
    target_sitemaps = [s for s in all_sitemaps if 'en-us.hoteldetail.xml' in s or 'en.hoteldetail.xml' in s]

    print(f"[*] Found {len(target_sitemaps)} brand hoteldetail sub-sitemaps on IHG.")

    all_raw_urls = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(fetch_sub_sitemap, target_sitemaps)
        for res in results:
            all_raw_urls.extend(res)

    print(f"[*] Retrieved {len(all_raw_urls)} total raw hotel URLs from IHG sitemaps.")

    unique_hotels = {}
    for url in all_raw_urls:
        m = re.search(r'ihg\.com/([^/]+)/hotels/[^/]+/en/([^/]+)/([a-z0-9]{4,6})/hoteldetail', url)
        if m:
            brand_slug = m.group(1).lower()
            city_slug = m.group(2).lower()
            hotel_code = m.group(3).upper()

            if hotel_code not in unique_hotels:
                brand_display = BRAND_NAME_MAP.get(brand_slug, "IHG")
                clean_city = " ".join([w.capitalize() for w in city_slug.split("-")])
                hotel_name = f"{brand_display} {clean_city}"

                prefix3 = hotel_code[:3].lower()
                if prefix3 in KNOWN_IHG_LOCATIONS:
                    city, country, curr, region = KNOWN_IHG_LOCATIONS[prefix3]
                else:
                    city = clean_city
                    country = "United States" if not any(c in city_slug for c in ["china", "uk", "france", "germany", "japan", "spain", "italy"]) else "Global"
                    curr = "USD"
                    region = "Global"

                clean_url = f"https://www.ihg.com/{brand_slug}/hotels/us/en/{city_slug}/{hotel_code.lower()}/hoteldetail"

                unique_hotels[hotel_code] = {
                    "id": f"ihg_{hotel_code.lower()}",
                    "brand": "IHG",
                    "name": hotel_name,
                    "city": city,
                    "country": country,
                    "currency": curr,
                    "url": clean_url
                }

    print(f"\n✅ Total Verified Unique IHG Hotels: {len(unique_hotels)}")

    # Ingest into SQLite database
    conn = sqlite3.connect("hotel_stays.db")
    c = conn.cursor()
    c.execute("DELETE FROM hotels WHERE brand = 'IHG'")

    for h in unique_hotels.values():
        c.execute("""
            INSERT OR REPLACE INTO hotels (id, brand, name, city, country, currency, loyalty_model, award_category, track_points, official_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (h["id"], h["brand"], h["name"], h["city"], h["country"], h["currency"], "DYNAMIC_AWARD", "IHG Dynamic", 1, h["url"]))

    conn.commit()
    total_db = c.execute("SELECT COUNT(*) FROM hotels WHERE brand = 'IHG'").fetchone()[0]
    conn.close()

    print(f"📊 Saved {total_db} verified IHG One Rewards hotels to hotel_stays.db.\n")
    return list(unique_hotels.values())

if __name__ == "__main__":
    crawl_ihg_live()
