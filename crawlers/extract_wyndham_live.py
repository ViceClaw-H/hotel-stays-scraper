import os
import sys
import re
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# US States mapping
US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new-hampshire",
    "new-jersey", "new-mexico", "new-york", "north-carolina", "north-dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode-island", "south-carolina", "south-dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west-virginia",
    "wisconsin", "wyoming", "district-of-columbia", "puerto-rico"
}

CANADIAN_PROVINCES = {
    "ontario", "quebec", "british-columbia", "alberta", "manitoba", "saskatchewan",
    "nova-scotia", "new-brunswick", "newfoundland-and-labrador", "prince-edward-island"
}

def fetch_sub_sitemap(sm_url):
    try:
        r = requests.get(sm_url, impersonate='chrome124', timeout=30)
        if r.status_code == 200:
            urls = re.findall(r'<loc>(https://www\.wyndhamhotels\.com/[^<]+/overview)</loc>', r.text)
            return urls
    except Exception:
        pass
    return []

def crawl_wyndham_live():
    print("==================================================")
    print("🚀 Crawling Official Wyndham Hotels & Resorts Directory")
    print("==================================================")

    r = requests.get("https://www.wyndhamhotels.com/sitemap.xml", impersonate='chrome124', timeout=30)
    all_sitemaps = re.findall(r'<loc>([^<]+)</loc>', r.text)
    prop_sitemaps = [s for s in all_sitemaps if '_properties_' in s and 'en-us' in s]

    print(f"[*] Found {len(prop_sitemaps)} English property sub-sitemaps on Wyndham.")

    all_overview_urls = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_sub_sitemap, prop_sitemaps)
        for res in results:
            all_overview_urls.extend(res)

    print(f"[*] Retrieved {len(all_overview_urls)} total property overview URLs.")

    unique_hotels = {}
    for url in all_overview_urls:
        # Pattern: https://www.wyndhamhotels.com/{brand}/{city}-{location}/{slug}/overview
        m = re.search(r'wyndhamhotels\.com/([^/]+)/([^/]+)/([^/]+)/overview', url)
        if m:
            brand_slug = m.group(1)
            loc_slug = m.group(2)
            hotel_slug = m.group(3)

            # Determine city and country
            loc_parts = loc_slug.split("-")
            
            # Check if US State
            matched_state = None
            for st in US_STATES:
                if loc_slug.endswith(f"-{st}") or loc_slug == st:
                    matched_state = st
                    break

            if matched_state:
                country = "United States"
                city_raw = loc_slug.replace(f"-{matched_state}", "").replace("-", " ").title()
                city = city_raw or matched_state.replace("-", " ").title()
                curr = "USD"
            elif any(loc_slug.endswith(f"-{prov}") for prov in CANADIAN_PROVINCES):
                country = "Canada"
                city = loc_parts[0].capitalize()
                curr = "CAD"
            elif loc_slug.endswith("-indonesia"):
                country = "Indonesia"
                city = " ".join([w.capitalize() for w in loc_parts[:-1]])
                curr = "IDR"
            elif loc_slug.endswith("-singapore"):
                country = "Singapore"
                city = "Singapore"
                curr = "SGD"
            elif loc_slug.endswith("-malaysia"):
                country = "Malaysia"
                city = " ".join([w.capitalize() for w in loc_parts[:-1]])
                curr = "MYR"
            elif loc_slug.endswith("-thailand"):
                country = "Thailand"
                city = " ".join([w.capitalize() for w in loc_parts[:-1]])
                curr = "THB"
            elif loc_slug.endswith("-china"):
                country = "China"
                city = " ".join([w.capitalize() for w in loc_parts[:-1]])
                curr = "CNY"
            elif loc_slug.endswith("-united-kingdom") or loc_slug.endswith("-uk"):
                country = "United Kingdom"
                city = loc_parts[0].capitalize()
                curr = "GBP"
            elif loc_slug.endswith("-germany"):
                country = "Germany"
                city = loc_parts[0].capitalize()
                curr = "EUR"
            elif loc_slug.endswith("-france"):
                country = "France"
                city = loc_parts[0].capitalize()
                curr = "EUR"
            elif loc_slug.endswith("-australia"):
                country = "Australia"
                city = loc_parts[0].capitalize()
                curr = "AUD"
            else:
                country = loc_parts[-1].capitalize() if len(loc_parts) > 1 else "Global"
                city = " ".join([w.capitalize() for w in loc_parts[:-1]]) if len(loc_parts) > 1 else loc_slug.capitalize()
                curr = "USD"

            hotel_name = " ".join([w.capitalize() for w in hotel_slug.split("-")])
            hid = f"wynd_{re.sub(r'[^a-z0-9]', '', hotel_slug.lower())[:24]}"

            if hid not in unique_hotels:
                unique_hotels[hid] = {
                    "id": hid,
                    "brand": "WYNDHAM",
                    "name": hotel_name,
                    "city": city,
                    "country": country,
                    "currency": curr,
                    "url": url
                }

    print(f"\n✅ Total Verified Unique Wyndham Hotels: {len(unique_hotels)}")

    # Ingest into SQLite database
    conn = sqlite3.connect("hotel_stays.db")
    c = conn.cursor()
    c.execute("DELETE FROM hotels WHERE brand = 'WYNDHAM'")

    for h in unique_hotels.values():
        c.execute("""
            INSERT OR REPLACE INTO hotels (id, brand, name, city, country, currency, loyalty_model, award_category, track_points, official_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (h["id"], h["brand"], h["name"], h["city"], h["country"], h["currency"], "FIXED_CHART", "Wyndham Tier", 1, h["url"]))

    conn.commit()
    total_db = c.execute("SELECT COUNT(*) FROM hotels WHERE brand = 'WYNDHAM'").fetchone()[0]
    conn.close()

    print(f"📊 Saved {total_db} verified Wyndham Rewards hotels to hotel_stays.db.\n")
    return list(unique_hotels.values())

if __name__ == "__main__":
    crawl_wyndham_live()
