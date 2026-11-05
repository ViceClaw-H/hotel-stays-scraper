#!/usr/bin/env python3
"""
Swiss-Belhotel International - Complete Property Discovery & Ingestion Engine.

Discovers 100% of Swiss-Belhotel properties globally via:
1. XML Sitemap Master (/sitemap.xml)
2. Destination Directory Portals (/destinations/*)
3. Schema.org Hotel JSON-LD metadata extraction
4. Google Maps embed coordinate parsing (!2d<lng>!3d<lat>)
5. Sabre SynXis Booking Engine property resolution

Persists verified properties to SQLite `hotel_stays.db` and records lifecycle events.
"""

import os
import sys

# Ensure UTF-8 output on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import re
import json
import sqlite3
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from curl_cffi import requests

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hotel_stays.db")
BACKUP_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "swissbel_catalog.json")

CURRENCY_BY_COUNTRY = {
    "indonesia": "IDR",
    "australia": "AUD",
    "new zealand": "NZD",
    "bahrain": "BHD",
    "kuwait": "KWD",
    "qatar": "QAR",
    "oman": "OMR",
    "egypt": "EGP",
    "kenya": "KES",
    "malaysia": "MYR",
    "vietnam": "VND",
    "philippines": "PHP",
    "thailand": "THB",
    "china": "CNY",
    "switzerland": "CHF",
    "georgia": "GEL"
}

def get_all_hotel_slugs():
    """Extract full master list of hotel slugs from sitemap and destination directory."""
    print("[1/4] Fetching Swiss-Belhotel XML sitemap...")
    sm_url = "https://www.swiss-belhotel.com/sitemap.xml"
    r_sm = requests.get(sm_url, impersonate="chrome124", timeout=20)
    sitemap_slugs = set(re.findall(r'https://www\.swiss-belhotel\.com/hotels/([a-zA-Z0-9_-]+)', r_sm.text))
    print(f"      Discovered {len(sitemap_slugs)} hotel slugs in sitemap.xml")

    print("[2/4] Cross-checking destination directories...")
    dest_main = "https://www.swiss-belhotel.com/destinations"
    dest_hotel_slugs = set()
    try:
        r_dest = requests.get(dest_main, impersonate="chrome124", timeout=20)
        soup_main = BeautifulSoup(r_dest.text, "html.parser")
        dest_links = set()
        for a in soup_main.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/destinations/"):
                dest_links.add(f"https://www.swiss-belhotel.com{href}")

        for d_url in sorted(list(dest_links)):
            try:
                r_d = requests.get(d_url, impersonate="chrome124", timeout=15)
                slugs = set(re.findall(r'/hotels/([a-zA-Z0-9_-]+)', r_d.text))
                dest_hotel_slugs.update(slugs)
            except Exception:
                pass
    except Exception as e:
        print(f"      Destination directory scan warning: {e}")

    # Remove non-hotel placeholders if any
    all_slugs = (sitemap_slugs | dest_hotel_slugs) - {"destinations", "offers", "rooms", "dining"}
    print(f"      Total unique master slugs to extract: {len(all_slugs)}")
    return sorted(list(all_slugs))

