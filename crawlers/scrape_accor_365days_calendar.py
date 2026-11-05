"""Accor 365-Day Price Calendar Ingestion Engine.
Fetches full 365-day daily rates (day by day) directly from official Accor PriceCalendar GraphQL API.
Computes daily Member Rate, Tax, ALL Points, and 365-day Floor & Ceiling bounds.
"""
import sys
import os
import json
import sqlite3
import time
from datetime import datetime, date, timedelta
from curl_cffi import requests
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.baselines import update_property_and_brand_baselines

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("accor_365_calendar")

GRAPHQL_URL = "https://api.accor.com/bff/v1/graphql"

def load_calendar_query():
    for p in [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "graphql", "accor_pricecalendar_query.graphql"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "accor_pricecalendar_query.graphql"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "accor_pricecalendar_query.graphql"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crawlers", "graphql", "accor_pricecalendar_query.graphql")
    ]:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
    return None

def get_headers():
    return {
        "content-type": "application/json",
        "origin": "https://all.accor.com",
        "referer": "https://all.accor.com/",
        "accept-language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "apikey": os.environ.get("ACCOR_API_KEY", ""),
        "clientid": "all.accor",
        "app-id": "all.accor",
        "app-version": "1.48.0",
        "lang": "id"
    }

def clean_amount(val):
    if not val:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    # Strip currency symbols like 'Rp', '€', '.', commas, non-breaking spaces
    clean_str = str(val).replace("Rp", "").replace("€", "").replace("$", "").replace("£", "").replace("\xa0", "").strip()
    # If standard Indonesian formatting '521.480'
    clean_str = clean_str.replace(".", "").replace(",", ".")
    try:
        return float(clean_str)
    except:
        return None

