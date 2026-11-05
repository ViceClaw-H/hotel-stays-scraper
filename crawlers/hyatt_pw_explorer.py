import os
import sys
import json
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hyatt_pw_explorer")

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_hyatt")

def explore_hyatt_official():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/Chicago",
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            ignore_default_args=["--enable-automation"],
        )
        page = context.new_page()

        captured_apis = []
        def on_response(response):
            if any(k in response.url.lower() for k in ["explore", "hotels", "properties", "locations", "sitemap", "directory"]):
                if "json" in response.headers.get("content-type", ""):
                    try:
                        captured_apis.append({"url": response.url, "status": response.status})
                    except:
                        pass

        page.on("response", on_response)

        logger.info("Opening Hyatt explore hotels directory...")
        page.goto("https://www.hyatt.com/en-US/explore-hotels", wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(5000)

        logger.info(f"Page Title: {page.title()}")
        logger.info(f"Page URL: {page.url}")
        
        # Check page content & headings
        body_text = page.inner_text("body")
        logger.info(f"Body text length: {len(body_text)} chars")
        
        logger.info(f"Captured {len(captured_apis)} JSON API responses during explore page load:")
        for ca in captured_apis[:15]:
            logger.info(f"  • {ca['url'][:140]}")

        # Check for hotel cards / links
        hotel_links = page.query_selector_all("a[href*='/hotel/'], a[href*='/park-hyatt/'], a[href*='/grand-hyatt/'], a[href*='/andaz/'], a[href*='/alila/'], a[href*='/hyatt-regency/'], a[href*='/thompson-hotels/'], a[href*='/hyatt-centric/'], a[href*='/hyatt-place/'], a[href*='/hyatt-house/']")
        logger.info(f"Found {len(hotel_links)} official brand hotel links on page.")

        # Save HTML snapshot for inspection
        with open("hyatt_explore_snapshot.html", "w", encoding="utf-8") as f:
            f.write(page.content())

        page.close()
        context.close()

if __name__ == '__main__':
    explore_hyatt_official()
