import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def debug_ihg_booking():
    url = "https://www.ihg.com/intercontinental/hotels/us/en/jakarta/jktha/hoteldetail"
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)

        page.goto(url, wait_until="domcontentloaded", timeout=35000)
        page.wait_for_timeout(4000)

        # Remove OneTrust
        page.evaluate("""() => {
            const el = document.getElementById('onetrust-consent-sdk');
            if (el) el.remove();
        }""")

        # Extract all buttons and links on page
        interactive = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a, button')).map(el => ({
                tag: el.tagName,
                text: el.innerText ? el.innerText.trim() : '',
                href: el.href || ''
            })).filter(x => x.text.length > 2 && x.text.length < 50);
        }""")

        print(f"[*] Found {len(interactive)} interactive elements on IHG detail page:")
        for it in interactive[:20]:
            print("  - ", it)

        browser.close()

if __name__ == "__main__":
    debug_ihg_booking()
