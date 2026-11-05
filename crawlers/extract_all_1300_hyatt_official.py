"""Hyatt Global Directory Extractor using Playwright.
Extracts the complete official directory of Hyatt properties directly from hyatt.com.
"""
import sys
import os
import json
import sqlite3
import re
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = "hotel_stays.db"

def extract_hyatt_official():
    print("=======================================================")
    print("🚀 Membuka Browser Playwright untuk Menarik Direktori Resmi Hyatt")
    print("=======================================================\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
            viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()

        # Try explore hotels directory
        url = "https://www.hyatt.com/explore-hotels"
        print(f"[*] Mengakses {url}...")
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)

        print(f"[*] Judul Halaman: {page.title()}")

        # Extract all property links
        links = page.eval_on_selector_all("a[href]", """
            elements => elements.map(el => ({
                text: el.innerText.trim(),
                href: el.href
            }))
        """)

        print(f"[*] Total Link Ditemukan: {len(links)}")

        hotel_properties = []
        seen_urls = set()

        for link in links:
            href = link["href"]
            text = link["text"]

            # Match authentic Hyatt hotel pattern: /brand/en-US/xxxxx-hotel-name
            match = re.search(r'hyatt\.com/([a-z\-]+)/en-US/([a-z0-9]{5}-[a-z0-9\-]+)', href)
            if match and href not in seen_urls:
                seen_urls.add(href)
                brand_slug = match.group(1)
                full_code = match.group(2)
                prop_code = full_code[:5]

                hotel_properties.append({
                    "name": text or full_code[6:].replace("-", " ").title(),
                    "brand": brand_slug.replace("-", " ").title(),
                    "code": prop_code,
                    "url": href
                })

        print(f"✅ Berhasil Mengekstrak {len(hotel_properties)} Hotel Hyatt Resmi dari Web!")
        for hp in hotel_properties[:15]:
            print(f"  • [{hp['code']}] {hp['name']} -> {hp['url']}")

        browser.close()
        return hotel_properties

if __name__ == "__main__":
    extract_hyatt_official()
