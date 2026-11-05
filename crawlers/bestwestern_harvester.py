#!/usr/bin/env python3
"""
Best Western (BWH Hotels) - Golden Standard Harvester (Schema v2)

Golden Standard Constraints:
- Direct GraphQL Backend for Frontend (BFF): https://bff.bff-api.web.bwhhotels.com/graphql
- 100% DataDome bypass via session cookie integration.
- Stratified Date Grid: 24 dates (1 Wednesday + 1 Saturday per month across 12 months).
- Prices are requested in IDR (targetCurrency: "IDR"): Best Western converts them, the response has no currency
  field, so IDR is the currency WE REQUESTED, not the hotel's own. Hotel native currency: resortSummary.currencyCode.
- Only a TAX-INCLUSIVE price is stored (averageNightlyAmountWithFeesAndTaxes). The server states in every response
  whether it can supply taxes and fees (taxesAndFeesAvailable); when it cannot, the pre-tax figure is NOT stored as
  if it were taxed - the row is skipped and counted. (Older versions stored the pre-tax figure as tax-inclusive.)
- resortRoomCategory is a numeric code, not a room name, so the room is labelled UNKNOWN (code ...).
- Provenance gate: Evidence stored on disk with SHA-256 hash in SQLite rate_records.
"""

import os
import sys
import json
import sqlite3
import datetime
import hashlib
import requests
import time
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from engine.rate_writer import write_authentic_rate_record

DB_PATH = os.path.join(BASE_DIR, "hotel_stays.db")
EVIDENCE_DIR = os.path.join(BASE_DIR, "evidence", "bestwestern", "raw")
COOKIE_FILE = os.path.join(BASE_DIR, "crawlers", "pw_bestwestern_session", "bestwestern_cookies.json")
os.makedirs(EVIDENCE_DIR, exist_ok=True)

GQL_URL = "https://bff.bff-api.web.bwhhotels.com/graphql"
TARGET_CURRENCY = "IDR"   # currency we ASK the server to convert into; the response itself carries no currency
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Origin": "https://www.bestwestern.com",
    "Referer": "https://www.bestwestern.com/"
}

# Attach DataDome session cookie if available
if os.path.exists(COOKIE_FILE):
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies if 'name' in c and 'value' in c])
            if cookie_str:
                HEADERS["Cookie"] = cookie_str
    except Exception:
        pass

ROOM_RATE_QUERY = """
query GetRoomsWithRatePlans($input: RoomRateRequestInput!) {
  getRoomsWithRatePlans(input: $input) {
    resortId
    langCode
    totalRooms
    taxesAndFeesAvailable
    rooms {
      roomCategoryCode
      roomId
      description
      ratePlans {
        rateCode
        shortName
        taxIncluded
        averageNightlyRate
        averageNightlyRateWithTaxes
        totalCostOfStay
        totalCostOfStayWithTaxes
        isMemberRate
        fxAverageNightlyPoints
      }
    }
  }
}
"""

