import os
import json
import time
from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_accor_calendar_modal")

def capture_accor_calendar_modal():
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

        calendar_requests = []
        def on_request(request):
            u = request.url
            if any(k in u for k in ["calendar", "graphql", "prices", "availability", "rates"]):
                calendar_requests.append({
                    "url": u,
                    "method": request.method,
                    "headers": request.headers,
                    "post_data": request.post_data
                })

        calendar_responses = []
        def on_response(response):
            u = response.url
            if any(k in u for k in ["calendar", "graphql", "prices", "availability", "rates"]):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct or "text" in ct:
                        t = response.text()
                        if len(t) > 100:
                            calendar_responses.append((u, t))
                            print(f"Captured: {u[:90]}... ({len(t)} bytes)")
                except:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        url = "https://all.accor.com/booking/id/accor/hotels/indonesia?dateIn=2026-09-03&nights=1"
        print(f"Navigating to {url}...")
        page.goto(url, wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(4000)

        # Handle cookie banner
        try:
            accept_btn = page.query_selector("#onetrust-accept-btn-handler")
            if accept_btn:
                accept_btn.click()
                page.wait_for_timeout(1000)
        except:
            pass

        print("Waiting for hotel cards to load...")
        page.wait_for_timeout(6000)

        # Find and click "Lihat kalender harga"
        print("Looking for 'Lihat kalender harga' link...")
        cal_links = page.query_selector_all("a:has-text('Lihat kalender harga'), button:has-text('Lihat kalender harga'), [data-testid*='calendar']")
        print(f"Found {len(cal_links)} calendar links.")
        if cal_links:
            print("Clicking 'Lihat kalender harga'...")
            cal_links[0].click()
            page.wait_for_timeout(8000)

        # Save all captured calendar data
        with open("accor_calendar_requests.json", "w", encoding="utf-8") as f:
            json.dump(calendar_requests, f, indent=2, ensure_ascii=False)
        
        for idx, (u, t) in enumerate(calendar_responses):
            with open(f"accor_cal_resp_{idx}.json", "w", encoding="utf-8") as f:
                f.write(t)

        print("Captured and saved calendar modal API traffic successfully!")
        page.close()
        context.close()

if __name__ == '__main__':
    capture_accor_calendar_modal()
