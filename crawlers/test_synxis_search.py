import json
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def test_synxis_search():
    # Pass dates to SynXis
    url = "https://reservations.brilliantbylangham.com/?chain=10316&hotel=32509&arrive=2026-10-15&depart=2026-10-16&adult=1&child=0&rooms=1"
    print(f"[*] Navigating to SynXis search with dates: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        captured_apis = []

        def handle_res(res):
            u = res.url
            if any(k in u.lower() for k in ["api", "rate", "avail", "hotel", "room", "ari"]):
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
        page.wait_for_timeout(8000)

        print(f"\n[*] Captured {len(captured_apis)} JSON API responses during search:")
        for item in captured_apis:
            print(f"\n-> [{item['status']}] URL: {item['url']}")
            # If it contains room or rate info, print it in detail
            s = json.dumps(item['data'])
            print(f"   Payload snippet: {s[:300]}...")

        # Also extract room elements rendered on page
        rooms_on_page = page.evaluate("""() => {
            const results = [];
            document.querySelectorAll('[data-testid*=\"room\"], .room-card, .room-type, [class*=\"RoomCard\"]').forEach(el => {
                results.push(el.innerText.trim());
            });
            if (results.length === 0) {
                // Try finding all price / title text
                document.querySelectorAll('h2, h3, h4, .price, [class*=\"price\"]').forEach(el => {
                    if (el.innerText) results.push(el.innerText.trim());
                });
            }
            return results;
        }""")
        print(f"\n[*] Extracted elements from DOM ({len(rooms_on_page)} items):")
        for r in rooms_on_page[:10]:
            print("  - ", r.replace('\n', ' | '))

        browser.close()

if __name__ == "__main__":
    test_synxis_search()
