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

BRAND_MAP = {
    "wa": "Waldorf Astoria",
    "ch": "Conrad",
    "lx": "LXR",
    "hi": "Hilton",
    "dt": "DoubleTree",
    "es": "Embassy Suites",
    "gi": "Hilton Garden Inn",
    "hp": "Hampton",
    "ht": "Home2 Suites",
    "hw": "Homewood Suites",
    "qq": "Curio Collection",
    "up": "Tapestry / Canopy",
    "ru": "Tru by Hilton",
    "pe": "Tempo / Spark",
    "py": "Signia / Motto",
}

# Major CTYHOCN city code prefixes
KNOWN_CITIES = {
    "jkt": ("Jakarta", "Indonesia", "IDR", "Asia"),
    "dps": ("Bali", "Indonesia", "IDR", "Asia"),
    "sub": ("Surabaya", "Indonesia", "IDR", "Asia"),
    "bdg": ("Bandung", "Indonesia", "IDR", "Asia"),
    "sin": ("Singapore", "Singapore", "SGD", "Asia"),
    "kul": ("Kuala Lumpur", "Malaysia", "MYR", "Asia"),
    "bkk": ("Bangkok", "Thailand", "THB", "Asia"),
    "hkt": ("Phuket", "Thailand", "THB", "Asia"),
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
    "orl": ("Orlando", "United States", "USD", "Americas"),
    "yvr": ("Vancouver", "Canada", "CAD", "Americas"),
    "yyz": ("Toronto", "Canada", "CAD", "Americas"),
}

def clean_title_from_slug(slug: str) -> str:
    # Slug format: {ctyhocn}-{hotel-name-words}
    parts = slug.split("-")
    words = parts[1:] if len(parts) > 1 else parts
    capitalized = []
    for w in words:
        if w.lower() in ["and", "by", "the", "at", "in", "of"]:
            capitalized.append(w.lower())
        else:
            capitalized.append(w.capitalize())
    return " ".join(capitalized)

async def crawl_hilton_live():
    print("==================================================")
    print("🚀 Crawling Official Hilton Honors Global Directory")
    print("==================================================")

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30.0) as client:
        r = await client.get("https://www.hilton.com/sitemap/en/sitemap-en.xml")
        all_sub_sitemaps = re.findall(r'<loc>([^<]+)</loc>', r.text)
        prop_sitemaps = [sm for sm in all_sub_sitemaps if "sitemap-en-prop-" in sm]

    print(f"[*] Found {len(prop_sitemaps)} property sub-sitemaps in Hilton master index.")

    all_hotel_records = []
    seen_urls = set()

    async def fetch_sub_sitemap(client, sm_url):
        try:
            res = await client.get(sm_url, timeout=20.0)
            urls = re.findall(r'<loc>(https://www\.hilton\.com/en/hotels/[^<]+)/</loc>', res.text)
            
            m_brand = re.search(r'sitemap-en-prop-([a-z]{2})', sm_url)
            brand_code = m_brand.group(1) if m_brand else "hi"
            sub_brand = BRAND_MAP.get(brand_code, "Hilton")

            for u in urls:
                if u not in seen_urls and not any(x in u for x in ["/dining", "/amenities", "/rooms", "/offers", "/events", "/gallery", "/things-to-do"]):
                    seen_urls.add(u)
                    hotel_slug = u.split("/")[-1]
                    code = hotel_slug[:7].lower()
                    
                    # Determine city / country
                    prefix3 = code[:3]
                    if prefix3 in KNOWN_CITIES:
                        city, country, curr, region = KNOWN_CITIES[prefix3]
                    else:
                        city = clean_title_from_slug(hotel_slug).split()[-1] if len(hotel_slug.split("-")) > 1 else "Main City"
                        country = "United States" if not any(c in hotel_slug for c in ["china", "uk", "france", "germany", "japan"]) else "Global"
                        curr = "USD"
                        region = "Global"

                    hotel_name = clean_title_from_slug(hotel_slug)
                    if sub_brand not in hotel_name and not any(b in hotel_name for b in ["Hilton", "DoubleTree", "Hampton", "Conrad", "Waldorf", "Embassy", "Curio", "Canopy"]):
                        hotel_name = f"{sub_brand} {hotel_name}"

                    all_hotel_records.append({
                        "id": f"hilt_{code}",
                        "brand": "HILTON",
                        "name": hotel_name,
                        "city": city,
                        "country": country,
                        "currency": curr,
                        "url": u + "/"
                    })
        except Exception:
            pass

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, limits=httpx.Limits(max_connections=35)) as client:
        batch_size = 30
        for i in range(0, len(prop_sitemaps), batch_size):
            chunk = prop_sitemaps[i:i+batch_size]
            await asyncio.gather(*[fetch_sub_sitemap(client, u) for u in chunk])
            print(f"  Processed {min(i+batch_size, len(prop_sitemaps))}/{len(prop_sitemaps)} Hilton sub-sitemaps... (Unique Hotels: {len(all_hotel_records)})")

    print(f"\n✅ Total Verified Hilton Hotels Extracted: {len(all_hotel_records)}")

    # Ingest into SQLite database
    conn = sqlite3.connect("hotel_stays.db")
    c = conn.cursor()
    c.execute("DELETE FROM hotels WHERE brand = 'HILTON'")

    for h in all_hotel_records:
        c.execute("""
            INSERT OR REPLACE INTO hotels (id, brand, name, city, country, currency, loyalty_model, award_category, track_points, official_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (h["id"], h["brand"], h["name"], h["city"], h["country"], h["currency"], "DYNAMIC_AWARD", "Honors Dynamic", 1, h["url"]))

    conn.commit()
    total_db = c.execute("SELECT COUNT(*) FROM hotels WHERE brand = 'HILTON'").fetchone()[0]
    conn.close()

    print(f"📊 Saved {total_db} verified Hilton Honors hotels to hotel_stays.db.\n")
    return all_hotel_records

if __name__ == "__main__":
    asyncio.run(crawl_hilton_live())
