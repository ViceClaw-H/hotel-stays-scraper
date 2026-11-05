import json
import re
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def inspect_langham_and_ihg():
    print("==================================================")
    print("🔍 Inspeksi Struktur Booking Engine & Kalender Tarif")
    print("==================================================")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        captured = []
        def on_response(res):
            u = res.url
            if any(k in u.lower() for k in ["synxis", "rate", "calendar", "avail", "offers", "rooms"]):
                try:
                    ct = res.headers.get("content-type", "")
                    if "json" in ct or "javascript" in ct:
                        captured.append({"url": u, "status": res.status, "text": res.text()[:250]})
                except:
                    pass
        page.on("response", on_response)

        # 1. Langham Booking Flow
        print("[*] Navigasi ke Langham Jakarta...")
        page.goto("https://www.langhamhotels.com/en/the-langham/jakarta/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)

        # Look for Book Now button or SynXis link
        links = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href], button')).map(el => ({
                tag: el.tagName,
                text: el.innerText ? el.innerText.trim() : '',
                href: el.href || ''
            })).filter(x => x.text.toLowerCase().includes('book') || x.href.includes('synxis') || x.href.includes('reservation'));
        }""")
        print(f"[*] Langham booking buttons/links ({len(links)}):")
        for l in links[:5]:
            print("  ", l)

        browser.close()

if __name__ == "__main__":
    inspect_langham_and_ihg()
