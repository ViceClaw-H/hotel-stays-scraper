import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def extract_langham_rooms_inner():
    url = "https://reservations.brilliantbylangham.com/default/booking/rooms?adult=1&arrive=2026-10-15&chain=10316&child=0&depart=2026-10-16&hotel=32509&rooms=1"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=40000)
        page.wait_for_timeout(5000)

        # Extract all text blocks inside main section
        room_cards = page.evaluate("""() => {
            const list = [];
            // Target all cards / containers after "Select Room"
            const allElements = document.querySelectorAll('*');
            allElements.forEach(el => {
                if (el.children.length === 0 && el.innerText && el.innerText.trim().length > 0) {
                    list.push(el.innerText.trim());
                }
            });
            return list;
        }""")
        print(f"[*] Found {len(room_cards)} leaf text nodes:")
        # Filter relevant strings
        relevant = [t for t in room_cards if any(k in t.lower() for k in ['deluxe', 'suite', 'king', 'idr', 'rp', 'night', 'price', 'room', 'view', 'bed'])]
        for r in relevant[:30]:
            print("  • ", r)

        browser.close()

if __name__ == "__main__":
    extract_langham_rooms_inner()
