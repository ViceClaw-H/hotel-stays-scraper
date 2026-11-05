import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def test_langham_with_stealth():
    url = "https://reservations.brilliantbylangham.com/?chain=10316&hotel=32509&arrive=2026-10-15&depart=2026-10-16&adult=1&child=0&rooms=1"
    print(f"[*] Testing Langham with Bot Stealth on: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="en-US"
        )
        page = context.new_page()

        # Stealth JS patch
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)

        captured = []
        page.on("response", lambda r: captured.append(r.url) if any(k in r.url.lower() for k in ["rate", "avail", "room", "offers", "ari"]) else None)

        page.goto(url, wait_until="networkidle", timeout=40000)
        page.wait_for_timeout(6000)

        # Remove OneTrust
        page.evaluate("""() => {
            const ot = document.getElementById('onetrust-consent-sdk');
            if (ot) ot.remove();
        }""")

        # Extract text nodes
        text_nodes = page.evaluate("""() => {
            const list = [];
            document.querySelectorAll('h1, h2, h3, h4, span, div, p').forEach(el => {
                const t = el.innerText ? el.innerText.trim() : '';
                if ((t.includes('Deluxe') || t.includes('King') || t.includes('Executive') || t.includes('Suite') || t.includes('Superior')) &&
                    (t.includes('IDR') || t.includes('Rp') || t.includes('Book') || t.includes('Night') || t.includes('from') || t.includes('sqm'))) {
                    if (t.length > 20 && t.length < 300 && !list.includes(t)) {
                        list.push(t);
                    }
                }
            });
            return list;
        }""")

        print(f"\n[*] Captured {len(captured)} pricing/ARI network calls.")
        for u in captured[:5]:
            print("  ->", u[:100])

        print(f"\n✅ Extracted {len(text_nodes)} Real Langham Room Cards & Rates:")
        for tn in text_nodes[:15]:
            print("---")
            print(tn)

        browser.close()

if __name__ == "__main__":
    test_langham_with_stealth()
