"""Country Composite Valuation Engine ($P_{50}^{\\text{composite}}(\\text{country})$).

Calculates exact empirical distributions of point redemption valuation (CPP = USD cents per point)
for every country in the global database using normalized official CRS cash rates and points required.

Zero synthetic data. Strict CRS provenance.
"""
import sqlite3
import json
import os
import numpy as np
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("country_composites")

DB_PATH = "hotel_stays.db"
FX_PATH = "live_fx_rates_usd.json"

def load_fx_rates():
    if os.path.exists(FX_PATH):
        with open(FX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def compute_country_composites():
    fx_rates = load_fx_rates()
    logger.info(f"Loaded {len(fx_rates)} FX currency pairs for normalization.")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Create tables
    c.execute("""
        CREATE TABLE IF NOT EXISTS country_composites (
            country TEXT NOT NULL PRIMARY KEY,
            val_p0 REAL,
            val_p10 REAL,
            val_p50 REAL,
            val_p90 REAL,
            val_p100 REAL,
            avg_cpp REAL,
            hotel_count INTEGER,
            rate_count INTEGER,
            updated_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS country_brand_composites (
            country TEXT NOT NULL,
            brand TEXT NOT NULL,
            val_p0 REAL,
            val_p10 REAL,
            val_p50 REAL,
            val_p90 REAL,
            val_p100 REAL,
            avg_cpp REAL,
            hotel_count INTEGER,
            rate_count INTEGER,
            updated_at TEXT,
            PRIMARY KEY (country, brand)
        )
    """)

    logger.info("Querying rate records with valid cash and points...")
    # Select joined data
    c.execute("""
        SELECT h.country, h.brand, h.id, rr.cash_rate, rr.raw_currency, h.currency, rr.points_required
        FROM rate_records rr
        JOIN room_categories rc ON rr.room_id = rc.id
        JOIN hotels h ON rc.hotel_id = h.id
        WHERE rr.points_required > 0 
          AND rr.cash_rate > 0
          AND h.country IS NOT NULL
          AND h.country != ''
    """)

    rows = c.fetchall()
    logger.info(f"Loaded {len(rows):,} rate records with paired cash and points.")

    country_vals = {}
    country_brand_vals = {}
    country_hotels = {}
    country_brand_hotels = {}

    for country, brand, hid, cash, raw_curr, h_curr, pts in rows:
        curr = (raw_curr or h_curr or "USD").upper().strip()
        
        # Convert to USD
        fx = fx_rates.get(curr)
        if curr == "USD":
            cash_usd = cash
        elif fx and fx > 0:
            cash_usd = cash / fx
        else:
            continue # Skip unresolvable currency

        # Realized CPP (cents per point) = (cash_usd / pts) * 100
        cpp = (cash_usd / pts) * 100.0
        if cpp <= 0 or cpp > 50.0:  # Exclude extreme anomalies (> $0.50/pt is usually glitch/unlinked)
            continue

        # Country aggregate
        if country not in country_vals:
            country_vals[country] = []
            country_hotels[country] = set()
        country_vals[country].append(cpp)
        country_hotels[country].add(hid)

        # Country + Brand aggregate
        cb_key = (country, brand)
        if cb_key not in country_brand_vals:
            country_brand_vals[cb_key] = []
            country_brand_hotels[cb_key] = set()
        country_brand_vals[cb_key].append(cpp)
        country_brand_hotels[cb_key].add(hid)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"Aggregating composites for {len(country_vals)} countries...")
    for country, vals in country_vals.items():
        arr = np.array(vals, dtype=float)
        p0 = float(np.min(arr))
        p10 = float(np.percentile(arr, 10))
        p50 = float(np.percentile(arr, 50))
        p90 = float(np.percentile(arr, 90))
        p100 = float(np.max(arr))
        avg = float(np.mean(arr))
        h_cnt = len(country_hotels[country])
        r_cnt = len(arr)

        c.execute("""
            INSERT OR REPLACE INTO country_composites (
                country, val_p0, val_p10, val_p50, val_p90, val_p100, avg_cpp, hotel_count, rate_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (country, p0, p10, p50, p90, p100, avg, h_cnt, r_cnt, now_iso))

    logger.info(f"Aggregating composites for {len(country_brand_vals)} country-brand pairs...")
    for (country, brand), vals in country_brand_vals.items():
        arr = np.array(vals, dtype=float)
        p0 = float(np.min(arr))
        p10 = float(np.percentile(arr, 10))
        p50 = float(np.percentile(arr, 50))
        p90 = float(np.percentile(arr, 90))
        p100 = float(np.max(arr))
        avg = float(np.mean(arr))
        h_cnt = len(country_brand_hotels[(country, brand)])
        r_cnt = len(arr)

        c.execute("""
            INSERT OR REPLACE INTO country_brand_composites (
                country, brand, val_p0, val_p10, val_p50, val_p90, val_p100, avg_cpp, hotel_count, rate_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (country, brand, p0, p10, p50, p90, p100, avg, h_cnt, r_cnt, now_iso))

    conn.commit()
    conn.close()
    logger.info("Successfully populated country_composites and country_brand_composites!")

if __name__ == "__main__":
    compute_country_composites()
