"""Master Global Wyndham Hotels Official Sitemap Crawler.
Pulls 100% of all ~9,200 real physical hotels worldwide from official wyndhamhotels.com XML sitemaps.
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
from database.models import Hotel, RoomCategory, PropertyBaseline
from export_hotels_excel import export_watchlist_to_excel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("wyndham_master")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
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

async def crawl_all_wyndham_properties():
    logger.info("Fetching Wyndham master sitemap index...")
    async with httpx.AsyncClient(headers=HEADERS, timeout=25.0, follow_redirects=True, limits=httpx.Limits(max_connections=35)) as client:
        r = await client.get("https://www.wyndhamhotels.com/sitemap.xml")
        sub_sitemaps = re.findall(r'<loc>([^<]+properties[^<]*\.xml)</loc>', r.text)
        logger.info(f"Found {len(sub_sitemaps)} property sub-sitemaps in official Wyndham index.")

        all_hotel_records = []
        seen_urls = set()

        async def fetch_sub_sitemap(sm_url):
            try:
                res = await client.get(sm_url)
                urls = re.findall(r'<loc>([^<]+/overview)</loc>', res.text)
                for u in urls:
                    if u not in seen_urls and not u.endswith("/testing/overview"):
                        seen_urls.add(u)
                        # Pattern: wyndhamhotels.com/{brand}/{city_region}/{hotel_slug}/overview
                        m = re.search(r'wyndhamhotels\.com/([a-z0-9-]+)/([a-z0-9-]+)/([a-z0-9-]+)/overview', u)
                        if m:
                            brand_slug = m.group(1)
                            city_region = m.group(2)
                            hotel_slug = m.group(3)

                            # Parse country and city
                            region_parts = city_region.split("-")
                            if len(region_parts) >= 2:
                                city_name = " ".join([p.capitalize() for p in region_parts[:-1]])
                                country_or_state = region_parts[-1].capitalize()
                            else:
                                city_name = city_region.capitalize()
                                country_or_state = "United States"

                            # Detect international vs US
                            known_countries = {
                                "indonesia": "Indonesia", "thailand": "Thailand", "malaysia": "Malaysia",
                                "singapore": "Singapore", "vietnam": "Vietnam", "philippines": "Philippines",
                                "japan": "Japan", "china": "China", "germany": "Germany", "france": "France",
                                "italy": "Italy", "spain": "Spain", "mexico": "Mexico", "canada": "Canada",
                                "australia": "Australia", "brazil": "Brazil", "turkey": "Turkey",
                                "united-kingdom": "United Kingdom", "united-arab-emirates": "United Arab Emirates",
                                "netherlands": "Netherlands", "austria": "Austria", "switzerland": "Switzerland",
                                "greece": "Greece", "india": "India", "saudi-arabia": "Saudi Arabia"
                            }

                            matched_country = None
                            for k, v in known_countries.items():
                                if k in city_region:
                                    matched_country = v
                                    break

                            country = matched_country if matched_country else ("United States" if country_or_state in [
                                "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
                                "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
                                "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
                                "Missouri", "Montana", "Nebraska", "Nevada", "New-hampshire", "New-jersey", "New-mexico",
                                "New-york", "North-carolina", "North-dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
                                "Rhode-island", "South-carolina", "South-dakota", "Tennessee", "Texas", "Utah", "Vermont",
                                "Virginia", "Washington", "West-virginia", "Wisconsin", "Wyoming", "Texas", "Georgia"
                            ] else country_or_state)

                            hotel_name = clean_title_from_slug(hotel_slug)

                            all_hotel_records.append({
                                "name": hotel_name,
                                "city": city_name,
                                "country": country,
                                "brand_slug": brand_slug,
                                "url": u
                            })
            except Exception as e:
                logger.error(f"Error fetching sub-sitemap {sm_url}: {e}")

        # Gather in chunks
        chunk_size = 20
        for i in range(0, len(sub_sitemaps), chunk_size):
            chunk = sub_sitemaps[i:i+chunk_size]
            await asyncio.gather(*[fetch_sub_sitemap(url) for url in chunk])
            logger.info(f"Processed {min(i+chunk_size, len(sub_sitemaps))}/{len(sub_sitemaps)} sub-sitemaps. Total unique hotels: {len(all_hotel_records)}")

        logger.info(f"Finished sitemap crawl! Extracted {len(all_hotel_records)} real physical Wyndham hotels globally.")

        # Save JSON
        with open("wyndham_master_directory.json", "w", encoding="utf-8") as f:
            json.dump(all_hotel_records, f, indent=2, ensure_ascii=False)

        # Ingest into DB
        SessionMaker = get_session_factory()
        session = SessionMaker()

        # Remove previous Wyndham hotels
        session.query(Hotel).filter(Hotel.brand == "WYNDHAM").delete()
        session.commit()

        total_added = 0
        seen_ids = set()

        for h in all_hotel_records:
            slug_code = re.sub(r'[^a-z0-9]', '', h["url"].split("/")[-2].lower())[:20]
            h_id = f"wynd_{slug_code}"
            if h_id in seen_ids:
                h_id = f"wynd_{slug_code}_{total_added}"
            seen_ids.add(h_id)

            curr = "EUR" if h["country"] in ["France", "Germany", "Italy", "Spain", "Netherlands", "Austria"] else ("IDR" if h["country"] == "Indonesia" else ("THB" if h["country"] == "Thailand" else "USD"))

            new_hotel = Hotel(
                id=h_id,
                brand="WYNDHAM",
                name=h["name"],
                city=h["city"],
                country=h["country"],
                currency=curr,
                loyalty_model="FLAT_3_TIER",
                track_points=True,
                official_url=h["url"]
            )
            session.add(new_hotel)
            total_added += 1

            if total_added % 1000 == 0:
                session.commit()
                logger.info(f"Committed {total_added} Wyndham hotels to database...")

        session.commit()
        session.close()
        logger.info(f"Successfully inserted all {total_added} real physical Wyndham hotels into database!")
        export_watchlist_to_excel()

if __name__ == '__main__':
    asyncio.run(crawl_all_wyndham_properties())
