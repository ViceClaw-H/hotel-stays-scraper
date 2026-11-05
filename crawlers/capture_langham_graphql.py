import json
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def capture_synxis_queries():
    url = "https://reservations.brilliantbylangham.com/?chain=10316&hotel=32509&arrive=2026-10-15&depart=2026-10-16&adult=1&child=0&rooms=1"
    print(f"[*] Capturing exact GraphQL POST queries on: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        captured_requests = []

        def handle_req(req):
            if "graphql" in req.url:
                try:
                    captured_requests.append({
                        "url": req.url,
                        "method": req.method,
                        "headers": req.headers,
                        "post_data": req.post_data
                    })
                except Exception:
                    pass

        page.on("request", handle_req)

        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(6000)

        print(f"\n[*] Captured {len(captured_requests)} GraphQL Requests:")
        for idx, cr in enumerate(captured_requests, 1):
            print(f"\n--- REQUEST #{idx} ---")
            print("URL:", cr["url"])
            print("Method:", cr["method"])
            if cr["post_data"]:
                try:
                    pd = json.loads(cr["post_data"])
                    print("Operation Name:", pd.get("operationName"))
                    print("Variables:", json.dumps(pd.get("variables"), indent=2))
                    print("Query snippet:\n", pd.get("query", "")[:250])
                except:
                    print("Raw Post Data:", cr["post_data"][:250])

        browser.close()

if __name__ == "__main__":
    capture_synxis_queries()
