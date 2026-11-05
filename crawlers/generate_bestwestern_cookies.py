import os
import sys
import json
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSION_DIR = os.path.join(BASE_DIR, "crawlers", "pw_bestwestern_session")
os.makedirs(SESSION_DIR, exist_ok=True)
COOKIE_FILE = os.path.join(SESSION_DIR, "bestwestern_cookies.json")

print("=" * 65)
print("  BEST WESTERN (DATADOME) SESSION GENERATOR")
print("  Opening visible browser for manual/auto DataDome clearance...")
print("=" * 65)

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        channel="msedge",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--start-maximized"
        ]
    )
    context = browser.new_context(
        no_viewport=True,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    print("\nNavigating to https://www.bestwestern.com ...")
    page.goto("https://www.bestwestern.com/en_US.html", timeout=60000)
    
    print("\n[ACTION REQUIRED] If a DataDome slider or verification appears on your screen, please complete it.")
    print("Waiting up to 60 seconds for cookies...")
    
    datadome_found = False
    for i in range(30):
        page.wait_for_timeout(2000)
        cookies = context.cookies()
        dd_cookie = next((c for c in cookies if c["name"].lower() == "datadome"), None)
        if dd_cookie:
            print(f"\n[SUCCESS] Captured DataDome Cookie: {dd_cookie['value'][:30]}...")
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)
            print(f"Saved session cookies to: {COOKIE_FILE}")
            datadome_found = True
            break
        print(f"  Waiting... ({i*2}/60s)")
        
    if not datadome_found:
        print("\n[WARN] Timeout reached without capturing datadome cookie.")
        
    browser.close()
    print("\nBrowser closed. Session generation complete.")
