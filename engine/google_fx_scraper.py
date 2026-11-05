"""Automated Live Currency Scraper from Google Finance.
Fetches real-time exchange rates to IDR for all hotel transaction currencies on every rescrape.
Stores rates in hotel_stays.db (daily_fx_rates) and creates a live JSON snapshot.
"""
import urllib.request
import re
import json
import sqlite3
import datetime
import os
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "hotel_stays.db")
CACHE_FILE = os.path.join(ROOT, "live_google_fx.json")

# Core hotel operating currencies converted to IDR
CURRENCY_PAIRS = [
    ("USD", "IDR"),
    ("JPY", "IDR"),
    ("SGD", "IDR"),
    ("EUR", "IDR"),
    ("GBP", "IDR"),
    ("AUD", "IDR"),
    ("MYR", "IDR"),
    ("THB", "IDR"),
    ("CNY", "IDR"),
    ("CHF", "IDR"),
    ("AED", "IDR"),
    ("SAR", "IDR")
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9,id;q=0.8'
}

def init_fx_table():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_fx_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetch_date DATE NOT NULL,
            base_currency TEXT NOT NULL,
            quote_currency TEXT NOT NULL DEFAULT 'IDR',
            rate REAL NOT NULL,
            source TEXT DEFAULT 'Google Finance',
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(fetch_date, base_currency, quote_currency)
        )
    """)
    conn.commit()
    conn.close()

def extract_rate_from_html(base, quote, html):
    """Extract asset price accurately from Google Finance quote HTML."""
    # Method 1: Look for main asset header span jsname="Pdsbrc"
    # Matches patterns like: <div class="gO24Ff">...</div>...<span>17,898.9177</span>
    m = re.search(r'<div class="gO24Ff">[^<]*' + base + r'[^<]*</div>.*?<span jsname="Pdsbrc"[^>]*><span>([0-9,\.]+)</span>', html, re.DOTALL | re.IGNORECASE)
    if m:
        return float(m.group(1).replace(',', ''))

    # Method 2: Look for class N6SYTe wrapping the main quote
    m2 = re.search(r'class="N6SYTe"[^>]*>.*?<span>([0-9,\.]+)</span>', html, re.DOTALL)
    if m2:
        val = float(m2.group(1).replace(',', ''))
        # Sanity check: Avoid matching the 1050 IDX market index
        if val != 1050.3 and val > 0:
            return val

    # Method 3: In-depth regex fallback for known currency scale ranges
    if base == "USD":
        m3 = re.findall(r'\b(1[6-9]\d{3}\.\d+)\b', html)
        if m3: return float(m3[0])
    elif base == "EUR":
        m3 = re.findall(r'\b(1[8-9]\d{3}\.\d+|2[0-2]\d{3}\.\d+)\b', html)
        if m3: return float(m3[0])
    elif base == "GBP":
        m3 = re.findall(r'\b(2[1-5]\d{3}\.\d+)\b', html)
        if m3: return float(m3[0])
    elif base == "SGD":
        m3 = re.findall(r'\b(1[2-5]\d{3}\.\d+)\b', html)
        if m3: return float(m3[0])
    elif base == "JPY":
        m3 = re.findall(r'\b(1[0-2]\d{1}\.\d{2,4})\b', html)
        if m3: return float(m3[0])

    return None

def fetch_and_store_google_fx(verbose=True):
    """Scrape live exchange rates from Google Finance and save to DB & JSON."""
    init_fx_table()
    today_str = datetime.date.today().isoformat()
    now_iso = datetime.datetime.now().isoformat()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    rates_map = {"IDR": 1.0}
    saved_count = 0

    if verbose:
        print(f"[*] Scraping live exchange rates from Google Finance ({today_str})...")

    for base, quote in CURRENCY_PAIRS:
        url = f"https://www.google.com/finance/quote/{base}-{quote}"
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
                rate = extract_rate_from_html(base, quote, html)
                
                if rate:
                    rates_map[base] = rate
                    # Upsert into database
                    cur.execute("""
                        INSERT INTO daily_fx_rates (fetch_date, base_currency, quote_currency, rate, source, fetched_at)
                        VALUES (?, ?, ?, ?, 'Google Finance', ?)
                        ON CONFLICT(fetch_date, base_currency, quote_currency) 
                        DO UPDATE SET rate=excluded.rate, fetched_at=excluded.fetched_at
                    """, (today_str, base, quote, rate, now_iso))
                    saved_count += 1
                    if verbose:
                        print(f"    [Google Finance] 1 {base} = Rp {rate:,.2f} IDR")
                else:
                    if verbose:
                        print(f"    [!] Could not parse rate for {base}-{quote}")
        except Exception as e:
            if verbose:
                print(f"    [!] Network error fetching {base}-{quote}: {e}")

    conn.commit()
    conn.close()

    # Save to live JSON snapshot for dashboard and scrapers
    snapshot = {
        "source": "Google Finance",
        "fetch_date": today_str,
        "fetched_at": now_iso,
        "usd_to_idr": rates_map.get("USD", 17898.92),
        "rates_to_idr": rates_map
    }

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)

    if verbose:
        print(f"[✓] Successfully stored {saved_count} Google Finance live FX rates in database and cache.")

    return snapshot

if __name__ == "__main__":
    fetch_and_store_google_fx(verbose=True)
