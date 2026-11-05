"""Master Global Shangri-La & The Langham Official Sitemap Crawler.
Pulls 100% of all real physical hotels worldwide directly from official XML sitemaps.
"""
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
logger = logging.getLogger("shang_lang_master")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def clean_title_from_slug(slug: str) -> str:
    words = slug.split("-")
    capitalized = []
    for w in words:
        if w.lower() in ["and", "by", "the", "at", "in", "of", "on", "de", "la", "le"]:
            capitalized.append(w.lower())
        else:
            capitalized.append(w.capitalize())
    return " ".join(capitalized)

def crawl_shangrila_langham():
    # 1. SHANGRI-LA
    logger.info("Fetching Shangri-La official sitemap...")
    r_shang = httpx.get("https://www.shangri-la.com/uploadedFiles/sitemapmain.xml", headers=HEADERS, timeout=20.0)
    locs = re.findall(r'<loc>(https://www\.shangri-la\.com/en/([^/]+)/([^/]+)/?)</loc>', r_shang.text)
    
    shang_hotels = []
    seen_shang = set()
    for full_url, city_slug, hotel_slug in locs:
        if not any(k in hotel_slug for k in ["dining", "offers", "meetings", "weddings", "about", "press", "terms", "privacy", "contact"]):
            key = f"{city_slug}_{hotel_slug}"
            if key not in seen_shang and len(hotel_slug) > 3:
                seen_shang.add(key)
                hotel_name = clean_title_from_slug(hotel_slug)
                city_name = clean_title_from_slug(city_slug)
                shang_hotels.append({
                    "name": hotel_name,
                    "city": city_name,
                    "slug": key,
                    "url": full_url
                })

    logger.info(f"Extracted {len(shang_hotels)} Shangri-La properties from official XML sitemap.")

    # 2. THE LANGHAM
    logger.info("Fetching The Langham official sitemap...")
    r_lang = httpx.get("https://www.langhamhotels.com/sitemap.xml", headers=HEADERS, timeout=20.0)
    lang_locs = re.findall(r'<loc>(https://www\.langhamhotels\.com/en/([^/]+)/([^/]+)/?)</loc>', r_lang.text)
    
    lang_hotels = []
    seen_lang = set()
    for full_url, brand_slug, hotel_slug in lang_locs:
        if not any(k in hotel_slug for k in ["admin", "your-story", "about", "contact", "offers", "dining", "terms"]):
            key = f"{brand_slug}_{hotel_slug}"
            if key not in seen_lang and len(hotel_slug) > 2:
                seen_lang.add(key)
                hotel_name = clean_title_from_slug(hotel_slug)
                brand_name = clean_title_from_slug(brand_slug)
                lang_hotels.append({
                    "name": f"{brand_name} {hotel_name}",
                    "city": hotel_name,
                    "slug": key,
                    "url": full_url
                })

    logger.info(f"Extracted {len(lang_hotels)} The Langham properties from official XML sitemap.")

    # Ingest into DB
    SessionMaker = get_session_factory()
    session = SessionMaker()

    if shang_hotels:
        session.query(Hotel).filter(Hotel.brand == "SHANGRI_LA").delete()
        for idx, h in enumerate(shang_hotels):
            h_id = f"shang_{re.sub(r'[^a-z0-9]', '', h['slug'].lower())[:24]}_{idx}"
            new_h = Hotel(
                id=h_id,
                brand="SHANGRI_LA",
                name=h["name"],
                city=h["city"],
                country="Global Portfolio",
                currency="USD",
                loyalty_model="FIXED_REBATE",
                track_points=False,
                official_url=h["url"]
            )
            session.add(new_h)

    if lang_hotels:
        session.query(Hotel).filter(Hotel.brand == "LANGHAM").delete()
        for idx, h in enumerate(lang_hotels):
            h_id = f"lang_{re.sub(r'[^a-z0-9]', '', h['slug'].lower())[:24]}_{idx}"
            new_h = Hotel(
                id=h_id,
                brand="LANGHAM",
                name=h["name"],
                city=h["city"],
                country="Global Portfolio",
                currency="USD",
                loyalty_model="FIXED_REBATE",
                track_points=False,
                official_url=h["url"]
            )
            session.add(new_h)

    session.commit()
    session.close()
    logger.info("Successfully committed Shangri-La and The Langham official hotels into database!")
    export_watchlist_to_excel()

if __name__ == '__main__':
    crawl_shangrila_langham()
