import sys
import json
import re
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def capture_hyatt_network():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
            viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()

        captured_json_urls = []

        def handle_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct and any(k in response.url for k in ["explore", "hotels", "properties", "search", "graphql"]):
                    print(f"[Captured API] {response.url[:120]}")
                    captured_json_urls.append(response.url)
            except Exception:
                pass

        page.on("response", handle_response)

        print("[*] Mengakses https://www.hyatt.com/explore-hotels...")
        page.goto("https://www.hyatt.com/explore-hotels", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(5000)

        print(f"[*] Total API JSON Ditangkap: {len(captured_json_urls)}")
        browser.close()

if __name__ == "__main__":
    capture_hyatt_network()
