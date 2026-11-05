import json
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def test_synxis_booking():
    url = "https://reservations.brilliantbylangham.com/?chain=10316&config=brilliant&theme=brilliant&hotel=32509&level=hotel"
    print(f"[*] Visiting Langham Sabre SynXis Booking Engine: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        captured_apis = []

        def handle_res(res):
            u = res.url
            if "api" in u.lower() or "calendar" in u.lower() or "rates" in u.lower() or "availability" in u.lower() or "synxis" in u.lower():
                try:
                    ct = res.headers.get("content-type", "")
                    if "json" in ct:
                        captured_apis.append({
                            "url": u,
                            "status": res.status,
                            "data": res.json()
                        })
                except Exception:
                    pass

        page.on("response", handle_res)

        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(6000)

        print(f"\n[*] Captured {len(captured_apis)} JSON API responses:")
        for item in captured_apis:
            print(f"\n-> [{item['status']}] URL: {item['url']}")
            sample_str = json.dumps(item['data'], indent=2)[:350]
            print(f"   Payload: {sample_str}...")

        browser.close()

if __name__ == "__main__":
    test_synxis_booking()
