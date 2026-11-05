import json
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def test_ihg_interactive_search():
    url = "https://www.ihg.com/intercontinental/hotels/us/en/jakarta/jktha/hoteldetail"
    print(f"[*] Navigating to IHG Property Detail: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        captured = []

        def handle_res(res):
            u = res.url
            if any(k in u.lower() for k in ["rate", "room", "price", "avail", "hotel", "offers", "graphql", "api"]):
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
        page.wait_for_timeout(4000)

        # Accept cookie
        try:
            btn = page.query_selector("#onetrust-accept-btn-handler, button:has-text('Accept All')")
            if btn:
                btn.click()
                page.wait_for_timeout(2000)
        except Exception:
            pass

        # Look for "Book Now" or "Check Availability" button
        book_btn = page.query_selector("a:has-text('Book'), button:has-text('Book'), a:has-text('Check Rates'), button:has-text('Check Rates')")
        if book_btn:
            print(f"[*] Found Book/Rates button: {book_btn.inner_text().strip()}")
            book_btn.click()
            page.wait_for_timeout(5000)

        print(f"\n[*] Captured {len(captured)} JSON responses on IHG:")
        for item in captured[:10]:
            print(f"-> [{item['status']}] {item['url'][:120]}")
            s = json.dumps(item['data'])[:250]
            print(f"   Payload: {s}...\n")

        browser.close()

if __name__ == "__main__":
    test_ihg_interactive_search()
