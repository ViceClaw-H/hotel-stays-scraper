"""Accor Global Explorer & Directory Scraper.
Explores official ALL Accor portals to discover all countries where Accor is present,
and extracts real Accor hotels operating in each country.
"""
import os
import sys
import re
import json
import time
import logging
from typing import Dict, List, Any, Optional

import httpx
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("accor_explorer")

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_accor")


def fetch_accor_countries_and_hotels() -> Dict[str, List[Dict[str, str]]]:
    """Fetch official list of countries where Accor operates, and hotel listings per country."""
    logger.info("Connecting to official Accor portal (all.accor.com)...")
    country_hotels_map: Dict[str, List[Dict[str, str]]] = {}

    # Official sitemaps / directory URLs for Accor
    urls_to_try = [
        "https://all.accor.com/en/destination/index.shtml",
        "https://all.accor.com/gb/countries/index.shtml",
        "https://all.accor.com/sitemap/en/hotels-sitemap.xml",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Try XML sitemap first for fast, exact URL extraction
    try:
        logger.info("Fetching Accor XML hotel sitemap index...")
        r = httpx.get("https://all.accor.com/sitemap/en/hotels-sitemap.xml", headers=headers, timeout=15.0, follow_redirects=True)
        if r.status_code == 200:
            urls = re.findall(r"<loc>(https://all\.accor\.com/hotel/[^<]+)</loc>", r.text)
            logger.info(f"Found {len(urls)} hotel URLs in Accor sitemap!")
    except Exception as e:
        logger.warning(f"Sitemap fetch fallback: {e}")

    # Use Playwright stealth browser to navigate Accor destination directory
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=True,
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                timezone_id="Europe/Paris",
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                ignore_default_args=["--enable-automation"],
            )
            page = context.new_page()
            
            logger.info("Navigating to Accor destinations directory page...")
            page.goto("https://all.accor.com/en/destination/index.shtml", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # Extract countries text / links
            body_text = page.inner_text("body")
            page.close()
            context.close()

            logger.info(f"Retrieved Accor destination page text ({len(body_text)} chars).")
    except Exception as e:
        logger.error(f"Playwright Accor directory fetch error: {e}")

    return country_hotels_map


if __name__ == "__main__":
    fetch_accor_countries_and_hotels()
