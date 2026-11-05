import os
import sys
import re
import json
import sqlite3
import asyncio
from urllib.parse import urlparse
from curl_cffi.requests import AsyncSession

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ISO_COUNTRY_MAP = {
    "ID": ("Indonesia", "IDR", "Asia"),
    "SG": ("Singapore", "SGD", "Asia"),
    "TH": ("Thailand", "THB", "Asia"),
    "MY": ("Malaysia", "MYR", "Asia"),
    "VN": ("Vietnam", "USD", "Asia"),
    "JP": ("Japan", "JPY", "Asia"),
    "KR": ("South Korea", "KRW", "Asia"),
    "CN": ("China", "CNY", "Asia"),
    "HK": ("Hong Kong", "HKD", "Asia"),
    "MO": ("Macau", "MOP", "Asia"),
    "TW": ("Taiwan", "TWD", "Asia"),
    "PH": ("Philippines", "PHP", "Asia"),
    "IN": ("India", "INR", "Asia"),
    "MV": ("Maldives", "USD", "Asia"),
    "KH": ("Cambodia", "USD", "Asia"),
    "LA": ("Laos", "USD", "Asia"),
    "MM": ("Myanmar", "USD", "Asia"),
    "LK": ("Sri Lanka", "LKR", "Asia"),
    "NP": ("Nepal", "NPR", "Asia"),
    "BD": ("Bangladesh", "BDT", "Asia"),
    "UZ": ("Uzbekistan", "USD", "Asia"),
    "KZ": ("Kazakhstan", "KZT", "Asia"),
    "AZ": ("Azerbaijan", "AZN", "Asia"),
    "GE": ("Georgia", "GEL", "Europe"),
    "AM": ("Armenia", "AMD", "Europe"),
    
    # Oceania
    "AU": ("Australia", "AUD", "Oceania"),
    "NZ": ("New Zealand", "NZD", "Oceania"),
    "FJ": ("Fiji", "FJD", "Oceania"),
    "PF": ("French Polynesia", "XPF", "Oceania"),
    "NC": ("New Caledonia", "XPF", "Oceania"),
    
    # Europe
    "FR": ("France", "EUR", "Europe"),
    "GB": ("United Kingdom", "GBP", "Europe"),
    "DE": ("Germany", "EUR", "Europe"),
    "IT": ("Italy", "EUR", "Europe"),
    "ES": ("Spain", "EUR", "Europe"),
    "NL": ("Netherlands", "EUR", "Europe"),
    "BE": ("Belgium", "EUR", "Europe"),
    "CH": ("Switzerland", "CHF", "Europe"),
    "AT": ("Austria", "EUR", "Europe"),
    "PT": ("Portugal", "EUR", "Europe"),
    "GR": ("Greece", "EUR", "Europe"),
    "PL": ("Poland", "PLN", "Europe"),
    "CZ": ("Czech Republic", "CZK", "Europe"),
    "HU": ("Hungary", "HUF", "Europe"),
    "RO": ("Romania", "RON", "Europe"),
    "TR": ("Turkey", "USD", "Europe"),
    "SE": ("Sweden", "SEK", "Europe"),
    "IE": ("Ireland", "EUR", "Europe"),
    "DK": ("Denmark", "DKK", "Europe"),
    "HR": ("Croatia", "EUR", "Europe"),
    "BG": ("Bulgaria", "BGN", "Europe"),
    "RS": ("Serbia", "RSD", "Europe"),
    "SK": ("Slovakia", "EUR", "Europe"),
    "SI": ("Slovenia", "EUR", "Europe"),
    "EE": ("Estonia", "EUR", "Europe"),
    "LV": ("Latvia", "EUR", "Europe"),
    "LT": ("Lithuania", "EUR", "Europe"),
    "LU": ("Luxembourg", "EUR", "Europe"),
    "MT": ("Malta", "EUR", "Europe"),
    "CY": ("Cyprus", "EUR", "Europe"),
    "IS": ("Iceland", "ISK", "Europe"),
    "NO": ("Norway", "NOK", "Europe"),
    "FI": ("Finland", "EUR", "Europe"),
    "UA": ("Ukraine", "UAH", "Europe"),
    "MD": ("Moldova", "MDL", "Europe"),
    "BA": ("Bosnia and Herzegovina", "BAM", "Europe"),
    "ME": ("Montenegro", "EUR", "Europe"),
    "MK": ("North Macedonia", "MKD", "Europe"),
    "AL": ("Albania", "ALL", "Europe"),
    "AD": ("Andorra", "EUR", "Europe"),
    "MC": ("Monaco", "EUR", "Europe"),
    "RU": ("Russia", "RUB", "Europe"),
    
    # Middle East & Africa
    "AE": ("United Arab Emirates", "AED", "Middle East"),
    "SA": ("Saudi Arabia", "SAR", "Middle East"),
    "QA": ("Qatar", "QAR", "Middle East"),
    "OM": ("Oman", "OMR", "Middle East"),
    "BH": ("Bahrain", "BHD", "Middle East"),
    "KW": ("Kuwait", "KWD", "Middle East"),
    "JO": ("Jordan", "JOD", "Middle East"),
    "LB": ("Lebanon", "USD", "Middle East"),
    "IL": ("Israel", "ILS", "Middle East"),
    "EG": ("Egypt", "USD", "Africa"),
    "MA": ("Morocco", "MAD", "Africa"),
    "ZA": ("South Africa", "ZAR", "Africa"),
    "MU": ("Mauritius", "USD", "Africa"),
    "SC": ("Seychelles", "EUR", "Africa"),
    "NG": ("Nigeria", "NGN", "Africa"),
    "KE": ("Kenya", "USD", "Africa"),
    "SN": ("Senegal", "XOF", "Africa"),
    "CI": ("Ivory Coast", "XOF", "Africa"),
    "GH": ("Ghana", "GHS", "Africa"),
    "CM": ("Cameroon", "XAF", "Africa"),
    "DZ": ("Algeria", "DZD", "Africa"),
    "TN": ("Tunisia", "TND", "Africa"),
    "ET": ("Ethiopia", "ETB", "Africa"),
    "TZ": ("Tanzania", "USD", "Africa"),
    "RW": ("Rwanda", "USD", "Africa"),
    "CD": ("Congo (DRC)", "USD", "Africa"),
    "CG": ("Congo", "XAF", "Africa"),
    "MG": ("Madagascar", "MGA", "Africa"),
    "AO": ("Angola", "AOA", "Africa"),
    "BJ": ("Benin", "XOF", "Africa"),
    "TG": ("Togo", "XOF", "Africa"),
    "GN": ("Guinea", "GNF", "Africa"),
    "GQ": ("Equatorial Guinea", "XAF", "Africa"),
    "TD": ("Chad", "XAF", "Africa"),
    
    # Americas
    "US": ("United States", "USD", "Americas"),
    "CA": ("Canada", "CAD", "Americas"),
    "MX": ("Mexico", "USD", "Americas"),
    "BR": ("Brazil", "BRL", "Americas"),
    "AR": ("Argentina", "USD", "Americas"),
    "CL": ("Chile", "USD", "Americas"),
    "CO": ("Colombia", "USD", "Americas"),
    "PE": ("Peru", "USD", "Americas"),
    "UY": ("Uruguay", "USD", "Americas"),
    "PA": ("Panama", "USD", "Americas"),
    "CU": ("Cuba", "USD", "Americas"),
    "EC": ("Ecuador", "USD", "Americas"),
    "CR": ("Costa Rica", "USD", "Americas"),
    "DO": ("Dominican Republic", "USD", "Americas"),
    "PR": ("Puerto Rico", "USD", "Americas"),
    "JM": ("Jamaica", "USD", "Americas"),
    "BS": ("Bahamas", "USD", "Americas"),
    "BM": ("Bermuda", "USD", "Americas"),
    "BB": ("Barbados", "USD", "Americas"),
    "CW": ("Curacao", "USD", "Americas"),
    "AW": ("Aruba", "USD", "Americas"),
    "GT": ("Guatemala", "GTQ", "Americas"),
    "HN": ("Honduras", "HNL", "Americas"),
    "SV": ("El Salvador", "USD", "Americas"),
    "NI": ("Nicaragua", "NIO", "Americas"),
    "BO": ("Bolivia", "BOB", "Americas"),
    "PY": ("Paraguay", "PYG", "Americas"),
    "VE": ("Venezuela", "USD", "Americas")
}