def query_room_rate_plans(resort_id, checkin_date, currency=TARGET_CURRENCY):
    """Query GetRoomsWithRatePlans for genuine room names and tax-verified rates."""
    checkout_date = (datetime.date.fromisoformat(checkin_date) + datetime.timedelta(days=1)).isoformat()
    payload = {
        "query": ROOM_RATE_QUERY,
        "variables": {
            "input": {
                "resortId": str(resort_id),
                "checkinDate": checkin_date,
                "checkoutDate": checkout_date,
                "numAdult": "2",
                "numChild": "0",
                "childrenAge": [],
                "targetCurrency": currency,
                "langCode": "en_US",
                "showGatedRates": False,
                "includeTaxesAndFees": True,
                "numberOfRooms": "1"
            }
        }
    }
    try:
        r = requests.post(GQL_URL, json=payload, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            res_json = r.json() or {}
            data = (res_json.get("data") or {}).get("getRoomsWithRatePlans") or {}
            rooms = data.get("rooms") or []
            return r.text, rooms
    except Exception as e:
        print(f"      [!] GQL RoomRate Error ({resort_id}): {e}", flush=True)
    return None, []

# Major search hubs globally
HUBS = [
    # Southeast Asia
    {"name": "Bangkok / Thailand", "lat": 13.7563, "lng": 100.5018, "dist": "100"},
    {"name": "Phuket / Thailand", "lat": 7.8804, "lng": 98.3923, "dist": "100"},
    {"name": "Jakarta / West Java", "lat": -6.2088, "lng": 106.8456, "dist": "100"},
    {"name": "Bali / Nusa Tenggara", "lat": -8.4095, "lng": 115.1889, "dist": "100"},
    {"name": "Kuala Lumpur / Malaysia", "lat": 3.1390, "lng": 101.6869, "dist": "100"},
    {"name": "Manila / Philippines", "lat": 14.5995, "lng": 120.9842, "dist": "100"},
    {"name": "Hanoi / Vietnam", "lat": 21.0285, "lng": 105.8542, "dist": "100"},
    
    # East Asia
    {"name": "Tokyo / Japan", "lat": 35.6762, "lng": 139.6503, "dist": "100"},
    {"name": "Osaka / Kyoto Japan", "lat": 34.6937, "lng": 135.5023, "dist": "100"},
    {"name": "Seoul / Korea", "lat": 37.5665, "lng": 126.9780, "dist": "100"},
    
    # Europe
    {"name": "London / UK", "lat": 51.5074, "lng": -0.1278, "dist": "100"},
    {"name": "Paris / France", "lat": 48.8566, "lng": 2.3522, "dist": "100"},
    {"name": "Rome / Italy", "lat": 41.9028, "lng": 12.4964, "dist": "100"},
    {"name": "Berlin / Germany", "lat": 52.5200, "lng": 13.4050, "dist": "100"},
    {"name": "Amsterdam / Netherlands", "lat": 52.3676, "lng": 4.9041, "dist": "100"},
    {"name": "Madrid / Spain", "lat": 40.4168, "lng": -3.7038, "dist": "100"},
    {"name": "Vienna / Austria", "lat": 48.2082, "lng": 16.3738, "dist": "100"},
    
    # North America
    {"name": "New York / US", "lat": 40.7128, "lng": -74.0060, "dist": "100"},
    {"name": "Los Angeles / US", "lat": 34.0522, "lng": -118.2437, "dist": "100"},
    {"name": "Chicago / US", "lat": 41.8781, "lng": -87.6298, "dist": "100"},
    {"name": "San Francisco / US", "lat": 37.7749, "lng": -122.4194, "dist": "100"},
    {"name": "Miami / Florida US", "lat": 25.7617, "lng": -80.1918, "dist": "100"},
    {"name": "Toronto / Canada", "lat": 43.6532, "lng": -79.3832, "dist": "100"},
    
    # Australia & Middle East
    {"name": "Sydney / Australia", "lat": -33.8688, "lng": 151.2093, "dist": "100"},
    {"name": "Melbourne / Australia", "lat": -37.8136, "lng": 144.9631, "dist": "100"},
    {"name": "Dubai / UAE", "lat": 25.2048, "lng": 55.2708, "dist": "100"}
]

def make_stratified_dates(months=12):
    """Generate 2 dates per month (Wednesday & Saturday) for the next 12 months (24 dates)."""
    base = datetime.date.today() + datetime.timedelta(days=7)
    dates = []
    for m in range(months):
        ref = base + datetime.timedelta(days=m * 30)
        wed = ref + datetime.timedelta(days=(2 - ref.weekday() + 7) % 7 or 7)
        sat = ref + datetime.timedelta(days=(5 - ref.weekday() + 7) % 7 or 7)
        dates.append(wed.isoformat())
        dates.append(sat.isoformat())
    return sorted(list(set(dates)))

def search_cluster_rates(lat, lng, distance="100", checkin_date=None, currency=TARGET_CURRENCY):
    """Query BWH GraphQL for hotels and rates near coordinates."""
    if not checkin_date:
        checkin_date = (datetime.date.today() + datetime.timedelta(days=14)).isoformat()
    checkout_date = (datetime.date.fromisoformat(checkin_date) + datetime.timedelta(days=1)).isoformat()

    query = """
    query SearchHotels($input: HotelSearchRequestInput!) {
      searchHotels(input: $input) {
        taxesAndFeesAvailable
        hotels {
          resort
          resortSummary {
            resort
            name
            latitude
            longitude
            currencyCode
            city
            country
            state
            stateCode
          }
          resortSearchRate {
            totalAmount
            totalAmountWithFeesAndTaxes
            averageNightlyRate
            averageNightlyAmountWithFeesAndTaxes
            resortRoomCategory
          }
          resortSearchPoint {
            totalPoints
          }
        }
      }
    }
    """
    payload = {
        "query": query,
        "variables": {
            "input": {
                "latitude": str(lat),
                "longitude": str(lng),
                "distance": str(distance),
                "distanceUnit": "mi",
                "targetCurrency": currency,
                "includeTaxesAndFees": True,
                "checkinDate": checkin_date,
                "checkoutDate": checkout_date,
                "numberOfRooms": "1"
            }
        }
    }
    try:
        r = requests.post(GQL_URL, json=payload, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            res_json = r.json() or {}
            data_node = res_json.get("data") or {}
            search_node = data_node.get("searchHotels") or {}
            hotels_list = search_node.get("hotels") or []
            return r.text, hotels_list
    except Exception as e:
        print(f"      [!] GQL Error: {e}")
    return None, []

def harvest_and_record_bestwestern(limit_hubs=None, grid_months=12):
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    dates = make_stratified_dates(months=grid_months)
    hubs = HUBS[:limit_hubs] if limit_hubs else HUBS
    total_rates = 0
    skipped_no_tax = 0
    write_errors = 0
    ok_calls = 0
    
    print(f"[BEST WESTERN] Harvesting {len(hubs)} clusters across {len(dates)} stratified dates ({dates[0]} -> {dates[-1]})...")
    
    for hub in hubs:
        hub_name = hub['name']
        print(f"\n=======================================================")
        print(f"--> Cluster Hub: {hub_name} ({hub['lat']}, {hub['lng']})")
        print(f"=======================================================")
        
        hub_slug = hub_name.split()[0].lower()
        
        for d_idx, stay_date in enumerate(dates, 1):
            raw_text, hotels = search_cluster_rates(hub['lat'], hub['lng'], distance=hub['dist'], checkin_date=stay_date)
            if not hotels or not raw_text:
                continue
            ok_calls += 1
            # Save raw evidence JSON per cluster date
            ev_fname = f"bw_cluster_{hub_slug}_{stay_date}.json"
            ev_fpath = os.path.join(EVIDENCE_DIR, ev_fname)
            with open(ev_fpath, "w", encoding="utf-8") as f:
                f.write(raw_text)
                
            rates_in_call = 0
            for h in hotels:
                resort_id = str(h.get("resort"))
                summ = h.get("resortSummary", {})
                name = summ.get("name") or f"Best Western {resort_id}"
                city = summ.get("city") or "Unknown"
                country = summ.get("country") or "Unknown"
                hotel_id = f"bw_{resort_id}"
                official_url = f"https://www.bestwestern.com/en-us/book/hotel-rooms/{resort_id}"
                
                # Upsert hotel into hotels table if missing
                cur.execute("SELECT id FROM hotels WHERE id = ?", (hotel_id,))
                if not cur.fetchone():
                    cur.execute("""
                        INSERT INTO hotels (
                            id, brand, name, city, country, currency, loyalty_model,
                            award_category, track_points, official_url, created_at,
                            lifecycle_status, status_updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        hotel_id, "BEST_WESTERN", name, city, country, (summ.get("currencyCode") or "Unknown"),
                        "BW_REWARDS", "STANDARD", 1, official_url,
                        now_iso, "ACTIVE", now_iso
                    ))
                    conn.commit()
                    
                rate_info = h.get("resortSearchRate") or {}
                pts_info = h.get("resortSearchPoint") or {}

                # 1. Try cluster-level tax-inclusive amount
                taxed = rate_info.get("averageNightlyAmountWithFeesAndTaxes")
                try:
                    taxed = float(taxed) if taxed is not None else None
                except (TypeError, ValueError):
                    taxed = None

                # 2. If cluster-level has no tax, query room level GetRoomsWithRatePlans
                if taxed is None or taxed <= 0:
                    raw_room_text, rooms_list = query_room_rate_plans(resort_id, stay_date)
                    if rooms_list and raw_room_text:
                        room_ev_fname = f"bw_room_{resort_id}_{stay_date}.json"
                        room_ev_fpath = os.path.join(EVIDENCE_DIR, room_ev_fname)
                        with open(room_ev_fpath, "w", encoding="utf-8") as rf:
                            rf.write(raw_room_text)

                        for rm in rooms_list:
                            rm_desc = rm.get("description") or f"Room {rm.get('roomId')}"
                            rm_cat = rm.get("roomCategoryCode") or rm.get("roomId") or "std"
                            rm_id = f"{hotel_id}_rm_{rm_cat}"
                            
                            cur.execute(
                                "INSERT OR IGNORE INTO room_categories (id, hotel_id, raw_name, standardized_type, max_occupancy) VALUES (?, ?, ?, 'UNKNOWN', 2)",
                                (rm_id, hotel_id, rm_desc[:255]),
                            )

                            # Lowest PUBLIC plan of this room (member-only plans are skipped). The price is the server's own
                            # tax-inclusive figure: averageNightlyRate when the plan states taxIncluded=true, else
                            # averageNightlyRateWithTaxes. A plan whose tax status the server does not state gives no row.
                            best = None
                            for rp in rm.get("ratePlans") or []:
                                if rp.get("isMemberRate") is True:
                                    continue
                                flag = rp.get("taxIncluded")
                                field = "averageNightlyRate" if flag is True else "averageNightlyRateWithTaxes"
                                try:
                                    val = float(rp.get(field)) if rp.get(field) is not None else None
                                except (TypeError, ValueError):
                                    val = None
                                if val and val > 0 and (best is None or val < best[0]):
                                    best = (val, rp, field, flag)
                            if best is not None:
                                p_rate, rp, field, flag = best
                                plan_name = rp.get("shortName") or "Standard"
                                pts = rp.get("fxAverageNightlyPoints")
                                try:
                                    write_authentic_rate_record(
                                        conn=conn,
                                        room_id=rm_id,
                                        stay_date_str=stay_date,
                                        raw_amount=p_rate,
                                        raw_currency=TARGET_CURRENCY,
                                        source_url=official_url,
                                        source_type="OFFICIAL_BESTWESTERN_BFF",
                                        raw_payload_str=raw_room_text,
                                        evidence_file=room_ev_fpath,
                                        points_required=pts,
                                        cash_rate_idr=None,
                                        tax_inclusive=True,
                                        notes=f"Best Western room BFF plan '{plan_name}' ({field}; server flag taxIncluded={flag}); currency = the one requested",
                                    )
                                    total_rates += 1
                                    rates_in_call += 1
                                except Exception as e:
                                    write_errors += 1
                                    if write_errors <= 5:
                                        print(f"      [!] row rejected ({stay_date}, {hotel_id}): {e}", flush=True)
                        continue
                    else:
                        skipped_no_tax += 1
                        continue

                points = pts_info.get("totalPoints") if pts_info else None
                room_code = rate_info.get("resortRoomCategory")
                room_name = f"UNKNOWN (Best Western room category code {room_code}; name not given by the source)"
                room_id = f"{hotel_id}_cat_{room_code}" if room_code else f"{hotel_id}_unknown_room"
                cur.execute(
                    "INSERT OR IGNORE INTO room_categories (id, hotel_id, raw_name, standardized_type, max_occupancy) VALUES (?, ?, ?, 'UNKNOWN', 2)",
                    (room_id, hotel_id, room_name[:255]),
                )
                try:
                    write_authentic_rate_record(
                        conn=conn,
                        room_id=room_id,
                        stay_date_str=stay_date,
                        raw_amount=taxed,
                        raw_currency=TARGET_CURRENCY,
                        source_url=official_url,
                        source_type="OFFICIAL_BESTWESTERN_BFF",
                        raw_payload_str=raw_text,
                        evidence_file=ev_fpath,
                        points_required=points,
                        cash_rate_idr=None,
                        tax_inclusive=True,
                        notes=f"Best Western GraphQL BFF, tax inclusive, converted by the server to {TARGET_CURRENCY} on request",
                    )
                    total_rates += 1
                    rates_in_call += 1
                except Exception as e:
                    write_errors += 1
                    if write_errors <= 5:
                        print(f"      [!] row rejected ({stay_date}, {hotel_id}): {e}", flush=True)

            print(f"    [{d_idx}/{len(dates)}] Date {stay_date}: {len(hotels)} hotels -> Recorded {rates_in_call} rates", flush=True)
            time.sleep(0.3) # Polite throttling
            
    conn.commit()
    conn.close()
    print(f"\n[DONE] {total_rates} Best Western rates stored; {skipped_no_tax} hotel-prices skipped (server gave no tax-inclusive price); {write_errors} rejected by the evidence gate.")
    if total_rates == 0:
        print("[!] ERROR: Fail-closed gate: 0 records harvested. Exiting with error code 1.")
        sys.exit(1)
    return total_rates

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Best Western Stratified Grid Harvester")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of hub clusters")
    parser.add_argument("--months", type=int, default=12, help="Number of months for date grid")
    args = parser.parse_args()

    print("=" * 70)
    print("  BEST WESTERN (BWH HOTELS) - 12-MONTH STRATIFIED GRID HARVESTER")
    print("=" * 70)
    harvest_and_record_bestwestern(limit_hubs=args.limit, grid_months=args.months)

if __name__ == "__main__":
    main()
