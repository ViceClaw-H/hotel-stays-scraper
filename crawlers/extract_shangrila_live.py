import os
import sys
import re
import json
import sqlite3

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from curl_cffi import requests

def extract_and_verify_shangrila():
    print("==================================================")
    print("🚀 Extracting Official Shangri-La Global Directory")
    print("==================================================")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US"
        )

        url = "https://www.shangri-la.com/en/find-a-hotel/"
        print(f"[*] Visiting {url}...")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)

        # Extract all hotel links
        raw_hotels = page.evaluate("""() => {
            const list = [];
            const links = Array.from(document.querySelectorAll('a[href]'));
            for (const a of links) {
                const href = a.href;
                const text = a.innerText ? a.innerText.trim() : '';
                if (href.match(/shangri-la\\.com\\/en\\/[a-z0-9\\-]+\\/[a-z0-9\\-]+\\/?$/) &&
                    !href.includes('/landing/') &&
                    !href.includes('/find-a-hotel') &&
                    !href.includes('/corporate') &&
                    !href.includes('/contact-us') &&
                    !href.includes('/privacy-policy') &&
                    !href.includes('/terms-and-conditions')) {
                    
                    list.push({
                        name: text.split('\\n')[0].trim(),
                        url: href
                    });
                }
            }
            return list;
        }""")
        browser.close()

    print(f"[*] Extracted {len(raw_hotels)} candidate Shangri-La links from official page.")

    # Deduplicate by canonical URL
    unique_hotels = {}
    for h in raw_hotels:
        u = h["url"].rstrip("/") + "/"
        name = h["name"]
        if u not in unique_hotels and len(name) > 3 and not any(k in name.lower() for k in ["find a hotel", "explore", "offers"]):
            unique_hotels[u] = name

    print(f"[*] Unique Official Hotel Properties: {len(unique_hotels)}")

    # Known city-country-currency mapping for Shangri-La locations
    LOCATION_MAP = {
        # Indonesia
        "jakarta": ("Jakarta", "Indonesia", "IDR", "Asia"),
        "surabaya": ("Surabaya", "Indonesia", "IDR", "Asia"),
        "bali": ("Bali", "Indonesia", "IDR", "Asia"),
        
        # Singapore
        "singapore": ("Singapore", "Singapore", "SGD", "Asia"),
        
        # Malaysia
        "kualalumpur": ("Kuala Lumpur", "Malaysia", "MYR", "Asia"),
        "penang": ("Penang", "Malaysia", "MYR", "Asia"),
        "kotakinabalu": ("Kota Kinabalu", "Malaysia", "MYR", "Asia"),
        "johor": ("Johor Bahru", "Malaysia", "MYR", "Asia"),
        
        # Thailand
        "bangkok": ("Bangkok", "Thailand", "THB", "Asia"),
        "chiangmai": ("Chiang Mai", "Thailand", "THB", "Asia"),
        
        # Philippines
        "manila": ("Manila", "Philippines", "PHP", "Asia"),
        "cebu": ("Cebu", "Philippines", "PHP", "Asia"),
        "boracay": ("Boracay", "Philippines", "PHP", "Asia"),
        
        # Cambodia
        "phnompenh": ("Phnom Penh", "Cambodia", "USD", "Asia"),
        
        # Myanmar
        "yangon": ("Yangon", "Myanmar", "USD", "Asia"),
        
        # Sri Lanka
        "colombo": ("Colombo", "Sri Lanka", "LKR", "Asia"),
        "hambantota": ("Hambantota", "Sri Lanka", "LKR", "Asia"),
        
        # Maldives
        "male": ("Male", "Maldives", "USD", "Asia"),
        "villingili": ("Villingili", "Maldives", "USD", "Asia"),
        
        # Japan
        "tokyo": ("Tokyo", "Japan", "JPY", "Asia"),
        "kyoto": ("Kyoto", "Japan", "JPY", "Asia"),
        
        # India
        "newdelhi": ("New Delhi", "India", "INR", "Asia"),
        "bengaluru": ("Bengaluru", "India", "INR", "Asia"),
        
        # China / Hong Kong / Taiwan / Mongolia
        "hongkong": ("Hong Kong", "Hong Kong", "HKD", "Asia"),
        "taipei": ("Taipei", "Taiwan", "TWD", "Asia"),
        "tainan": ("Tainan", "Taiwan", "TWD", "Asia"),
        "ulaanbaatar": ("Ulaanbaatar", "Mongolia", "USD", "Asia"),
        
        # Europe & Middle East
        "london": ("London", "United Kingdom", "GBP", "Europe"),
        "paris": ("Paris", "France", "EUR", "Europe"),
        "istanbul": ("Istanbul", "Turkey", "USD", "Europe"),
        "dubai": ("Dubai", "United Arab Emirates", "AED", "Middle East"),
        "abudhabi": ("Abu Dhabi", "United Arab Emirates", "AED", "Middle East"),
        "jeddah": ("Jeddah", "Saudi Arabia", "SAR", "Middle East"),
        "muscat": ("Muscat", "Oman", "OMR", "Middle East"),
        
        # Australia & Pacific
        "sydney": ("Sydney", "Australia", "AUD", "Oceania"),
        "cairns": ("Cairns", "Australia", "AUD", "Oceania"),
        "fiji": ("Yanuca Island", "Fiji", "FJD", "Oceania"),
        "yanucaisland": ("Yanuca Island", "Fiji", "FJD", "Oceania"),
        
        # North America & Africa
        "vancouver": ("Vancouver", "Canada", "CAD", "Americas"),
        "toronto": ("Toronto", "Canada", "CAD", "Americas"),
        "mauritius": ("Trou d'Eau Douce", "Mauritius", "USD", "Africa")
    }

    # Verify every URL with live HTTP request (ZERO 404s allowed)
    verified_hotels = []
    print("\n[*] Testing live HTTP status for every Shangri-La hotel URL...")
    
    session = requests.Session()
    session.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

    count = 0
    for url, name in unique_hotels.items():
        count += 1
        m = re.search(r'shangri-la\.com/en/([^/]+)/([^/]+)/', url)
        city_slug = m.group(1).lower() if m else "global"
        brand_slug = m.group(2).lower() if m else "shangrila"

        # Lookup location or infer from city_slug
        if city_slug in LOCATION_MAP:
            city, country, curr, region = LOCATION_MAP[city_slug]
        else:
            # China domestic cities default
            city = city_slug.capitalize()
            country = "China"
            curr = "CNY"
            region = "Asia"

        # Test live URL
        try:
            r = session.get(url, impersonate="chrome124", timeout=15)
            status = r.status_code
        except Exception as e:
            status = f"Err: {e}"

        if status == 200 or status in [301, 302, 307, 308]:
            verified_hotels.append({
                "id": f"shang_{city_slug}_{brand_slug}",
                "brand": "SHANGRI-LA",
                "name": name,
                "city": city,
                "country": country,
                "region": region,
                "currency": curr,
                "url": url,
                "status": status
            })
            print(f"  [{count:03d}] HTTP {status} OK | {name} | {city}, {country} ({region}) -> {url}")
        else:
            print(f"  ❌ [{count:03d}] HTTP {status} FAILED | {url}")
            sys.exit(f"ABORT: 404/Error encountered on {url}!")

    print(f"\n✅ 100% of Shangri-La properties ({len(verified_hotels)}) verified LIVE with 0 errors / 0 404s!")

    # Ingest into SQLite database
    conn = sqlite3.connect("hotel_stays.db")
    c = conn.cursor()
    c.execute("DELETE FROM hotels WHERE brand = 'SHANGRI-LA'")

    for h in verified_hotels:
        c.execute("""
            INSERT OR REPLACE INTO hotels (id, brand, name, city, country, currency, loyalty_model, award_category, track_points, official_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (h["id"], h["brand"], h["name"], h["city"], h["country"], h["currency"], "FIXED_REBATE", "Circle Fixed", 1, h["url"]))

    conn.commit()
    total_db = c.execute("SELECT COUNT(*) FROM hotels WHERE brand = 'SHANGRI-LA'").fetchone()[0]
    conn.close()

    print(f"📊 Saved {total_db} verified Shangri-La hotels to hotel_stays.db.\n")
    return verified_hotels

if __name__ == "__main__":
    extract_and_verify_shangrila()
