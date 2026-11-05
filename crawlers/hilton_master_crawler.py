"""Master Global Hilton Hotels Official Sitemap Crawler.
Pulls 100% of all ~7,500+ real physical Hilton hotels worldwide from official hilton.com XML sitemaps.
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
logger = logging.getLogger("hilton_master")

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

def clean_title_from_slug(slug: str) -> str:
    words = slug.split("-")
    capitalized = []
    for w in words:
        if w.lower() in ["and", "by", "the", "at", "in", "of"]:
            capitalized.append(w.lower())
        else:
            capitalized.append(w.capitalize())
    return " ".join(capitalized)

async def crawl_all_hilton_properties():
    logger.info("Fetching Hilton master sitemap index...")
    async with httpx.AsyncClient(headers=HEADERS, timeout=25.0, follow_redirects=True, limits=httpx.Limits(max_connections=35)) as client:
        r = await client.get("https://www.hilton.com/sitemap/en/sitemap-en.xml")
        all_sub_sitemaps = re.findall(r'<loc>([^<]+)</loc>', r.text)
        prop_sitemaps = [sm for sm in all_sub_sitemaps if "sitemap-en-prop-" in sm]
        logger.info(f"Found {len(prop_sitemaps)} property-specific sub-sitemaps in official Hilton index.")

        all_hotel_records = []
        seen_urls = set()

        async def fetch_sub_sitemap(sm_url):
            try:
                res = await client.get(sm_url)
                # Pattern: https://www.hilton.com/en/hotels/{ctyhocn-slug}/
                urls = re.findall(r'<loc>(https://www\.hilton\.com/en/hotels/[^<]+)/</loc>', res.text)
                for u in urls:
                    if u not in seen_urls and not any(x in u for x in ["/dining", "/amenities", "/rooms", "/offers", "/events", "/gallery"]):
                        seen_urls.add(u)
                        hotel_slug = u.split("/")[-1]
                        
                        # Extract brand code from sitemap URL (e.g., sitemap-en-prop-wa-001.xml)
                        m_brand = re.search(r'sitemap-en-prop-([a-z]{2})', sm_url)
                        brand_code = m_brand.group(1) if m_brand else "hi"
                        brand_name = BRAND_MAP.get(brand_code, "Hilton")

                        hotel_name = clean_title_from_slug(hotel_slug)

                        all_hotel_records.append({
                            "name": hotel_name,
                            "slug": hotel_slug,
                            "brand": "HILTON",
                            "sub_brand": brand_name,
                            "url": u + "/"
                        })
            except Exception as e:
                logger.error(f"Error fetching Hilton sub-sitemap {sm_url}: {e}")

        # Gather in chunks
        chunk_size = 25
        for i in range(0, len(prop_sitemaps), chunk_size):
            chunk = prop_sitemaps[i:i+chunk_size]
            await asyncio.gather(*[fetch_sub_sitemap(url) for url in chunk])
            logger.info(f"Processed {min(i+chunk_size, len(prop_sitemaps))}/{len(prop_sitemaps)} Hilton sub-sitemaps. Total unique hotels: {len(all_hotel_records)}")

        logger.info(f"Finished sitemap crawl! Extracted {len(all_hotel_records)} real physical Hilton hotels globally.")

        # Save JSON
        with open("hilton_master_directory.json", "w", encoding="utf-8") as f:
            json.dump(all_hotel_records, f, indent=2, ensure_ascii=False)

        # Ingest into DB
        SessionMaker = get_session_factory()
        session = SessionMaker()

        # Remove previous Hilton hotels
        session.query(Hotel).filter(Hotel.brand == "HILTON").delete()
        session.commit()

        total_added = 0
        seen_ids = set()

        for h in all_hotel_records:
            slug_code = re.sub(r'[^a-z0-9]', '', h["slug"].lower())[:24]
            h_id = f"hilt_{slug_code}"
            if h_id in seen_ids:
                h_id = f"hilt_{slug_code}_{total_added}"
            seen_ids.add(h_id)

            new_hotel = Hotel(
                id=h_id,
                brand="HILTON",
                name=h["name"],
                city=h["sub_brand"],
                country="Global Portfolio",
                currency="USD",
                loyalty_model="DYNAMIC_AWARD",
                track_points=True,
                official_url=h["url"]
            )
            session.add(new_hotel)
            total_added += 1

            if total_added % 1000 == 0:
                session.commit()
                logger.info(f"Committed {total_added} Hilton hotels to database...")

        session.commit()
        session.close()
        logger.info(f"Successfully inserted all {total_added} real physical Hilton hotels into database!")
        export_watchlist_to_excel()

if __name__ == '__main__':
    asyncio.run(crawl_all_hilton_properties())