async def fetch_accor_hotel(session: AsyncSession, url: str, semaphore: asyncio.Semaphore):
    m_code = re.search(r'/hotel/([a-zA-Z0-9]{4})/', url)
    hotel_id = f"accor_{m_code.group(1).lower()}" if m_code else f"accor_{url.split('/')[-2]}"

    async with semaphore:
        try:
            r = await session.get(url, timeout=20.0)
            if r.status_code == 200:
                matches = re.findall(r'<script[^>]*type=[\'"]application/ld\+json[\'"][^>]*>(.*?)</script>', r.text, re.DOTALL)
                name = None
                city = None
                country_code = None

                for m in matches:
                    try:
                        data = json.loads(m.strip())
                        if isinstance(data, dict) and data.get('@type') in ['Hotel', 'LodgingBusiness', 'Resort', 'Accommodation']:
                            name = data.get('name')
                            addr = data.get('address', {})
                            if isinstance(addr, dict):
                                country_code = addr.get('addressCountry')
                                city = addr.get('addressLocality')
                            break
                    except Exception:
                        pass

                if not name:
                    m_title = re.search(r'<title>(.*?)</title>', r.text, re.IGNORECASE)
                    if m_title:
                        name = m_title.group(1).replace('- ALL', '').replace('| ALL', '').strip()

                if name:
                    name = name.replace('- ALL', '').replace('| ALL', '').strip()
                    name = re.sub(r'&amp;', '&', name).strip()
                    cc = (country_code or '').upper().strip()
                    
                    if cc in ISO_COUNTRY_MAP:
                        country_name, curr, region = ISO_COUNTRY_MAP[cc]
                    else:
                        country_name = cc if cc else "Global"
                        curr = "EUR"
                        region = "Global"

                    city_name = (city or "Main City").strip().title()

                    return {
                        "id": hotel_id,
                        "brand": "ACCOR",
                        "name": name,
                        "city": city_name,
                        "country": country_name,
                        "region": region,
                        "currency": curr,
                        "url": url,
                        "status": 200
                    }
            return None
        except Exception:
            return None

