import os
import re
import json
from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_shang_106")

def scrape_shangrila_all_106():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="Asia/Singapore",
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            ignore_default_args=["--enable-automation"],
        )
        page = context.new_page()

        url = "https://www.shangri-la.com/en/find-a-hotel/"
        print(f"Visiting: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(4000)

        # Extract all hotel elements/links
        links = page.query_selector_all("a[href*='/shangrila/'], a[href*='/hoteljen/'], a[href*='/kerry/'], a[href*='/traders/'], a[href*='/resort/']")
        print(f"Found {len(links)} candidate links on page.")

        hotels = {}
        for a in links:
            href = a.get_attribute("href") or ""
            text = a.inner_text().strip()
            if href.startswith("/"):
                href = f"https://www.shangri-la.com{href}"
            if len(text) > 3 and not any(k in href for k in ["/dining", "/offers", "/meetings", "/weddings", "/about", "/press", "/terms", "/privacy"]):
                clean_name = text.split("\n")[0].strip()
                if clean_name not in hotels:
                    hotels[clean_name] = href

        # If not enough links via standard selector, evaluate page DOM for all destination cards
        cards = page.evaluate("""() => {
            const results = [];
            const elements = document.querySelectorAll('a');
            for (const el of elements) {
                const text = el.innerText ? el.innerText.trim() : '';
                const href = el.href || '';
                if (href.includes('shang-ri-la.com') || href.includes('shangri-la.com/en/')) {
                    if (text.length > 3 && (text.includes('Shangri-La') || text.includes('JEN') || text.includes('Kerry') || text.includes('Traders') || text.includes('Hotel'))) {
                        results.push({ name: text.split('\\n')[0], url: href });
                    }
                }
            }
            return results;
        }""")

        for c in cards:
            name = c["name"]
            url = c["url"]
            if name not in hotels and not any(k in url for k in ["/dining", "/offers", "/meetings", "/terms", "/privacy"]):
                hotels[name] = url

        print(f"Extracted {len(hotels)} unique Shangri-La Group properties!")
        for n, u in list(hotels.items())[:20]:
            print(f"  • {n} -> {u}")

        with open("shangrila_106_extracted.json", "w", encoding="utf-8") as f:
            json.dump(hotels, f, indent=2, ensure_ascii=False)

        page.close()
        context.close()

if __name__ == '__main__':
    scrape_shangrila_all_106()
