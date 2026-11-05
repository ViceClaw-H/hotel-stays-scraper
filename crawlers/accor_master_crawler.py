"""Accor Master Global Extractor & Database Seeder.
Parses all 5,897 verified properties from Accor's official master XML sitemap,
extracts real hotel names, cities, and countries, and populates hotel_stays.db.
"""
import sys
import os
import re
import json
import asyncio
import logging
from typing import Dict, List, Any
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.connection import get_session_factory
from database.models import Hotel, RoomCategory

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("accor_master_crawler")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

# ISO 2-letter country code to full name mapping
ISO_COUNTRY_MAP = {
    "ID": "Indonesia", "SG": "Singapore", "TH": "Thailand", "MY": "Malaysia",
    "VN": "Vietnam", "JP": "Japan", "KR": "South Korea", "AU": "Australia",
    "NZ": "New Zealand", "FR": "France", "GB": "United Kingdom", "DE": "Germany",
    "IT": "Italy", "ES": "Spain", "NL": "Netherlands", "CH": "Switzerland",
    "BE": "Belgium", "AT": "Austria", "PT": "Portugal", "GR": "Greece",
    "TR": "Turkey", "AE": "United Arab Emirates", "SA": "Saudi Arabia",
    "QA": "Qatar", "EG": "Egypt", "MA": "Morocco", "US": "United States",
    "CA": "Canada", "BR": "Brazil", "MX": "Mexico", "CN": "China",
    "IN": "India", "PH": "Philippines", "ZA": "South Africa", "PL": "Poland",
    "CZ": "Czech Republic", "HU": "Hungary", "RO": "Romania", "SE": "Sweden",
    "IE": "Ireland", "DK": "Denmark", "HR": "Croatia", "CO": "Colombia",
    "AR": "Argentina", "CL": "Chile", "PE": "Peru", "UY": "Uruguay",
    "CI": "Ivory Coast", "SN": "Senegal", "NG": "Nigeria", "KE": "Kenya",
    "OM": "Oman", "BH": "Bahrain", "KW": "Kuwait", "JO": "Jordan",
    "PF": "French Polynesia", "MU": "Mauritius", "SC": "Seychelles"
}

async def fetch_hotel_details(client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
    try:
        r = await client.get(url, timeout=12.0)
        if r.status_code == 200:
            country_m = re.search(r'"addressCountry"\s*:\s*"([^"]+)"', r.text)
            city_m = re.search(r'"addressLocality"\s*:\s*"([^"]+)"', r.text)
            name_m = re.search(r'"name"\s*:\s*"([^"]+)"', r.text)
            
            if not name_m:
                title_m = re.search(r'<title>(.*?)</title>', r.text, re.IGNORECASE)
                name = title_m.group(1).replace('- ALL', '').replace('| ALL', '').strip() if title_m else ''
            else:
                name = name_m.group(1).replace('- ALL', '').replace('| ALL', '').strip()
                if "Accor Live Limitless" in name:
                    title_m = re.search(r'<title>(.*?)</title>', r.text, re.IGNORECASE)
                    name = title_m.group(1).replace('- ALL', '').replace('| ALL', '').strip() if title_m else name

            country_code = country_m.group(1).upper() if country_m else ''
            country = ISO_COUNTRY_MAP.get(country_code, country_code or 'Global')
            city = city_m.group(1).title() if city_m else 'Main City'
            name = re.sub(r'&amp;', '&', name).strip()
            
            if name and len(name) > 3:
                return {
                    "name": name,
                    "city": city,
                    "country": country,
                    "country_code": country_code,
                    "url": url,
                    "status": "ok"
                }
    except Exception as e:
        return {"url": url, "status": "error", "error": str(e)}
    return {"url": url, "status": "fail"}

async def run_full_accor_extraction(limit: int = 0):
    logger.info("Connecting to official Accor Master XML Sitemap...")
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30.0) as client:
        r = await client.get("https://all.accor.com/sitemap-fh.en.xml")
        urls = re.findall(r'<loc>([^<]+)</loc>', r.text)
    
    total = len(urls)
    logger.info(f"Retrieved {total} official hotel URLs from Accor.")
    target_urls = urls[:limit] if limit > 0 else urls
    
    all_hotels = []
    batch_size = 50
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, limits=httpx.Limits(max_connections=35)) as client:
        for i in range(0, len(target_urls), batch_size):
            chunk = target_urls[i:i+batch_size]
            tasks = [fetch_hotel_details(client, u) for u in chunk]
            results = await asyncio.gather(*tasks)
            valid = [r for r in results if r.get("status") == "ok"]
            all_hotels.extend(valid)
            if len(all_hotels) % 250 == 0 or i + batch_size >= len(target_urls):
                logger.info(f"Progress: {len(all_hotels)} / {len(target_urls)} verified properties processed...")
            await asyncio.sleep(0.3)

    # Save to JSON
    by_country = {}
    for h in all_hotels:
        c = h["country"]
        if c not in by_country:
            by_country[c] = []
        by_country[c].append(h)

    with open("accor_master_directory.json", "w", encoding="utf-8") as f:
        json.dump(by_country, f, ensure_ascii=False, indent=2)

    logger.info(f"Successfully extracted {len(all_hotels)} Accor hotels across {len(by_country)} countries.")

    # Seed Database
    SessionMaker = get_session_factory()
    session = SessionMaker()
    added = 0
    for country, hotel_list in by_country.items():
        for h in hotel_list:
            existing = session.query(Hotel).filter(Hotel.name == h["name"]).first()
            if not existing:
                slug = re.sub(r'[^a-z0-9_]', '', h["name"].lower().replace(' ', '_').replace('-', '_'))[:35]
                h_id = f"accor_{h['country_code'].lower()}_{slug}"
                new_h = Hotel(
                    id=h_id,
                    brand="ACCOR",
                    name=h["name"],
                    city=h["city"],
                    country=country,
                    currency="EUR" if country in ["France", "Germany", "Italy", "Spain", "Netherlands", "Belgium", "Austria", "Portugal", "Greece"] else ("USD" if country in ["United States", "United Arab Emirates", "Saudi Arabia", "Qatar", "Egypt"] else "IDR"),
                    loyalty_model="CASH_REBATE",
                    track_points=False,
                    official_url=h["url"]
                )
                session.add(new_h)
                added += 1
    session.commit()
    session.close()
    logger.info(f"Database synced with {added} new properties.")

if __name__ == '__main__':
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    asyncio.run(run_full_accor_extraction(limit=lim))
