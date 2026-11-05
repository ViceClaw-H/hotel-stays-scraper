import sys
import os
import re
import json
import sqlite3
import asyncio
from urllib.parse import urlparse
from curl_cffi.requests import AsyncSession

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def get_country_currency(country_name):
    country_name = (country_name or "").strip()
    mapping = {
        "Indonesia": "IDR", "Singapore": "SGD", "Thailand": "THB", "Malaysia": "MYR",
        "Vietnam": "USD", "Japan": "JPY", "South Korea": "KRW", "China": "CNY",
        "Hong Kong": "HKD", "Macau": "MOP", "Taiwan": "TWD", "Philippines": "PHP",
        "India": "INR", "Maldives": "USD", "Cambodia": "USD", "Laos": "USD",
        "Myanmar": "USD", "Australia": "AUD", "New Zealand": "NZD", "Fiji": "FJD",
        "United States": "USD", "Canada": "CAD", "Mexico": "USD", "Brazil": "BRL",
        "Argentina": "USD", "Chile": "USD", "Colombia": "USD", "Peru": "USD",
        "United Kingdom": "GBP", "France": "EUR", "Germany": "EUR", "Italy": "EUR",
        "Spain": "EUR", "Netherlands": "EUR", "Belgium": "EUR", "Switzerland": "CHF",
        "Austria": "EUR", "Portugal": "EUR", "Greece": "EUR", "Poland": "PLN",
        "Czech Republic": "CZK", "Hungary": "HUF", "Romania": "RON", "Turkey": "USD",
        "Sweden": "SEK", "Ireland": "EUR", "Denmark": "DKK", "Croatia": "EUR",
        "United Arab Emirates": "AED", "Saudi Arabia": "SAR", "Qatar": "QAR",
        "Oman": "OMR", "Bahrain": "BHD", "Kuwait": "KWD", "Jordan": "JOD",
        "Egypt": "USD", "Morocco": "MAD", "South Africa": "ZAR", "Mauritius": "USD",
        "Seychelles": "EUR", "Kenya": "USD", "Norway": "NOK", "Finland": "EUR"
    }
    return mapping.get(country_name, "USD")

def extract_country_from_city_obj(city_obj):
    if not city_obj or not isinstance(city_obj, dict):
        return None
    curr = city_obj.get('_location', {}).get('parentLocation')
    while curr and isinstance(curr, dict):
        content = curr.get('content', {})
        if isinstance(content, dict) and 'name' in content and content['name']:
            return content['name']
        curr = content.get('_location', {}).get('parentLocation') or curr.get('parentLocation')
    return None

async def fetch_gha_hotel(session: AsyncSession, url: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        try:
            r = await session.get(url, timeout=20.0)
            if r.status_code == 200:
                m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text)
                if m:
                    data = json.loads(m.group(1))
                    page = data.get('props', {}).get('pageProps', {}).get('page', {})
                    name = page.get('name')
                    if not name:
                        return None
                    
                    city_obj = page.get('city') or {}
                    city_name = city_obj.get('name') or "Destination"
                    country_name = extract_country_from_city_obj(city_obj) or "Global"
                    
                    # Brand extraction
                    brand_content = page.get('_location', {}).get('parentLocation', {}).get('content', {})
                    sub_brand = brand_content.get('title') or "GHA DISCOVERY"
                    
                    # Slug ID
                    path_parts = urlparse(url).path.strip('/').split('/')
                    hotel_slug = path_parts[1] if len(path_parts) > 1 else path_parts[0]
                    hotel_id = f"gha_{hotel_slug.replace('-', '_')[:30]}"
                    
                    currency = get_country_currency(country_name)
                    
                    return {
                        "id": hotel_id,
                        "brand": "GHA",
                        "sub_brand": sub_brand,
                        "name": name.strip(),
                        "city": city_name.strip(),
                        "country": country_name.strip(),
                        "currency": currency,
                        "url": url,
                        "status": 200
                    }
            return None
        except Exception as e:
            return None

async def main():
    print("==================================================")
    print("🚀 Crawling Official GHA DISCOVERY Directory")
    print("==================================================")
    
    async with AsyncSession(impersonate="chrome124") as session:
        all_sitemap_urls = []
        for i in range(1, 7):
            s_url = f"https://www.ghadiscovery.com/sitemap-{i}.xml"
            try:
                r = await session.get(s_url, timeout=15)
                if r.status_code == 200:
                    urls = re.findall(r'<loc>([^<]+)</loc>', r.text)
                    all_sitemap_urls.extend(urls)
                    print(f"[*] Fetched {s_url}: {len(urls)} URLs")
            except Exception as e:
                print(f"[!] Error fetching {s_url}: {e}")

    non_hotel_prefixes = {
        'destination-guides', 'news', 'about-us', 'brands', 'legal', 'loyalty',
        'complimentary-breakfast', 'explore', 'terms-and-conditions', 'privacy-policy',
        'faq', 'contact-us', 'press', 'careers', 'gha-discovery', 'promotions'
    }

    unique_hotel_urls = {}
    for u in all_sitemap_urls:
        path = urlparse(u).path.strip('/')
        parts = path.split('/')
        if len(parts) >= 2 and parts[0] not in non_hotel_prefixes:
            brand_slug = parts[0]
            hotel_slug = parts[1]
            hotel_url = f"https://www.ghadiscovery.com/{brand_slug}/{hotel_slug}"
            unique_hotel_urls[hotel_url] = (brand_slug, hotel_slug)

    print(f"[*] Total unique GHA hotel candidate URLs: {len(unique_hotel_urls)}")

    semaphore = asyncio.Semaphore(25)
    verified_hotels = []

    async with AsyncSession(impersonate="chrome124") as session:
        tasks = [fetch_gha_hotel(session, u, semaphore) for u in unique_hotel_urls.keys()]
        print(f"[*] Processing {len(tasks)} hotel pages concurrently...")
        
        batch_size = 50
        for idx in range(0, len(tasks), batch_size):
            chunk = tasks[idx:idx+batch_size]
            results = await asyncio.gather(*chunk)
            for res in results:
                if res and res.get("name"):
                    verified_hotels.append(res)
            print(f"  Processed {min(idx+batch_size, len(tasks))}/{len(tasks)} (Verified: {len(verified_hotels)})")

    print(f"\n✅ Total Verified Genuine GHA Hotels: {len(verified_hotels)}")

    # Ingest into SQLite database
    conn = sqlite3.connect("hotel_stays.db")
    c = conn.cursor()
    c.execute("DELETE FROM hotels WHERE brand = 'GHA'")

    inserted = 0
    seen_ids = set()
    for h in verified_hotels:
        h_id = h["id"]
        if h_id in seen_ids:
            h_id = f"{h_id}_{inserted}"
        seen_ids.add(h_id)

        c.execute("""
            INSERT OR REPLACE INTO hotels (id, brand, name, city, country, currency, loyalty_model, award_category, track_points, official_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (h_id, "GHA", h["name"], h["city"], h["country"], h["currency"], "CASH_REBATE", h["sub_brand"], 0, h["url"]))
        inserted += 1

    conn.commit()
    total_db = c.execute("SELECT COUNT(*) FROM hotels WHERE brand = 'GHA'").fetchone()[0]
    conn.close()

    print(f"📊 Saved {total_db} verified GHA DISCOVERY hotels to hotel_stays.db.\n")

if __name__ == "__main__":
    asyncio.run(main())
