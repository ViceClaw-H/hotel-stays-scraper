"""IHG One Rewards Master Global Sitemap Crawler.
Pulls 100% of all official physical hotels across all 19 IHG brands directly from official IHG sitemaps:
InterContinental, Regent, Six Senses, Kimpton, Vignette Collection, voco, Hotel Indigo,
Crowne Plaza, Holiday Inn, Holiday Inn Express, Holiday Inn Resorts, Holiday Inn Club Vacations,
Staybridge Suites, Candlewood Suites, avid hotels, Atwell Suites, Garner Hotels, EVEN Hotels, Iberostar.
"""
import os
import sys
import re
import json
import logging
from curl_cffi import requests
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from export_hotels_excel import export_watchlist_to_excel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ihg_master_crawler")

SITEMAP_INDEX_URL = "https://www.ihg.com/bin/sitemapindex.xml"

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
    "armyhotels": "IHG Army Hotels"
}

def clean_name_from_slug(city_slug: str, hotel_code: str, brand_name: str) -> str:
    city_name = " ".join([w.capitalize() for w in city_slug.split("-")])
    return f"{brand_name} {city_name} ({hotel_code.upper()})"

def fetch_sitemap_urls(sitemap_url: str):
    try:
        r = requests.get(sitemap_url, impersonate='chrome124', timeout=40)
        if r.status_code == 200:
            return re.findall(r'<loc>([^<]+)</loc>', r.text)
    except Exception as e:
        logger.warning(f"Error fetching {sitemap_url}: {e}")
    return []

def run_ihg_master_crawler():
    logger.info("Fetching IHG Master Sitemap Index...")
    r = requests.get(SITEMAP_INDEX_URL, impersonate='chrome124', timeout=30)
    all_sitemaps = re.findall(r'<loc>([^<]+)</loc>', r.text)
    
    # Filter English hoteldetail sitemaps
    target_sitemaps = [s for s in all_sitemaps if 'en-us.hoteldetail.xml' in s or 'en.hoteldetail.xml' in s]
    logger.info(f"Found {len(target_sitemaps)} brand hoteldetail sub-sitemaps on IHG.")

    all_raw_urls = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(fetch_sitemap_urls, target_sitemaps)
        for res in results:
            all_raw_urls.extend(res)

    logger.info(f"Total raw URLs fetched from IHG sitemaps: {len(all_raw_urls)}")

    # Deduplicate by unique 5-letter hotel code
    # URL format: https://www.ihg.com/{brand}/hotels/us/en/{city}/{code}/hoteldetail
    unique_hotels = {}
    for url in all_raw_urls:
        m = re.search(r'ihg\.com/([^/]+)/hotels/[^/]+/en/([^/]+)/([a-z0-9]{4,6})/hoteldetail', url)
        if m:
            brand_slug = m.group(1).lower()
            city_slug = m.group(2).lower()
            hotel_code = m.group(3).upper()

            if hotel_code not in unique_hotels:
                brand_display = BRAND_NAME_MAP.get(brand_slug, "IHG")
                hotel_name = clean_name_from_slug(city_slug, hotel_code, brand_display)
                city_display = " ".join([w.capitalize() for w in city_slug.split("-")])
                
                # Standardize clean canonical English URL
                clean_url = f"https://www.ihg.com/{brand_slug}/hotels/us/en/{city_slug}/{hotel_code.lower()}/hoteldetail"

                unique_hotels[hotel_code] = {
                    "id": f"ihg_{hotel_code.lower()}",
                    "brand": "IHG",
                    "name": hotel_name,
                    "city": city_display,
                    "country": "Global Portfolio",
                    "currency": "USD",
                    "loyalty_model": "DYNAMIC_AWARD",
                    "track_points": 1,
                    "official_url": clean_url
                }

    logger.info(f"Total UNIQUE physical IHG properties extracted: {len(unique_hotels)}!")

    # Save to JSON
    with open("ihg_master_directory.json", "w", encoding="utf-8") as f:
        json.dump(list(unique_hotels.values()), f, indent=2, ensure_ascii=False)

    # Ingest into SQLite database
    import sqlite3
    conn = sqlite3.connect('hotel_stays.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM hotels WHERE brand = 'IHG'")
    conn.commit()

    for h in unique_hotels.values():
        cursor.execute("""
            INSERT OR REPLACE INTO hotels (id, brand, name, city, country, currency, loyalty_model, track_points, official_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (h["id"], h["brand"], h["name"], h["city"], h["country"], h["currency"], h["loyalty_model"], h["track_points"], h["official_url"]))

    conn.commit()
    conn.close()
    logger.info(f"Successfully committed all {len(unique_hotels)} official IHG properties into database!")
    export_watchlist_to_excel()

if __name__ == '__main__':
    run_ihg_master_crawler()
