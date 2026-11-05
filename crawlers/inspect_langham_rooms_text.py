import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def inspect_langham_default_rooms():
    url = "https://reservations.brilliantbylangham.com/?chain=10316&hotel=32509"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=40000)
        page.wait_for_timeout(5000)

        # Remove OneTrust
        page.evaluate("""() => {
            const ot = document.getElementById('onetrust-consent-sdk');
            if (ot) ot.remove();
        }""")

        # Get all text content within the main booking view
        text = page.evaluate("""() => {
            const elements = Array.from(document.querySelectorAll('div, section, p, h2, h3, h4, span, button'));
            return elements.map(e => e.innerText.trim()).filter(t => t.length > 5 && t.length < 150);
        }""")

        print("All text blocks on Langham rooms page:")
        unique_text = []
        for t in text:
            if t not in unique_text and not any(k in t.lower() for k in ['cookie', 'privacy', 'onetrust', 'terms']):
                unique_text.append(t)

        for u in unique_text:
            print("  •", u)

        browser.close()

if __name__ == "__main__":
    inspect_langham_default_rooms()
