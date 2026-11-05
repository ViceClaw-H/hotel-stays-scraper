import json
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def test_langham_search_flow():
    url = "https://reservations.brilliantbylangham.com/?chain=10316&hotel=32509&arrive=2026-10-15&depart=2026-10-16&adult=1&child=0&rooms=1"
    print(f"[*] Visiting SynXis Langham Jakarta with dates: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        captured_calls = []

        def handle_res(res):
            u = res.url
            if any(k in u.lower() for k in ["synxis", "api", "graphql", "rates", "avail", "hotel"]):
                try:
                    if "json" in res.headers.get("content-type", ""):
                        captured_calls.append({
                            "url": u,
                            "status": res.status,
                            "req_body": res.request.post_data,
                            "res_data": res.json()
                        })
                except Exception:
                    pass

        page.on("response", handle_res)

        page.goto(url, wait_until="networkidle", timeout=40000)
        page.wait_for_timeout(5000)

        print(f"\n[*] Captured {len(captured_calls)} JSON responses:")
        for c in captured_calls:
            print(f"-> [{c['status']}] {c['url']}")
            if c['req_body']:
                print("   Request Post Data:", c['req_body'][:150])
            s = json.dumps(c['res_data'])[:200]
            print(f"   Response Data: {s}...\n")

        browser.close()

if __name__ == "__main__":
    test_langham_search_flow()
