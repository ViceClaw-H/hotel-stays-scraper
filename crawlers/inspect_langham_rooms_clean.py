import sys
import json
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def extract_langham_actual_rooms():
    url = "https://reservations.brilliantbylangham.com/default/booking/rooms?adult=1&arrive=2026-10-15&chain=10316&child=0&depart=2026-10-16&hotel=32509&rooms=1"
    print(f"[*] Navigating to: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        page.goto(url, wait_until="networkidle", timeout=40000)
        page.wait_for_timeout(3000)

        # Remove or accept OneTrust cookie overlay
        page.evaluate("""() => {
            const el = document.getElementById('onetrust-consent-sdk');
            if (el) el.remove();
            const dark = document.querySelector('.onetrust-pc-dark-filter');
            if (dark) dark.remove();
        }""")
        page.wait_for_timeout(4000)

        # Extract all text and room cards
        rooms = page.evaluate("""() => {
            const list = [];
            document.querySelectorAll('div, section, article').forEach(el => {
                const t = el.innerText ? el.innerText.trim() : '';
                // Check if this container represents a distinct room card
                if ((t.includes('Deluxe') || t.includes('Executive') || t.includes('Suite') || t.includes('King')) &&
                    (t.includes('IDR') || t.includes('Rp') || t.includes('/ Night') || t.includes('night') || t.includes('Book'))) {
                    if (t.length > 30 && t.length < 500 && !list.some(existing => existing.includes(t) || t.includes(existing))) {
                        list.push(t);
                    }
                }
            });
            return list;
        }""")

        print(f"\n✅ Total Kartu Kamar & Harga Riil Ditemukan: {len(rooms)}\n")
        for idx, r in enumerate(rooms, 1):
            print(f"================== KAMAR #{idx} ==================")
            print(r)
            print()

        browser.close()

if __name__ == "__main__":
    extract_langham_actual_rooms()
