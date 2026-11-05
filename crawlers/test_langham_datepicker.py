import sys
import json
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def test_langham_interactive_datepicker():
    url = "https://reservations.brilliantbylangham.com/?chain=10316&hotel=32509"
    print(f"[*] Navigating to Langham Jakarta booking portal: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="domcontentloaded", timeout=35000)
        page.wait_for_timeout(4000)

        # Remove OneTrust
        page.evaluate("""() => {
            const ot = document.getElementById('onetrust-consent-sdk');
            if (ot) ot.remove();
        }""")

        # Look for the datepicker button / input
        date_btn = page.query_selector("[class*=\"date\"], [class*=\"Date\"], [data-testid*=\"date\"], button:has-text('Check-in'), div:has-text('Dates')")
        if date_btn:
            print(f"[*] Clicking date element: {date_btn.inner_text()[:40]}")
            date_btn.click()
            page.wait_for_timeout(2000)

        # Click Search button
        search_btn = page.query_selector("button:has-text('SEARCH'), button:has-text('Search'), button:has-text('CHECK RATES'), button:has-text('Check rates')")
        if search_btn:
            print(f"[*] Clicking Search: {search_btn.inner_text()}")
            search_btn.click()
            page.wait_for_timeout(8000)

        # Check all visible room items
        cards = page.evaluate("""() => {
            const list = [];
            document.querySelectorAll('*').forEach(el => {
                const t = el.innerText ? el.innerText.trim() : '';
                if ((t.includes('Deluxe') || t.includes('Executive') || t.includes('Suite') || t.includes('King')) &&
                    (t.includes('IDR') || t.includes('Rp') || t.includes('Night') || t.includes('USD'))) {
                    if (t.length > 20 && t.length < 300 && !list.includes(t)) {
                        list.push(t);
                    }
                }
            });
            return list;
        }""")

        print(f"\n✅ Extracted {len(cards)} live room cards:")
        for c in cards[:10]:
            print("---")
            print(c)

        browser.close()

if __name__ == "__main__":
    test_langham_interactive_datepicker()
