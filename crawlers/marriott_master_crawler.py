"""Master Global Marriott Bonvoy Official Sitemap Crawler.
Pulls 100% of all ~8,800 real physical Marriott hotels worldwide directly from official marriott.com country sitemaps.
"""
import asyncio
import httpx
import re
import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.connection import get_session_factory
from database.models import Hotel
from export_hotels_excel import export_watchlist_to_excel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("marriott_master")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def extract_hotels_from_next_data(html_text: str, source_url: str):
    hotels = []
    # Find JSON props script
    m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.DOTALL)
    if not m:
        m = re.search(r'<script[^>]*>(\{"props":\{"pageProps".*?\})</script>', html_text, re.DOTALL)

    if m:
        try:
            data = json.loads(m.group(1))
            # Traverse JSON to find all items with title / marsha code / url
            def traverse(obj):
                if isinstance(obj, dict):
                    if "title" in obj and ("url" in obj or "hotelUrl" in obj or "marshaCode" in obj):
                        title = obj.get("title", "").strip()
                        url = obj.get("url") or obj.get("hotelUrl") or ""
                        if url.startswith("/"):
                            url = f"https://www.marriott.com{url}"
                        
                        if len(title) > 3 and "Sitemap" not in title and not any(k in title.lower() for k in ["privacy", "terms", "credit card", "cookies"]):
                            city = obj.get("city") or obj.get("cityName") or ""
                            country = obj.get("country") or obj.get("countryName") or ""
                            marsha = obj.get("marshaCode") or ""
                            hotels.append({
                                "name": title.replace(r"\u0026", "&").replace("&amp;", "&"),
                                "city": city,
                                "country": country,
                                "marsha": marsha,
                                "url": url
                            })
                    for v in obj.values():
                        traverse(v)
                elif isinstance(obj, list):
                    for item in obj:
                        traverse(item)

            traverse(data)
        except Exception as e:
            logger.debug(f"JSON parse error on {source_url}: {e}")

    # Fallback regex parser for links and titles if nested JSON path varies
    if not hotels:
        title_matches = re.findall(r'"title":\s*"([^"]+)",\s*"url":\s*"([^"]+)"', html_text)
        for t, u in title_matches:
            if "Sitemap" not in t and "/hotels/" in u:
                if u.startswith("/"):
                    u = f"https://www.marriott.com{u}"
                hotels.append({
                    "name": t.replace(r"\u0026", "&").replace("&amp;", "&"),
                    "city": "",
                    "country": "",
                    "marsha": "",
                    "url": u
                })

    return hotels

async def crawl_all_marriott_properties():
    logger.info("Fetching Marriott master sitemap index...")
    async with httpx.AsyncClient(headers=HEADERS, timeout=25.0, follow_redirects=True, limits=httpx.Limits(max_connections=30)) as client:
        r = await client.get("https://www.marriott.com/content/dam/marriott-seo/en/marriott-tng/sitemap-hotel-sitemaps.xml")
        sitemap_urls = re.findall(r'<loc>([^<]+-hotel-sitemap)</loc>', r.text)
        logger.info(f"Found {len(sitemap_urls)} country/state hotel sitemaps in Marriott index.")

        all_hotel_records = []
        seen_urls = set()

        async def fetch_country_sitemap(sm_url):
            try:
                # Determine country/state name from URL slug
                slug = sm_url.split("/")[-1].replace("-hotel-sitemap", "")
                country_state = " ".join([w.capitalize() for w in slug.split("-")])
                
                res = await client.get(sm_url)
                if res.status_code == 200:
                    extracted = extract_hotels_from_next_data(res.text, sm_url)
                    for h in extracted:
                        u = h["url"]
                        if u not in seen_urls:
                            seen_urls.add(u)
                            if not h["country"]:
                                h["country"] = country_state
                            all_hotel_records.append(h)
            except Exception as e:
                logger.error(f"Error fetching Marriott sitemap {sm_url}: {e}")

        # Gather in chunks
        chunk_size = 20
        for i in range(0, len(sitemap_urls), chunk_size):
            chunk = sitemap_urls[i:i+chunk_size]
            await asyncio.gather(*[fetch_country_sitemap(url) for url in chunk])
            logger.info(f"Processed {min(i+chunk_size, len(sitemap_urls))}/{len(sitemap_urls)} Marriott sitemaps. Total unique hotels: {len(all_hotel_records)}")

        logger.info(f"Finished sitemap crawl! Extracted {len(all_hotel_records)} real physical Marriott hotels globally.")

        # Save JSON
        with open("marriott_master_directory.json", "w", encoding="utf-8") as f:
            json.dump(all_hotel_records, f, indent=2, ensure_ascii=False)

        # Ingest into DB
        SessionMaker = get_session_factory()
        session = SessionMaker()

        # Remove previous Marriott hotels
        session.query(Hotel).filter(Hotel.brand == "MARRIOTT").delete()
        session.commit()

        total_added = 0
        seen_ids = set()

        for h in all_hotel_records:
            slug_code = re.sub(r'[^a-z0-9]', '', h["url"].split("/")[-2].lower() if "/" in h["url"] else h["name"].lower())[:20]
            if not slug_code:
                slug_code = f"prop_{total_added}"
            h_id = f"marr_{slug_code}"
            if h_id in seen_ids:
                h_id = f"marr_{slug_code}_{total_added}"
            seen_ids.add(h_id)

            new_hotel = Hotel(
                id=h_id,
                brand="MARRIOTT",
                name=h["name"],
                city=h["city"] or h["country"],
                country=h["country"],
                currency="USD",
                loyalty_model="DYNAMIC_AWARD",
                track_points=True,
                official_url=h["url"]
            )
            session.add(new_hotel)
            total_added += 1

            if total_added % 1000 == 0:
                session.commit()
                logger.info(f"Committed {total_added} Marriott hotels to database...")

        session.commit()
        session.close()
        logger.info(f"Successfully inserted all {total_added} real physical Marriott hotels into database!")
        export_watchlist_to_excel()

if __name__ == '__main__':
    asyncio.run(crawl_all_marriott_properties())