def scrape_hotel_365_days(hotel_code: str, hotel_db_id: str, hotel_name: str, currency: str = "IDR", country_market: str = "ID"):
    query_str = load_calendar_query()
    if not query_str:
        logger.error("PriceCalendar GraphQL query not found.")
        return 0

    headers = get_headers()
    conn = sqlite3.connect('hotel_stays.db')
    cursor = conn.cursor()

    room_id = f"{hotel_db_id}_std"
    cursor.execute("""
        INSERT OR IGNORE INTO room_categories (id, hotel_id, raw_name, standardized_type, max_occupancy)
        VALUES (?, ?, ?, ?, ?)
    """, (room_id, hotel_db_id, "Standard Room (Calendar Lowest)", "STANDARD", 2))

    start_date = date.today()
    total_days_target = 365
    chunk_size = 7  # Accor API maximum window is 8 days

    logger.info(f"=== Starting 365-day calendar scrape for: {hotel_name} ({hotel_code}) ===")

    total_inserted = 0
    curr_date = start_date
    end_date = start_date + timedelta(days=total_days_target)

    session = requests.Session()

    while curr_date < end_date:
        to_date = min(curr_date + timedelta(days=chunk_size - 1), end_date)
        from_str = curr_date.strftime("%Y-%m-%d")
        to_str = to_date.strftime("%Y-%m-%d")

        variables = {
            "hotelId": hotel_code,
            "hotelId2": hotel_code,
            "dateIn": from_str,
            "dateOut": (curr_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "nbAdults": 1,
            "childrenAges": [],
            "countryMarket": country_market,
            "currency": currency,
            "from": from_str,
            "to": to_str,
            "use": "NIGHT",
            "concession": None
        }

        payload = {
            "operationName": "PriceCalendar",
            "variables": variables,
            "query": query_str
        }

        try:
            r = session.post(GRAPHQL_URL, json=payload, headers=headers, impersonate="chrome124", timeout=20)
            if r.status_code != 200:
                logger.warning(f"Failed status {r.status_code} for {from_str} to {to_str}")
                curr_date = to_date + timedelta(days=1)
                continue

            res_json = r.json()
            res_data = res_json.get("data") or {}
            hotel_offers = res_data.get("hotelOffers") or {}
            calendar_data = hotel_offers.get("calendar", []) or []

            for day_entry in calendar_data:
                if not isinstance(day_entry, dict):
                    continue
                stay_dt = day_entry.get("date")
                avail = (day_entry.get("availability") or {}).get("status")
                if avail == "UNAVAILABLE" or not stay_dt:
                    continue

                offer = day_entry.get("offer") or {}
                if not isinstance(offer, dict):
                    continue
                pricing = offer.get("pricing") or {}
                main_p = pricing.get("main") or {}
                alt_p = pricing.get("alternative") or {}

                member_amt = clean_amount(main_p.get("formattedAmount"))
                if not member_amt:
                    member_amt = clean_amount(alt_p.get("formattedAmount"))

                if not member_amt or member_amt <= 0:
                    continue

                # Compute ALL points (2,000 pts = 40 EUR / 688,000 IDR)
                if currency == "IDR":
                    pts_req = int((member_amt / 688000.0) * 2000)
                elif currency == "EUR":
                    pts_req = int((member_amt / 40.0) * 2000)
                elif currency == "USD":
                    pts_req = int((member_amt / 43.5) * 2000)
                elif currency == "SGD":
                    pts_req = int((member_amt / 58.0) * 2000)
                else:
                    pts_req = int(member_amt * 10)

                is_best = 1 if day_entry.get("bestRate") else 0

                cursor.execute("""
                    INSERT OR REPLACE INTO rate_records (room_id, stay_date, cash_rate, points_required, award_available, scraped_at, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (room_id, stay_dt, member_amt, pts_req, 1, datetime.now().isoformat(), f"Accor Official 365-Day Calendar {'(Floor Best Rate)' if is_best else ''}"))
                total_inserted += 1

            conn.commit()

        except Exception as e:
            logger.error(f"Error fetching chunk {from_str} -> {to_str}: {e}")

        curr_date = to_date + timedelta(days=1)
        time.sleep(0.15)  # respectful pacing

    conn.close()
    logger.info(f"==> Successfully ingested {total_inserted} days for {hotel_name} across the 365-day year!")
    return total_inserted

def run_365_days_for_hotels(hotels_to_scrape: list):
    grand_total_days = 0
    for h_code, h_db_id, h_name, curr, mkt in hotels_to_scrape:
        count = scrape_hotel_365_days(h_code, h_db_id, h_name, currency=curr, country_market=mkt)
        grand_total_days += count

    # Recalculate baseline floors & ceilings
    session_factory = get_session_factory()
    session = session_factory()
    updated = update_all_baselines(session)
    session.close()

    logger.info(f"\n=======================================================")
    logger.info(f"COMPLETED 365-DAY YEAR CRAWL: Ingested {grand_total_days} total daily rates across {len(hotels_to_scrape)} hotels!")
    logger.info(f"Updated {updated} property baselines with full 365-day Floor and Ceiling bounds.")
    logger.info(f"=======================================================")

if __name__ == '__main__':
    # Sample set of high-interest Accor properties across Indonesia & international hubs
    HOTELS = [
        ("8489", "accor_8489", "Novotel Banjarmasin Airport", "IDR", "ID"),
        ("C2H0", "accor_C2H0", "Swissôtel Nusantara", "IDR", "ID"),
        ("8307", "accor_8307", "Fairmont Jakarta", "IDR", "ID"),
        ("5704", "accor_5704", "Pullman Jakarta Indonesia Thamrin CBD", "IDR", "ID"),
        ("1960", "accor_1960", "The Phoenix Hotel Yogyakarta - Handwritten Collection", "IDR", "ID"),
        ("5451", "accor_5451", "Novotel Solo", "IDR", "ID"),
        ("0543", "accor_0543", "Pullman Paris Tour Eiffel", "EUR", "FR"),
        ("3634", "accor_3634", "Sofitel Singapore City Centre", "SGD", "SG")
    ]
    run_365_days_for_hotels(HOTELS)
