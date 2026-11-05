import sys
import os
import time
import json
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("capture_accor_search_api")

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_accor_search")

def capture_api():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="Asia/Singapore",
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            ignore_default_args=["--enable-automation"],
        )
        page = context.new_page()

        captured_requests = []
        def on_req(req):
            if any(k in req.url.lower() for k in ["suggest", "autocomplete", "search", "geo", "destination", "algolia"]):
                captured_requests.append({"url": req.url, "method": req.method})

        page.on("request", on_req)

        logger.info("Navigating to all.accor.com...")
        page.goto("https://all.accor.com/a/en.html", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)

        # Focus input and type letter by letter
        search_selector = "input[name='search.destination.userlang']"
        page.click(search_selector)
        page.type(search_selector, "Singapore", delay=150)
        page.wait_for_timeout(3000)

        logger.info(f"Captured {len(captured_requests)} candidate search API requests:")
        for cr in captured_requests:
            logger.info(f"  [{cr['method']}] {cr['url']}")

        page.close()
        context.close()

if __name__ == '__main__':
    capture_api()
