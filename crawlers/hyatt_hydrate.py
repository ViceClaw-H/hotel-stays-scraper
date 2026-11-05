import os
import sys
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hyatt_hydrate")

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_hyatt")

def hydrate_hyatt():
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

        logger.info("Navigating to Hyatt explore hotels...")
        page.goto("https://www.hyatt.com/en-US/explore-hotels", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)

        logger.info(f"Page Title after networkidle: {page.title()}")
        body_text = page.inner_text("body")
        logger.info(f"Body text length: {len(body_text)} chars")
        lines = [l.strip() for l in body_text.split("\n") if l.strip()]
        logger.info(f"First 25 lines:")
        for l in lines[:25]:
            logger.info(f"  * {l}")

        # Check links
        links = page.query_selector_all("a")
        logger.info(f"Total links found: {len(links)}")
        hotel_links = []
        for a in links:
            href = a.get_attribute("href") or ""
            text = a.inner_text().strip()
            if any(b in href.lower() for b in ["park-hyatt", "grand-hyatt", "andaz", "alila", "hyatt-regency", "thompson", "hyatt-centric", "hyatt-place", "hyatt-house", "hotel"]):
                hotel_links.append((text, href))

        logger.info(f"Extracted {len(hotel_links)} Hyatt hotel links:")
        for txt, href in hotel_links[:20]:
            logger.info(f"  • {txt} -> {href}")

        page.close()
        context.close()

if __name__ == '__main__':
    hydrate_hyatt()
