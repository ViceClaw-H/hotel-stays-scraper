import json
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def capture_accor_search():
    print("[*] Launching browser to search Accor rates...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        captured_responses = []

        def handle_res(res):
            u = res.url
            if any(k in u.lower() for k in ["api", "offer", "rate", "calendar", "graphql", "booking"]):
                try:
                    ct = res.headers.get("content-type", "")
                    if "json" in ct:
                        captured_responses.append({
                            "url": u,
                            "status": res.status,
                            "headers": dict(res.request.headers),
                            "post_data": res.request.post_data
                        })
                except Exception:
                    pass

        page.on("response", handle_res)

        # Accor booking URL with dates
        url = "https://all.accor.com/ssr/app/accor/rates/8967/index.en.shtml?dateIn=2026-10-15&nights=1&compositions=1&stayplus=false&snu=false&accessibleRooms=false&hideHotelDetails=false"
        print(f"[*] Navigating to Accor SSR rates: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(8000)

        # Accept cookie if any
        try:
            btn = page.query_selector("#onetrust-accept-btn-handler, button:has-text('Accept All')")
            if btn:
                btn.click()
                page.wait_for_timeout(3000)
        except Exception:
            pass

        print(f"\n[*] Captured {len(captured_responses)} API responses on SSR booking page:")
        for cr in captured_responses:
            print(f"\n-> [{cr['status']}] {cr['url'][:120]}")
            if "apikey" in cr["headers"] or "authorization" in cr["headers"] or "x-api-key" in cr["headers"]:
                print("   API Key header found! Headers:", {k: v for k, v in cr["headers"].items() if 'key' in k.lower() or 'auth' in k.lower() or 'app' in k.lower()})

        # Also extract room names and prices from DOM
        dom_rooms = page.evaluate("""() => {
            const list = [];
            document.querySelectorAll('[data-testid*=\"room\"], [class*=\"room\"], [class*=\"Room\"], [class*=\"offer\"], [class*=\"Offer\"]').forEach(el => {
                const txt = el.innerText ? el.innerText.trim() : '';
                if (txt.includes('IDR') || txt.includes('Rp') || txt.includes('Deluxe') || txt.includes('Superior') || txt.includes('Standard') || txt.includes('Suite')) {
                    if (txt.length < 250 && !list.includes(txt)) {
                        list.push(txt);
                    }
                }
            });
            return list;
        }""")
        print(f"\n[*] Extracted {len(dom_rooms)} room rate cards from DOM:")
        for r in dom_rooms[:8]:
            print("---")
            print(r)

        browser.close()

if __name__ == "__main__":
    capture_accor_search()
