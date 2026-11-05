import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def debug_langham_dom():
    url = "https://reservations.brilliantbylangham.com/default/booking/rooms?adult=1&arrive=2026-10-15&chain=10316&child=0&depart=2026-10-16&hotel=32509&rooms=1"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=40000)
        page.wait_for_timeout(4000)

        # Print all visible button and link texts
        elements = page.evaluate("""() => {
            const list = [];
            document.querySelectorAll('button, a, h1, h2, h3, p, span').forEach(el => {
                const t = el.innerText ? el.innerText.trim() : '';
                if (t && t.length < 100 && !list.includes(t)) list.push(t);
            });
            return list;
        }""")
        print(f"[*] Found {len(elements)} visible text items on Langham booking page:")
        for e in elements[:30]:
            print("  - ", e)

        browser.close()

if __name__ == "__main__":
    debug_langham_dom()
