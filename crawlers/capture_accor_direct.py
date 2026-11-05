import json
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def capture_accor_direct_booking():
    url = "https://all.accor.com/booking/en/accor/hotel/8967?dateIn=2026-10-15&nights=1&compositions=1"
    print(f"[*] Navigating to: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        captured_graphql = []

        def on_res(res):
            u = res.url
            if "graphql" in u or "offer" in u or "room" in u or "rate" in u:
                try:
                    if "json" in res.headers.get("content-type", ""):
                        data = res.json()
                        captured_graphql.append({
                            "url": u,
                            "status": res.status,
                            "req_headers": dict(res.request.headers),
                            "post_data": res.request.post_data,
                            "data": data
                        })
                except Exception:
                    pass

        page.on("response", on_res)

        page.goto(url, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(5000)

        # Accept cookie
        try:
            btn = page.query_selector("#onetrust-accept-btn-handler, button:has-text('Accept All')")
            if btn:
                btn.click()
                page.wait_for_timeout(3000)
        except Exception:
            pass

        page.wait_for_timeout(5000)

        print(f"\n[*] Captured {len(captured_graphql)} rate/graphql responses:")
        for cg in captured_graphql:
            print(f"\n-> [{cg['status']}] {cg['url']}")
            sample_data = json.dumps(cg['data'])[:350]
            print(f"   Data: {sample_data}...")

        # Extract room text and prices
        dom_text = page.evaluate("""() => {
            const list = [];
            document.querySelectorAll('h3, h4, [class*=\"room\"], [class*=\"Room\"], [class*=\"Price\"], [class*=\"price\"]').forEach(el => {
                const t = el.innerText ? el.innerText.trim() : '';
                if (t && t.length < 150 && !list.includes(t)) {
                    list.push(t);
                }
            });
            return list;
        }""")
        print(f"\n[*] Extracted DOM elements ({len(dom_text)}):")
        for t in dom_text[:15]:
            print("  - ", t)

        browser.close()

if __name__ == "__main__":
    capture_accor_direct_booking()
