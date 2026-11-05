import json
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def test_wyndham_rates():
    url = "https://www.wyndhamhotels.com/wyndham/jakarta-indonesia/wyndham-casablanca-jakarta/rooms-rates?brand_id=WY&hotel_id=52458&checkin_date=10/15/2026&checkout_date=10/16/2026&rooms=1&adults=1&children=0"
    print(f"[*] Navigating to Wyndham rooms & rates: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        captured_apis = []

        def on_res(res):
            u = res.url
            if any(k in u.lower() for k in ["api", "rate", "avail", "room", "price"]):
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

        page.on("response", on_res)

        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(8000)

        print(f"\n[*] Captured {len(captured_apis)} JSON API responses:")
        for a in captured_apis:
            print(f"-> [{a['status']}] {a['url'][:120]}")
            s = json.dumps(a['data'])[:250]
            print(f"   Payload: {s}...\n")

        # Extract DOM text
        rooms = page.evaluate("""() => {
            const list = [];
            document.querySelectorAll('h3, h4, .room-title, .rate-price, [class*=\"room-name\"], [class*=\"price\"]').forEach(el => {
                const t = el.innerText ? el.innerText.trim() : '';
                if (t && t.length < 150 && !list.includes(t)) {
                    list.push(t);
                }
            });
            return list;
        }""")
        print(f"\n[*] Extracted DOM elements ({len(rooms)}):")
        for r in rooms[:12]:
            print("  - ", r)

        browser.close()

if __name__ == "__main__":
    test_wyndham_rates()
