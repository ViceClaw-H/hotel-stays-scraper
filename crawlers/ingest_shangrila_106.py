import sys
import os
import json
import sqlite3
import re
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from export_hotels_excel import export_watchlist_to_excel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("shangrila_ingest")

def ingest_shangrila_106():
    with open("shangrila_106_extracted.json", "r", encoding="utf-8") as f:
        hotels_dict = json.load(f)

    conn = sqlite3.connect('hotel_stays.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM hotels WHERE brand = 'SHANGRI_LA'")
    conn.commit()

    country_map = {
        "jakarta": ("Indonesia", "IDR"),
        "surabaya": ("Indonesia", "IDR"),
        "singapore": ("Singapore", "SGD"),
        "bangkok": ("Thailand", "THB"),
        "chiangmai": ("Thailand", "THB"),
        "kualalumpur": ("Malaysia", "MYR"),
        "penang": ("Malaysia", "MYR"),
        "kotakinabalu": ("Malaysia", "MYR"),
        "johor": ("Malaysia", "MYR"),
        "tokyo": ("Japan", "JPY"),
        "kyoto": ("Japan", "JPY"),
        "london": ("United Kingdom", "GBP"),
        "paris": ("France", "EUR"),
        "istanbul": ("Turkey", "USD"),
        "dubai": ("United Arab Emirates", "AED"),
        "abudhabi": ("United Arab Emirates", "AED"),
        "jeddah": ("Saudi Arabia", "SAR"),
        "muscat": ("Oman", "OMR"),
        "sydney": ("Australia", "AUD"),
        "cairns": ("Australia", "AUD"),
        "fiji": ("Fiji", "FJD"),
        "toronto": ("Canada", "CAD"),
        "vancouver": ("Canada", "CAD"),
        "colombo": ("Sri Lanka", "USD"),
        "hambantota": ("Sri Lanka", "USD"),
        "manila": ("Philippines", "PHP"),
        "cebu": ("Philippines", "PHP"),
        "boracay": ("Philippines", "PHP"),
        "newdelhi": ("India", "INR"),
        "bengaluru": ("India", "INR"),
        "mauritius": ("Mauritius", "EUR"),
        "phnompenh": ("Cambodia", "USD"),
        "yangon": ("Myanmar", "USD"),
        "ulaanbaatar": ("Mongolia", "USD"),
    }

    count = 0
    for name, url in hotels_dict.items():
        # Extract city from url: https://www.shangri-la.com/en/{city}/...
        m = re.search(r'shangri-la\.com/en/([^/]+)/', url)
        city_slug = m.group(1).lower() if m else "china"
        
        country, curr = country_map.get(city_slug, ("China", "CNY"))
        city_display = city_slug.capitalize()

        h_id = f"shang_{re.sub(r'[^a-z0-9]', '', name.lower())[:24]}_{count+1}"

        cursor.execute("""
            INSERT OR REPLACE INTO hotels (id, brand, name, city, country, currency, loyalty_model, track_points, official_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (h_id, "SHANGRI_LA", name, city_display, country, curr, "FIXED_REBATE", 0, url))
        count += 1

    conn.commit()
    conn.close()
    logger.info(f"Successfully ingested all {count} official Shangri-La Group properties into database!")
    export_watchlist_to_excel()

if __name__ == '__main__':
    ingest_shangrila_106()
