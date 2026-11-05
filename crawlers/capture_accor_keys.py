import json
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def capture_fresh_accor_keys():
    print("[*] Launching browser to capture fresh Accor GraphQL headers & API key...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        captured = []

        def handle_req(req):
            if "graphql" in req.url:
                captured.append({
                    "url": req.url,
                    "headers": req.headers,
                    "post_data": req.post_data
                })

        page.on("request", handle_req)

        page.goto("https://all.accor.com/hotel/8967/index.en.shtml", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)

        print(f"[*] Captured {len(captured)} GraphQL requests on page:")
        for item in captured:
            print("URL:", item["url"])
            print("Headers:", json.dumps(item["headers"], indent=2))
            if item["post_data"]:
                print("Post data snippet:", item["post_data"][:200])

        browser.close()

if __name__ == "__main__":
    capture_fresh_accor_keys()
