import sys
import json
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def test_langham_state():
    url = "https://reservations.brilliantbylangham.com/default/booking/rooms?adult=1&arrive=2026-10-15&chain=10316&child=0&depart=2026-10-16&hotel=32509&rooms=1"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=40000)
        page.wait_for_timeout(8000)

        # Check RTK Query / Redux / Next data
        data = page.evaluate("""() => {
            const result = {};
            if (window.__NEXT_DATA__) {
                result.page = window.__NEXT_DATA__.page;
                result.query = window.__NEXT_DATA__.query;
            }
            if (window.lhg_data) {
                result.lhg_data = window.lhg_data;
            }
            // Check all room titles rendered
            const rooms = [];
            document.querySelectorAll('[data-testid*=\"room\"], [class*=\"room\"], [class*=\"Room\"]').forEach(el => {
                if (el.innerText && el.innerText.length < 200) {
                    rooms.push(el.innerText.trim());
                }
            });
            result.dom_rooms = rooms;
            return result;
        }""")

        print("Extracted State & Data:\n", json.dumps(data, indent=2))
        browser.close()

if __name__ == "__main__":
    test_langham_state()
