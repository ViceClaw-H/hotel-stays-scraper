import os
import re
import json
import time
from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_accor_live")

def capture_accor_graphql():
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

        captured = []
        def on_response(response):
            u = response.url
            if "graphql" in u or "availability" in u or "calendar" in u or "bff/v1" in u:
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct or "text" in ct:
                        t = response.text()
                        if len(t) > 100:
                            idx = len(captured)
                            captured.append((u, t))
                            fn = f"accor_graphql_{idx}.json"
                            try:
                                js = json.loads(t)
                                with open(fn, "w", encoding="utf-8") as f:
                                    json.dump({"url": u, "data": js}, f, indent=2, ensure_ascii=False)
                                print(f"Saved: {fn} ({len(t)} bytes) from {u[:80]}")
                            except Exception as ex:
                                print(f"Failed to parse json: {ex}")
                except:
                    pass

        page.on("response", on_response)

        url = "https://all.accor.com/booking/id/accor/hotels/indonesia?dateIn=2026-09-03&nights=1"
        print(f"Navigating to {url}...")
        page.goto(url, wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(3000)

        # Dismiss OneTrust cookie banner if present
        try:
            accept_btn = page.query_selector("#onetrust-accept-btn-handler, button:has-text('Terima semua'), button:has-text('Accept')")
            if accept_btn:
                print("Accepting cookies...")
                accept_btn.click()
                page.wait_for_timeout(2000)
        except:
            pass

        print("Waiting for GraphQL hotel results...")
        page.wait_for_timeout(8000)

        # Click on the first "Lihat kalender harga" button
        try:
            cal_btns = page.query_selector_all("a:has-text('kalender harga'), button:has-text('kalender harga'), [data-testid*='calendar']")
            print(f"Found {len(cal_btns)} 'Lihat kalender harga' buttons.")
            if cal_btns:
                print("Clicking first 'Lihat kalender harga' button...")
                cal_btns[0].click()
                page.wait_for_timeout(6000)
        except Exception as e:
            print(f"Error clicking calendar button: {e}")

        page.close()
        context.close()

if __name__ == '__main__':
    capture_accor_graphql()
