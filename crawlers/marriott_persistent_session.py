import os
import sys
import time
import json
import re
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROFILE_DIR = os.path.join(os.getcwd(), "crawlers", "pw_marriott_session")
os.makedirs(PROFILE_DIR, exist_ok=True)

COOKIE_FILE = os.path.join(PROFILE_DIR, "marriott_cookies.json")

def init_marriott_persistent_session(headless=True):
    """
    Launches Chromium with persistent user profile to establish a valid Akamai session (_abck ~0).
    Saves the session cookies for automated reuse.
    """
    print("===============================================================")
    print("🚀 INITIALIZING MARRIOTT PERSISTENT BROWSER SESSION")
    print("===============================================================")
    print(f"[*] Profile Directory: {PROFILE_DIR}")

    stealth = Stealth()

    with sync_playwright() as p:
        # Launch persistent context
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=headless,
            channel="chrome" if os.path.exists("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe") else None,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--start-maximized"
            ],
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US"
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        stealth.apply_stealth_sync(page)

        # 1. Navigate to Marriott Homepage
        print("[1/3] Loading Marriott Homepage...")
        page.goto("https://www.marriott.com/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)

        # 2. Check for cookie consent
        try:
            accept_btn = page.query_selector("#onetrust-accept-btn-handler, button:has-text('Accept All')")
            if accept_btn:
                print("[*] Accepting cookies...")
                accept_btn.click()
                page.wait_for_timeout(2000)
        except Exception:
            pass

        # 3. Navigate to The St. Regis Jakarta (jktxr)
        target_url = "https://www.marriott.com/en-us/hotels/jktxr-the-st-regis-jakarta/overview/"
        print(f"[2/3] Navigating to target hotel: {target_url}...")
        resp = page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)

        print(f"[*] Page Title: {page.title()}")
        print(f"[*] HTTP Status: {resp.status if resp else 'N/A'}")

        # 4. Extract and analyze cookies
        cookies = context.cookies()
        abck = next((c for c in cookies if c["name"] == "_abck"), None)
        
        if abck:
            print(f"[*] Akamai Cookie `_abck` value: {abck['value'][:40]}...")
            if "~0~" in abck["value"] or abck["value"].endswith("~0"):
                print("    ✅ SUCCESS: Akamai session is VERIFIED (~0)!")
            else:
                print("    ⚠️ Status: Akamai challenge pending (~-1).")

        # Save cookies to disk
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2)
        print(f"[*] Saved {len(cookies)} cookies to {COOKIE_FILE}")

        # 5. Check if room rates / price cards are rendered
        body_text = page.inner_text("body")
        prices = re.findall(r'(?:IDR|Rp\.?|USD|\$)\s*([\d\.,]+)', body_text)
        print(f"\n[3/3] Live Prices Detected on Screen: {len(prices)}")
        if prices:
            print(f"      Sample Rates: {prices[:6]}")

        context.close()

if __name__ == "__main__":
    init_marriott_persistent_session(headless=False)
