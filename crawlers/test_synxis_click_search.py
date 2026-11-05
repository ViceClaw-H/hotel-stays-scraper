import json
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def test_synxis_click_search():
    url = "https://reservations.brilliantbylangham.com/?chain=10316&hotel=32509"
    print(f"[*] Visiting SynXis Langham Jakarta: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        captured_requests = []

        def handle_req(req):
            if any(k in req.url.lower() for k in ["rate", "avail", "ari", "graphql", "synxis", "room", "search"]):
                captured_requests.append({
                    "url": req.url,
                    "method": req.method,
                    "post_data": req.post_data
                })

        page.on("request", handle_req)

        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)

        # Accept cookie
        try:
            btn = page.query_selector("#onetrust-accept-btn-handler, button:has-text('Accept')")
            if btn:
                btn.click()
                page.wait_for_timeout(2000)
        except:
            pass

        # Look for search or find rates button
        search_btn = page.query_selector("button:has-text('SEARCH'), button:has-text('Search'), button:has-text('Check'), button:has-text('Find')")
        if search_btn:
            print(f"[*] Clicking Search Button: {search_btn.inner_text().strip()}")
            search_btn.click()
            page.wait_for_timeout(6000)

        print(f"\n[*] Captured {len(captured_requests)} requests during interaction:")
        for r in captured_requests:
            print(f"-> [{r['method']}] {r['url'][:120]}")
            if r['post_data']:
                print(f"   Payload: {r['post_data'][:200]}...")

        # Extract DOM
        dom_text = page.evaluate("""() => {
            const list = [];
            document.querySelectorAll('h1, h2, h3, h4, .price, [class*=\"price\"], [class*=\"Room\"], [class*=\"room\"]').forEach(el => {
                const t = el.innerText ? el.innerText.trim() : '';
                if (t && (t.includes('IDR') || t.includes('Deluxe') || t.includes('King') || t.includes('Executive') || t.includes('Suite'))) {
                    if (t.length < 200 && !list.includes(t)) list.push(t);
                }
            });
            return list;
        }""")
        print(f"\n[*] DOM extracted rooms ({len(dom_text)}):")
        for dt in dom_text[:10]:
            print("  • ", dt)

        browser.close()

if __name__ == "__main__":
    test_synxis_click_search()
