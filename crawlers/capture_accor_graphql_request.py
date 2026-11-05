import os
import json
from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_accor_live")

def capture_accor_request():
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

        requests_log = []
        def on_request(request):
            u = request.url
            if "graphql" in u or "bff/v1" in u:
                post_data = request.post_data
                headers = request.headers
                requests_log.append({
                    "url": u,
                    "method": request.method,
                    "headers": headers,
                    "post_data": post_data
                })
                print(f"Captured Request to: {u} (method: {request.method})")

        page.on("request", on_request)

        url = "https://all.accor.com/booking/id/accor/hotels/indonesia?dateIn=2026-09-03&nights=1"
        page.goto(url, wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(6000)

        # Save requests log
        with open("accor_graphql_requests.json", "w", encoding="utf-8") as f:
            json.dump(requests_log, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(requests_log)} requests to accor_graphql_requests.json!")

        page.close()
        context.close()

if __name__ == '__main__':
    capture_accor_request()
