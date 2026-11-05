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

def extract_hotels_from_html(html_text: str, source_url: str):
    hotels = []
    
    # Try parsing Next.js __NEXT_DATA__
    m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            def traverse(obj):
                if isinstance(obj, dict):
                    if "title" in obj and ("url" in obj or "hotelUrl" in obj or "marshaCode" in obj):
                        title = obj.get("title", "").strip()
                        url = obj.get("url") or obj.get("hotelUrl") or ""
                        if url.startswith("/"):
                            url = f"https://www.marriott.com{url}"
                        
                        if len(title) > 3 and "Sitemap" not in title and not any(k in title.lower() for k in ["privacy", "terms", "credit card", "cookies", "best rate"]):
                            city = obj.get("city") or obj.get("cityName") or ""
                            country = obj.get("country") or obj.get("countryName") or ""
                            marsha = obj.get("marshaCode") or ""
                            
                            if not marsha:
                                m_mar = re.search(r'/hotels/([a-z0-9]{5})-', url)
                                if m_mar:
                                    marsha = m_mar.group(1)

                            hotels.append({
                                "name": title.replace(r"\u0026", "&").replace("&amp;", "&"),
                                "city": city,
                                "country": country,
                                "marsha": marsha.lower(),
                                "url": url
                            })
                    for v in obj.values():
                        traverse(v)
                elif isinstance(obj, list):
                    for item in obj:
                        traverse(item)

            traverse(data)
        except Exception:
            pass

    # Fallback regex parser for hotel cards
    if not hotels:
        matches = re.findall(r'<a[^>]*href=[\"\'](/en-us/hotels/[a-z0-9]{5}-[^\"\']+/overview/)[\"\'][^>]*>(.*?)</a>', html_text, re.DOTALL | re.IGNORECASE)
        for u, t in matches:
            clean_t = re.sub(r'<[^>]+>', '', t).strip()
            if len(clean_t) > 3 and "Sitemap" not in clean_t:
                m_mar = re.search(r'/hotels/([a-z0-9]{5})-', u)
                marsha = m_mar.group(1).lower() if m_mar else ""
                hotels.append({
                    "name": clean_t.replace("&amp;", "&"),
                    "city": "",
                    "country": "",
                    "marsha": marsha,
                    "url": f"https://www.marriott.com{u}"
                })

    return hotels

async def crawl_marriott_live():
    print("==================================================")
    print("🚀 Crawling Official Marriott Bonvoy Global Directory")
    print("==================================================")

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30.0) as client:
        r = await client.get("https://www.marriott.com/content/dam/marriott-seo/en/marriott-tng/sitemap-hotel-sitemaps.xml")
        sitemap_urls = re.findall(r'<loc>([^<]+-hotel-sitemap)</loc>', r.text)

    print(f"[*] Found {len(sitemap_urls)} country/state hotel sitemaps in Marriott index.")

    all_hotel_records = []
    seen_marshas = set()

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, limits=httpx.Limits(max_connections=35)) as client:
        for idx, sm_url in enumerate(sitemap_urls):
            slug = sm_url.split("/")[-1].replace("-hotel-sitemap", "")
            
            # Normalize country and state
            if slug.startswith("usa-"):
                country = "United States"
                state_name = slug.replace("usa-", "").replace("-", " ").title()
            elif slug.startswith("canada-"):
                country = "Canada"
                state_name = slug.replace("canada-", "").replace("-", " ").title()
            elif slug.startswith("mainland-china-"):
                country = "China"
                state_name = slug.replace("mainland-china-and-hong-kong-macau-taiwan-", "").replace("-", " ").title()
            else:
                country = " ".join([w.capitalize() for w in slug.split("-")])
                state_name = ""

            try:
                res = await client.get(sm_url, timeout=20.0)
                if res.status_code == 200:
                    hotels = extract_hotels_from_html(res.text, sm_url)
                    for h in hotels:
                        marsha = h["marsha"]
                        if marsha and marsha not in seen_marshas:
                            seen_marshas.add(marsha)
                            h_city = h["city"] or state_name or country
                            h_country = country if country else h["country"]
                            
                            all_hotel_records.append({
                                "id": f"marr_{marsha}",
                                "brand": "MARRIOTT",
                                "name": h["name"],
                                "city": h_city,
                                "country": h_country,
                                "currency": "USD",
                                "url": h["url"]
                            })
            except Exception as e:
                pass

            if (idx + 1) % 25 == 0 or idx + 1 == len(sitemap_urls):
                print(f"  Processed {idx + 1}/{len(sitemap_urls)} sitemaps... (Unique Marriott Properties: {len(all_hotel_records)})")

    print(f"\n✅ Total Verified Marriott Properties Extracted: {len(all_hotel_records)}")

    # Ingest into SQLite database
    conn = sqlite3.connect("hotel_stays.db")
    c = conn.cursor()
    c.execute("DELETE FROM hotels WHERE brand = 'MARRIOTT'")

    for h in all_hotel_records:
        c.execute("""
            INSERT OR REPLACE INTO hotels (id, brand, name, city, country, currency, loyalty_model, award_category, track_points, official_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (h["id"], h["brand"], h["name"], h["city"], h["country"], h["currency"], "DYNAMIC_AWARD", "Bonvoy Dynamic", 1, h["url"]))

    conn.commit()
    total_db = c.execute("SELECT COUNT(*) FROM hotels WHERE brand = 'MARRIOTT'").fetchone()[0]
    conn.close()

    print(f"📊 Saved {total_db} verified Marriott Bonvoy hotels to hotel_stays.db.\n")
    return all_hotel_records

if __name__ == "__main__":
    asyncio.run(crawl_marriott_live())
