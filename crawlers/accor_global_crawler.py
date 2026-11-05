"""Accor Global Country & Hotel Directory Extractor.
Pulls official hotel URLs from Accor's master sitemap and extracts verified hotels country-by-country.
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
logger = logging.getLogger("accor_crawler")

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
    "IN": "India", "PH": "Philippines", "ZA": "South Africa"
}

async def fetch_hotel_details(client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
    try:
        r = await client.get(url, timeout=12.0)
        if r.status_code == 200:
            # Extract JSON-LD or meta tags
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

            # Clean name
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

async def crawl_accor_sitemap(batch_size: int = 200, limit: int = 1000):
    logger.info("Fetching Accor Master Sitemap index...")
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30.0) as client:
        r = await client.get("https://all.accor.com/sitemap-fh.en.xml")
        urls = re.findall(r'<loc>([^<]+)</loc>', r.text)
    
    total_available = len(urls)
    logger.info(f"Total verified hotel URLs found in sitemap: {total_available}")
    
    target_urls = urls[:limit] if limit > 0 else urls
    logger.info(f"Processing batch of {len(target_urls)} hotels...")
    
    all_hotels = []
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, limits=httpx.Limits(max_connections=30)) as client:
        for i in range(0, len(target_urls), batch_size):
            chunk = target_urls[i:i+batch_size]
            tasks = [fetch_hotel_details(client, u) for u in chunk]
            results = await asyncio.gather(*tasks)
            valid = [r for r in results if r.get("status") == "ok"]
            all_hotels.extend(valid)
            logger.info(f"Extracted {len(all_hotels)} / {len(target_urls)} hotels so far...")
            await asyncio.sleep(0.5)

    # Group by country
    by_country = {}
    for h in all_hotels:
        c = h["country"]
        if c not in by_country:
            by_country[c] = []
        by_country[c].append(h)

    # Save to JSON
    with open("accor_crawled_hotels.json", "w", encoding="utf-8") as f:
        json.dump(by_country, f, ensure_ascii=False, indent=2)

    logger.info(f"Complete! Extracted {len(all_hotels)} hotels across {len(by_country)} countries.")
    return by_country

if __name__ == '__main__':
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    asyncio.run(crawl_accor_sitemap(batch_size=50, limit=limit))
