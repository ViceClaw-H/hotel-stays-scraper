import json
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def test_ihg_live_search():
    url = "https://www.ihg.com/intercontinental/hotels/us/en/find-hotels/hotel/rooms?qDest=Jakarta,%20Indonesia&qCiMy=92026&qCiD=15&qCoMy=92026&qCoD=16&qAdlt=1&qChld=0&qRms=1&qRtP=6CBARC&qIta=99502025&qSlH=JKTHA&qAkModel=false&qAAR=6CBARC&qRtP=6CBARC&setPMCookies=true&qRad=30&qRdU=mi&srhPresId=false"
    print(f"[*] Navigating to IHG live search: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        captured = []

        def handle_res(res):
            u = res.url
            if any(k in u.lower() for k in ["rate", "room", "price", "avail", "hotel", "offers", "graphql"]):
                try:
                    ct = res.headers.get("content-type", "")
                    if "json" in ct:
                        captured.append({
                            "url": u,
                            "status": res.status,
                            "data": res.json()
                        })
                except Exception:
                    pass

        page.on("response", handle_res)

        page.goto(url, wait_until="domcontentloaded", timeout=35000)
        page.wait_for_timeout(8000)

        # Accept cookie
        try:
            btn = page.query_selector("#onetrust-accept-btn-handler, button:has-text('Accept All')")
            if btn:
                btn.click()
                page.wait_for_timeout(3000)
        except Exception:
            pass

        print(f"\n[*] Captured {len(captured)} JSON responses on IHG:")
        for item in captured:
            print(f"-> [{item['status']}] {item['url'][:120]}")
            s = json.dumps(item['data'])[:250]
            print(f"   Payload snippet: {s}...\n")

        # Extract DOM rooms
        dom_rooms = page.evaluate("""() => {
            const list = [];
            document.querySelectorAll('[data-testid*=\"room\"], [class*=\"room-card\"], [class*=\"RoomCard\"], h3, h4').forEach(el => {
                const t = el.innerText ? el.innerText.trim() : '';
                if (t && (t.includes('Classic') || t.includes('King') || t.includes('Suite') || t.includes('IDR') || t.includes('Rp') || t.includes('Deluxe'))) {
                    if (t.length < 150 && !list.includes(t)) list.push(t);
                }
            });
            return list;
        }""")
        print(f"\n[*] Extracted IHG DOM elements ({len(dom_rooms)}):")
        for r in dom_rooms[:10]:
            print("  - ", r)

        browser.close()

if __name__ == "__main__":
    test_ihg_live_search()