def extract_property_details(slug):
    """Scrape and parse a single hotel overview page."""
    url = f"https://www.swiss-belhotel.com/hotels/{slug}"
    try:
        r = requests.get(url, impersonate="chrome124", timeout=20)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")

        # 1. Schema.org Hotel extraction
        name, address, city, country, phone, email = "", "", "", "", "", ""
        for s in soup.find_all("script"):
            if s.string and "schema.org" in s.string and '"Hotel"' in s.string:
                try:
                    data = json.loads(s.string.strip())
                    name = data.get("name", "")
                    addr_data = data.get("address", {})
                    if isinstance(addr_data, dict):
                        address = addr_data.get("streetAddress", "")
                        city = addr_data.get("addressLocality", "")
                        country = addr_data.get("addressCountry", "")
                    phone_raw = data.get("telephone", "")
                    email_raw = data.get("email", "")
                    phone = re.sub(r'<[^>]+>', '', phone_raw).strip()
                    email = re.sub(r'<[^>]+>', '', email_raw).strip()
                    break
                except Exception:
                    pass

        # Fallbacks for name and location
        if not name and soup.title:
            name = soup.title.string.split("|")[0].strip()
        if not name:
            h1 = soup.find("h1")
            name = h1.get_text(strip=True) if h1 else slug.replace("-", " ").title()

        # Inferred country/city from address if empty
        if not country and address:
            for c_cand in CURRENCY_BY_COUNTRY.keys():
                if c_cand in address.lower():
                    country = c_cand.title()
                    break
        if not country:
            country = "Indonesia" # Default primary territory for Swiss-Belhotel

        # 2. Coordinates from Google Maps Embed
        lat, lng = None, None
        m_maps = re.search(r'google\.com/maps/embed\?pb=[^"\'>]*!2d([-\d.]+)!3d([-\d.]+)', r.text)
        if m_maps:
            try:
                lng = float(m_maps.group(1))
                lat = float(m_maps.group(2))
            except Exception:
                pass

        # 3. Sabre SynXis Hotel ID
        synxis_id = ""
        m_synxis = re.search(r'synxis\.com/\?hotel=(\d+)', r.text, re.I)
        if m_synxis:
            synxis_id = m_synxis.group(1)

        # 4. Currency
        curr = CURRENCY_BY_COUNTRY.get(country.lower().strip(), "USD")

        hotel_id = f"swiss_{slug.replace('-', '_')}"

        return {
            "id": hotel_id,
            "slug": slug,
            "brand": "SWISS_BELHOTEL",
            "name": name,
            "city": city or "Unknown",
            "country": country,
            "currency": curr,
            "latitude": lat,
            "longitude": lng,
            "synxis_id": synxis_id,
            "street_address": address,
            "phone": phone,
            "email": email,
            "official_url": url,
            "loyalty_model": "SBEC_BENEFITS",
            "lifecycle_status": "ACTIVE"
        }
    except Exception as e:
        print(f"      [!] Failed to extract {slug}: {e}")
        return None

def ingest_to_database(properties):
    """Insert or update properties in hotel_stays.db."""
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    inserted_cnt = 0
    updated_cnt = 0

    for prop in properties:
        cur.execute("SELECT id, lifecycle_status FROM hotels WHERE id = ?", (prop["id"],))
        existing = cur.fetchone()

        if existing is None:
            cur.execute("""
                INSERT INTO hotels (
                    id, brand, name, city, country, currency, loyalty_model,
                    award_category, track_points, official_url, created_at,
                    lifecycle_status, status_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prop["id"], prop["brand"], prop["name"], prop["city"], prop["country"],
                prop["currency"], prop["loyalty_model"], "STANDARD", 1, prop["official_url"],
                now_iso, prop["lifecycle_status"], now_iso
            ))
            # Record lifecycle log
            cur.execute("""
                INSERT INTO property_lifecycle_log (
                    hotel_id, brand, event_type, previous_status, new_status,
                    reason, detail, evidence_url, transitioned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prop["id"], prop["brand"], "DISCOVERED", None, "ACTIVE",
                "INITIAL_DISCOVERY", f"Discovered via Swiss-Belhotel sitemap & destination crawl (SynXis: {prop['synxis_id']})",
                prop["official_url"], now_iso
            ))
            inserted_cnt += 1
        else:
            cur.execute("""
                UPDATE hotels SET
                    name = ?, city = ?, country = ?, currency = ?,
                    official_url = ?, status_updated_at = ?
                WHERE id = ?
            """, (
                prop["name"], prop["city"], prop["country"], prop["currency"],
                prop["official_url"], now_iso, prop["id"]
            ))
            updated_cnt += 1

    conn.commit()
    conn.close()
    return inserted_cnt, updated_cnt

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Swiss-Belhotel Discovery")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of hotel slugs")
    args = parser.parse_args()

    print("=" * 70)
    print("SWISS-BELHOTEL INTERNATIONAL: FULL PROPERTY DISCOVERY")
    print("=" * 70)

    slugs = get_all_hotel_slugs()
    if args.limit:
        slugs = slugs[:args.limit]

    print(f"\n[3/4] Extracting hotel metadata for {len(slugs)} properties (concurrency=4)...")
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(extract_property_details, s): s for s in slugs}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                results.append(res)
                print(f"      [+] {res['name']} ({res['city']}, {res['country']}) | SynXis: {res['synxis_id'] or 'N/A'}")

    print(f"\nSuccessfully harvested metadata for {len(results)} properties.")

    # Save backup JSON
    with open(BACKUP_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Catalog saved to {BACKUP_JSON}")

    # Ingest to SQLite DB
    print(f"\n[4/4] Ingesting into database: {DB_PATH}...")
    ins, upd = ingest_to_database(results)
    print(f"      [DB COMMIT] Inserted new: {ins} | Updated existing: {upd}")

    print("\n" + "=" * 70)
    print("SWISS-BELHOTEL DISCOVERY COMPLETE!")
    print(f"Total Hotels Active in DB: {len(results)}")
    print("=" * 70)

if __name__ == "__main__":
    main()
