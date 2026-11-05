import os
import re
from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_hyatt_full")

def inspect_hyatt_dom():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/Chicago",
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            ignore_default_args=["--enable-automation"],
        )
        page = context.new_page()
        page.goto("https://www.hyatt.com/explore-hotels/map", wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(4000)

        html = page.content()
        print(f"HTML length: {len(html)} bytes")
        
        # Look for JSON scripts
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
        print(f"Found {len(scripts)} scripts")
        for s in scripts:
            if "properties" in s.lower() or "hotel" in s.lower() or "spirit" in s.lower():
                print(f"Script match ({len(s)} chars): {s[:250]}...")

        links = re.findall(r'href="([^"]+)"', html)
        hotel_links = [l for l in links if any(k in l for k in ["/hotel/", "/alila/", "/andaz/", "/park-hyatt/", "/grand-hyatt/", "/hyatt-regency/", "/hyatt-place/", "/hyatt-house/"])]
        print(f"Found {len(hotel_links)} hotel links in DOM:")
        for l in hotel_links[:10]:
            print("  •", l)

        page.close()
        context.close()

if __name__ == '__main__':
    inspect_hyatt_dom()
