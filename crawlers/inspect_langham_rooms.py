import sys
import json
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def inspect_langham_rooms():
    url = "https://reservations.brilliantbylangham.com/default/booking/rooms?adult=1&arrive=2026-10-15&chain=10316&child=0&depart=2026-10-16&hotel=32509&rooms=1"
    print(f"[*] Navigating directly to Langham Rooms page: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(url, wait_until="domcontentloaded", timeout=35000)
        page.wait_for_timeout(6000)

        # Accept cookie if any
        try:
            btn = page.query_selector("#onetrust-accept-btn-handler, button:has-text('Accept')")
            if btn:
                btn.click()
                page.wait_for_timeout(2000)
        except:
            pass

        # Extract all room cards and prices
        room_data = page.evaluate("""() => {
            const results = [];
            // Find all room containers
            const containers = document.querySelectorAll('[class*=\"RoomItem\"], [class*=\"room-item\"], [class*=\"RoomCard\"], [class*=\"roomCard\"], [class*=\"room_item\"]');
            if (containers.length > 0) {
                containers.forEach(c => results.push(c.innerText.trim()));
            } else {
                // Fallback: extract all headings and price elements
                document.querySelectorAll('h2, h3, h4, [class*=\"Title\"], [class*=\"price\"], [class*=\"Price\"]').forEach(el => {
                    const t = el.innerText ? el.innerText.trim() : '';
                    if (t.length > 0 && t.length < 200 && !results.includes(t)) results.push(t);
                });
            }
            return results;
        }""")

        print(f"\n✅ Ditemukan {len(room_data)} data kartu kamar dari DOM Langham Jakarta:")
        for idx, r in enumerate(room_data[:15], 1):
            print(f"--- [ITEM #{idx}] ---")
            print(r)

        browser.close()

if __name__ == "__main__":
    inspect_langham_rooms()
