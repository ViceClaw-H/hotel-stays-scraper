import os
import re
import json
import time
from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_accor_calendar")

def inspect_accor_calendar():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            viewport={"width": 1366, "height": 768},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            ignore_default_args=["--enable-automation"],
        )
        page = context.new_page()

        captured_apis = []
        def on_response(response):
            u = response.url
            if any(k in u for k in ["api", "calendar", "price", "rate", "offer", "availability", "search", "hotel", "graphql"]):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct or "text" in ct:
                        t = response.text()
                        if len(t) > 100:
                            captured_apis.append((u, t))
                            print(f"Captured: {u[:100]}... ({len(t)} bytes)")
                except:
                    pass

        page.on("response", on_response)

        url = "https://all.accor.com/booking/id/accor/hotels/indonesia?dateIn=2026-09-03&nights=1"
        print(f"Navigating to {url}...")
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)

        print(f"Title: {page.title()} | Total API calls captured: {len(captured_apis)}")

        # Look for "Lihat kalender harga" button
        cal_btn = page.query_selector("button:has-text('kalender harga'), a:has-text('kalender harga'), [data-testid*='calendar'], button:has-text('calendar')")
        if cal_btn:
            print(f"Found 'Lihat kalender harga' button! Clicking it...")
            cal_btn.click()
            page.wait_for_timeout(6000)

        # Save all captured JSON responses to inspect
        for idx, (u, t) in enumerate(captured_apis):
            fn = f"accor_captured_{idx}.json"
            try:
                js = json.loads(t)
                with open(fn, "w", encoding="utf-8") as f:
                    json.dump({"url": u, "data": js}, f, indent=2, ensure_ascii=False)
                print(f"Saved JSON payload to {fn} (from {u[:80]})")
            except:
                pass

        page.close()
        context.close()

if __name__ == '__main__':
    inspect_accor_calendar()
