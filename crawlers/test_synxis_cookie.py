import json
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def test_synxis_with_cookie_accept():
    url = "https://reservations.brilliantbylangham.com/?chain=10316&hotel=32509&arrive=2026-10-15&depart=2026-10-16&adult=1&child=0&rooms=1"
    print(f"[*] Navigating to SynXis Langham Jakarta: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        graphql_queries = []

        def handle_res(res):
            u = res.url
            if "graphql" in u.lower() or "availability" in u.lower() or "calendar" in u.lower():
                try:
                    if "json" in res.headers.get("content-type", ""):
                        data = res.json()
                        graphql_queries.append({
                            "url": u,
                            "status": res.status,
                            "data": data
                        })
                except Exception:
                    pass

        page.on("response", handle_res)

        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        # Accept cookie banner if present
        try:
            btn = page.query_selector("#onetrust-accept-btn-handler, button:has-text('Accept All'), button:has-text('Accept')")
            if btn:
                print("[*] Clicking cookie accept button...")
                btn.click()
                page.wait_for_timeout(3000)
        except Exception as e:
            print("Cookie error:", e)

        page.wait_for_timeout(5000)

        print(f"\n[*] Captured {len(graphql_queries)} GraphQL / Availability API responses:")
        for q in graphql_queries:
            print(f"\n-> [{q['status']}] {q['url']}")
            keys = list(q['data'].keys()) if isinstance(q['data'], dict) else "array"
            print(f"   Root keys: {keys}")
            # Print sample content
            s = json.dumps(q['data'])
            print(f"   Data sample: {s[:350]}...")

        # Find room cards
        rooms = page.evaluate("""() => {
            const list = [];
            document.querySelectorAll('[class*=\"room\"], [class*=\"Room\"], [class*=\"card\"], [class*=\"Card\"]').forEach(el => {
                const text = el.innerText ? el.innerText.trim() : '';
                if (text.includes('IDR') || text.includes('Rp') || text.includes('$') || text.includes('Night') || text.includes('Deluxe') || text.includes('King')) {
                    if (text.length < 300 && !list.includes(text)) {
                        list.push(text);
                    }
                }
            });
            return list;
        }""")
        print(f"\n[*] Extracted Room Data from DOM ({len(rooms)} cards):")
        for r in rooms[:10]:
            print("---")
            print(r)

        browser.close()

if __name__ == "__main__":
    test_synxis_with_cookie_accept()
