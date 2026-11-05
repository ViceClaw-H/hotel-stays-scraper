import os
import re
import json
from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_hyatt_dev")

def extract_hyatt_development_hotels():
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
            if "json" in response.headers.get("content-type", "") or "hotels" in response.url or "development" in response.url:
                try:
                    text = response.text()
                    if "propertyName" in text or "hotelName" in text or "propertyCode" in text or "brand" in text:
                        captured_apis.append((response.url, text))
                        print(f"Captured API from {response.url} ({len(text)} bytes)")
                except:
                    pass

        page.on("response", on_response)

        url = "https://www.hyatt.com/development/explore-hotels/"
        print(f"Visiting: {url}")
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(5000)
            print(f"Title: {page.title()}")

            # Extract any property cards or table rows in the DOM
            html = page.content()
            print(f"DOM Length: {len(html)} bytes")

            # Look for property names or items in DOM
            hotels = page.evaluate("""() => {
                const list = [];
                // Look for table rows, cards, or list items
                const rows = document.querySelectorAll('tr, .hotel-card, .property-card, [data-testid*="hotel"], [data-testid*="property"]');
                for (const r of rows) {
                    const text = r.innerText ? r.innerText.trim() : '';
                    if (text.length > 5) {
                        list.push(text);
                    }
                }
                return list;
            }""")

            print(f"Extracted {len(hotels)} candidate DOM items from explore-hotels.")
            for h in hotels[:10]:
                print("  •", h.replace("\n", " | "))

            if captured_apis:
                for u, t in captured_apis:
                    with open("hyatt_dev_captured.json", "w", encoding="utf-8") as f:
                        f.write(t)
                    print(f"Saved captured API payload to hyatt_dev_captured.json")

        except Exception as e:
            print(f"Error: {e}")

        page.close()
        context.close()

if __name__ == '__main__':
    extract_hyatt_development_hotels()