async def crawl_accor_live():
    print("==================================================")
    print("🚀 Crawling Official ALL (Accor Live Limitless) Directory")
    print("==================================================")

    async with AsyncSession(impersonate="chrome124") as session:
        r = await session.get("https://all.accor.com/sitemap-fh.en.xml", timeout=30.0)
        urls = re.findall(r'<loc>([^<]+)</loc>', r.text)

    print(f"[*] Retrieved {len(urls)} official hotel URLs from Accor sitemap.")

    semaphore = asyncio.Semaphore(25)
    all_verified = []
    batch_size = 50

    async with AsyncSession(impersonate="chrome124") as session:
        for i in range(0, len(urls), batch_size):
            chunk = urls[i:i+batch_size]
            tasks = [fetch_accor_hotel(session, u, semaphore) for u in chunk]
            results = await asyncio.gather(*tasks)

            for res in results:
                if res and res.get("status") == 200 and "name" in res:
                    all_verified.append(res)

            print(f"  Processed {min(i + batch_size, len(urls))}/{len(urls)} URLs... (Verified Accor: {len(all_verified)})")

    print(f"\n✅ Total Verified Genuine Accor Hotels: {len(all_verified)}")

    # Ingest into SQLite database
    conn = sqlite3.connect("hotel_stays.db")
    c = conn.cursor()
    c.execute("DELETE FROM hotels WHERE brand = 'ACCOR'")

    for h in all_verified:
        c.execute("""
            INSERT OR REPLACE INTO hotels (id, brand, name, city, country, currency, loyalty_model, award_category, track_points, official_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (h["id"], h["brand"], h["name"], h["city"], h["country"], h["currency"], "FIXED_REBATE", "ALL Reward Points", 0, h["url"]))

    conn.commit()
    total_db = c.execute("SELECT COUNT(*) FROM hotels WHERE brand = 'ACCOR'").fetchone()[0]
    conn.close()

    print(f"📊 Saved {total_db} verified Accor hotels to hotel_stays.db.\n")
    return all_verified

if __name__ == "__main__":
    asyncio.run(crawl_accor_live())
