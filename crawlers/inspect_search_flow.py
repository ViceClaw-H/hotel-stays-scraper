import sys
import os
import json
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("inspect_search_flow")

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_accor_search")

def test_full_search(country_name: str = "Singapore"):
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

        api_responses = []
        def on_resp(resp):
            if any(k in resp.url.lower() for k in ["rates", "hotel", "search", "availability", "properties", "destination"]):
                if "json" in resp.headers.get("content-type", ""):
                    try:
                        api_responses.append({"url": resp.url, "status": resp.status})
                    except:
                        pass

        page.on("response", on_resp)

        logger.info("Loading Accor homepage...")
        page.goto("https://all.accor.com/a/en.html", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        # Accept cookies
        try:
            btn = page.query_selector("#onetrust-accept-btn-handler")
            if btn:
                btn.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass

        search_input = "input[name='search.destination.userlang']"
        page.click(search_input)
        page.type(search_input, country_name, delay=100)
        page.wait_for_timeout(2500)

        # Click the dropdown prediction item
        # Try clicking anywhere in the autocomplete container
        try:
            # Look for prediction items
            pred = page.wait_for_selector(".c-autocomplete__item, .autocomplete-item, [role='option'], div:has-text('Singapore')", timeout=4000)
            if pred:
                logger.info(f"Clicking pred: {pred.inner_text()[:40]}...")
                pred.click()
                page.wait_for_timeout(1500)
        except Exception as e:
            logger.warning(f"Could not click pred: {e}")

        # Now click search button
        try:
            submit_btn = page.query_selector("button[type='submit'], button[data-testid='search-button'], button:has-text('Search')")
            if submit_btn:
                logger.info("Clicking submit button...")
                submit_btn.click()
                page.wait_for_timeout(7000)
        except Exception as e:
            logger.warning(f"Submit error: {e}")

        logger.info(f"Landed URL: {page.url}")
        logger.info(f"Captured {len(api_responses)} JSON API responses:")
        for ar in api_responses:
            logger.info(f"  API: {ar['url']}")

        page.close()
        context.close()

if __name__ == '__main__':
    test_full_search("Singapore")
