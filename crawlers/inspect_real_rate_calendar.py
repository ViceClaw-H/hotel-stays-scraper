import json
import re
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def inspect_calendar_flow():
    print("==================================================")
    print("🔍 Menginspeksi Network Request Kalender Tarif Resmi")
    print("==================================================")

    captured_apis = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        def handle_response(response):
            url = response.url
            if any(k in url.lower() for k in ["rate", "avail", "calendar", "price", "room", "search", "synxis"]):
                try:
                    if "json" in response.headers.get("content-type", ""):
                        body = response.text()
                        captured_apis.append({
                            "url": url,
                            "status": response.status,
                            "body_sample": body[:300]
                        })
                except Exception:
                    pass

        page.on("response", handle_response)

        # 1. Test Shangri-La Jakarta Booking Page
        shang_url = "https://www.shangri-la.com/en/jakarta/shangrila/"
        print(f"[*] Mengakses {shang_url}...")
        try:
            page.goto(shang_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)
        except Exception as e:
            print("Error visiting Shangri-La:", e)

        print(f"\n[*] Captured {len(captured_apis)} rate/pricing API endpoints:")
        for api in captured_apis[:10]:
            print(f"  -> [{api['status']}] {api['url'][:100]}")
            print(f"     Body: {api['body_sample'][:150]}...\n")

        browser.close()

if __name__ == "__main__":
    inspect_calendar_flow()
