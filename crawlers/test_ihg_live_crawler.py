import json
import re
import sys
from datetime import date, timedelta
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def test_ihg_live_rate_search(hotel_code="JKTHA", checkin_date=None):
    if checkin_date is None:
        checkin_date = date.today() + timedelta(days=14)
    checkout_date = checkin_date + timedelta(days=1)

    ci_month_year = f"{checkin_date.month:02d}{checkin_date.year}"
    ci_day = str(checkin_date.day)
    co_month_year = f"{checkout_date.month:02d}{checkout_date.year}"
    co_day = str(checkout_date.day)

    url = (
        f"https://www.ihg.com/intercontinental/hotels/us/en/find-hotels/hotel/rooms?"
        f"qDest=Jakarta,%20Indonesia&qCiMy={ci_month_year}&qCiD={ci_day}&"
        f"qCoMy={co_month_year}&qCoD={co_day}&qAdlt=1&qChld=0&qRms=1&"
        f"qRtP=6CBARC&qSlH={hotel_code}&qAkModel=false&qAAR=6CBARC&"
        f"setPMCookies=true&qRad=30&qRdU=mi&srhPresId=false"
    )

    print(f"[*] Navigating to IHG live search URL:\n{url}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="en-US"
        )
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)

        captured_apis = []
        def on_res(res):
            u = res.url
            if any(k in u.lower() for k in ["rate", "room", "price", "avail", "offers", "graphql", "hotel"]):
                try:
                    if "json" in res.headers.get("content-type", ""):
                        captured_apis.append({"url": u, "status": res.status, "data": res.json()})
                except:
                    pass
        page.on("response", on_res)

        page.goto(url, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(4000)

        # Remove OneTrust cookie banner
        page.evaluate("""() => {
            const el = document.getElementById('onetrust-consent-sdk');
            if (el) el.remove();
        }""")
        page.wait_for_timeout(2000)

        # Extract all room cards from DOM
        room_cards = page.evaluate("""() => {
            const results = [];
            // Target room cards on IHG
            document.querySelectorAll('[data-testid*=\"room\"], [class*=\"room-card\"], [class*=\"RoomCard\"], [class*=\"roomType\"], [class*=\"hotel-room\"]').forEach(el => {
                const t = el.innerText ? el.innerText.trim() : '';
                if (t.length > 20 && !results.some(existing => existing.includes(t) || t.includes(existing))) {
                    results.push(t);
                }
            });
            if (results.length === 0) {
                // Fallback: search containers with price text
                document.querySelectorAll('div, section, article').forEach(el => {
                    const t = el.innerText ? el.innerText.trim() : '';
                    if ((t.includes('Classic') || t.includes('King') || t.includes('Twin') || t.includes('Suite') || t.includes('Premium')) &&
                        (t.includes('IDR') || t.includes('Rp') || t.includes('/ night') || t.includes('Select') || t.includes('from'))) {
                        if (t.length > 30 && t.length < 400 && !results.some(existing => existing.includes(t) || t.includes(existing))) {
                            results.push(t);
                        }
                    }
                });
            }
            return results;
        }""")

        print(f"[*] Captured {len(captured_apis)} JSON API responses.")
        for a in captured_apis[:5]:
            print("  API URL:", a["url"][:100])

        print(f"\n✅ Extracted {len(room_cards)} Room Cards from IHG DOM:")
        for idx, rc in enumerate(room_cards[:10], 1):
            print(f"\n--- [IHG ROOM #{idx}] ---")
            print(rc)

        browser.close()

if __name__ == "__main__":
    test_ihg_live_rate_search("JKTHA")
