import os
import re
import json
import time
from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_gha_map")

def capture_gha_map():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/New_York",
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            ignore_default_args=["--enable-automation"],
        )
        page = context.new_page()

        captured_data = []
        def on_response(response):
            u = response.url
            if any(k in u for k in ["hotels", "properties", "destinations", "mapbox", "geojson", "search"]):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct or "text" in ct:
                        t = response.text()
                        if len(t) > 200:
                            captured_data.append((u, t))
                            print(f"Captured: {u} ({len(t)} bytes)")
                except:
                    pass

        page.on("response", on_response)

        url = "https://www.ghadiscovery.com/destinations-map"
        print(f"Navigating to {url}...")
        page.goto(url, wait_until="networkidle", timeout=50000)
        page.wait_for_timeout(6000)

        print(f"Title: {page.title()} | Total API responses captured: {len(captured_data)}")

        # Also extract any hotel links from DOM
        links = page.evaluate("""() => {
            const list = [];
            const els = document.querySelectorAll('a');
            for (const el of els) {
                const href = el.href || '';
                const text = el.innerText ? el.innerText.trim() : '';
                if (href.includes('ghadiscovery.com') && text.length > 3) {
                    list.push({ text, href });
                }
            }
            return list;
        }""")

        print(f"Found {len(links)} candidate links in DOM.")
        for l in links[:15]:
            print("  •", l["text"], "->", l["href"])

        if captured_data:
            for idx, (u, t) in enumerate(captured_data):
                with open(f"gha_captured_{idx}.json", "w", encoding="utf-8") as f:
                    f.write(t)
                print(f"Saved {u} to gha_captured_{idx}.json")

        page.close()
        context.close()

if __name__ == '__main__':
    capture_gha_map()
