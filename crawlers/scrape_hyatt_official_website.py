"""Scrapes 100% official Hyatt hotel locations directly from official hyatt.com brand pages.
"""
import os
import sys
import re
import json
import time
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hyatt_official_scraper")

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_hyatt_official")

HYATT_BRAND_SLUGS = [
    "park-hyatt",
    "grand-hyatt",
    "andaz",
    "alila",
    "hyatt-regency",
    "thompson-hotels",
    "unbound-collection",
    "hyatt-centric",
    "hyatt-place",
    "hyatt-house",
    "destination-by-hyatt",
    "jdv-by-hyatt",
    "miraval",
    "hyatt-ziva",
    "hyatt-zilara",
    "secrets-resorts-and-spas",
    "dreams-resorts-and-spas",
    "zoetry-wellness-and-spa-resorts",
    "breathless-resorts-and-spas",
    "alua-hotels-and-resorts",
    "sunscape-resorts-and-spas",
    "hyatt-studios",
    "urcove"
]

def scrape_hyatt_brand_locations():
    extracted_hotels = {}

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/Chicago",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            ignore_default_args=["--enable-automation"],
        )
        page = context.new_page()

        for brand in HYATT_BRAND_SLUGS:
            url = f"https://www.hyatt.com/brands/{brand}"
            logger.info(f"Visiting official brand page: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=35000)
                page.wait_for_timeout(3000)

                # Extract all hotel links
                links = page.query_selector_all("a[href*='/hotel/'], a[href*='/alila/'], a[href*='/andaz/'], a[href*='/park-hyatt/'], a[href*='/grand-hyatt/'], a[href*='/hyatt-regency/'], a[href*='/thompson-hotels/'], a[href*='/hyatt-centric/'], a[href*='/hyatt-place/'], a[href*='/hyatt-house/'], a[href*='/unbound-collection/'], a[href*='/jdv-by-hyatt/'], a[href*='/destination-by-hyatt/'], a[href*='/all-inclusive/']")
                
                brand_hotel_count = 0
                for a in links:
                    href = a.get_attribute("href") or ""
                    text = a.inner_text().strip()
                    if href.startswith("/"):
                        href = f"https://www.hyatt.com{href}"
                    
                    if len(text) > 3 and "hyatt.com" in href and not any(k in href for k in ["/offers/", "/dining/", "/meetings/", "/events/", "/terms", "/privacy"]):
                        if href not in extracted_hotels:
                            extracted_hotels[href] = {
                                "name": text.split("\n")[0].strip(),
                                "url": href,
                                "brand": brand
                            }
                            brand_hotel_count += 1

                logger.info(f"Extracted {brand_hotel_count} official hotels from {brand} page. Total so far: {len(extracted_hotels)}")
            except Exception as e:
                logger.error(f"Error scraping brand {brand}: {e}")

            time.sleep(1.0)

        # Also try Hyatt locations directory
        dest_url = "https://www.hyatt.com/en-US/explore-hotels/locations"
        logger.info(f"Visiting global locations directory: {dest_url}")
        try:
            page.goto(dest_url, wait_until="domcontentloaded", timeout=35000)
            page.wait_for_timeout(4000)
            links = page.query_selector_all("a[href*='/hotel/']")
            for a in links:
                href = a.get_attribute("href") or ""
                text = a.inner_text().strip()
                if href.startswith("/"):
                    href = f"https://www.hyatt.com{href}"
                if len(text) > 3 and href not in extracted_hotels:
                    extracted_hotels[href] = {
                        "name": text.split("\n")[0].strip(),
                        "url": href,
                        "brand": "hyatt"
                    }
        except Exception as e:
            logger.error(f"Error scraping locations page: {e}")

        page.close()
        context.close()

    logger.info(f"Extraction complete! Total official Hyatt hotels extracted: {len(extracted_hotels)}")
    with open("hyatt_official_directory.json", "w", encoding="utf-8") as f:
        json.dump(extracted_hotels, f, indent=2, ensure_ascii=False)

if __name__ == '__main__':
    scrape_hyatt_brand_locations()
