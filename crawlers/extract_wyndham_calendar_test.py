"""Compliant test-batch calendar scraper for Wyndham Rewards (Indonesia). v3.

v1 of this script queried the Wyndham regional/destination search endpoint
(BWSServices/services/search/property/search). Root-cause investigation on
2026-09-15 found that endpoint now returns HTTP 400 "Mandatory fields missing"
for every request -- reproduced across multiple dates and header variants,
including the exact URL previously assumed to be confirmed-working. It is not
the endpoint that produced this project's real Wyndham data.

The endpoint that actually produced the 10,759 existing OFFICIAL_WYNDHAM_CRS
rate records was recovered directly from those records' own source_url:

    https://www.wyndhamhotels.com/BWSServices/services/hotels/availability/getRoomsAndRates
        ?brand_id=<2-letter>&checkin_date=MM-DD-YYYY&checkout_date=MM-DD-YYYY
        &adults=1&children=0&rooms=1
        &propertyId=<numeric>&isOrsId=<numeric>&altPropId=<numeric>
        &useWRPoints=true&language=en-us

This is a per-property, per-night availability endpoint (confirmed live-working
on 2026-09-15, including for dates past the existing calendar ceiling). This
script:
  1. For each catalogued Indonesia Wyndham hotel that already has at least one
     real OFFICIAL_WYNDHAM_CRS rate record, recovers its real propertyId and
     brand_id straight from that record's own source_url. Hotels with no prior
     CRS history are skipped -- never guessed.
  2. Queries getRoomsAndRates for each such hotel, for a handful of NEW nights
     just past the current calendar ceiling (2026-11-29 per the last audit).
  3. Saves the raw JSON response as on-disk evidence (SHA-256 hashed by the
     provenance gate) under evidence/wyndham/calendar/, matching the existing
     wyndham_{propertyId}_{checkin}_{checkout}.json convention already used by
     the historical evidence in that directory.
  4. For every room type in the response, reuses (or creates) the matching
     room_category -- keyed {hotel_id}_{roomTypeCode}, the same convention
     already used by every existing Wyndham room record -- and writes one rate
     record per room type via engine.rate_writer (which itself calls
     engine.provenance_gate). Never writes rate_records directly.

Cash rate and points selection logic (verified against known-correct existing
DB rows for propertyId=50061 / 2026-11-29 before use):
  - cash_rate = the lowest nightRatesAfterTax among rate plans that are NOT
    points-redemption plans (fnsRatePlan) and have a positive amount.
  - points_required = the lowest fnsPoints/totalFnsPoints among redemption
    rate plans that are actually qualified/bookable (qualified: true); left
    unset if no qualified redemption plan exists for that room on that date
    (this exactly reproduces why some existing rooms have NULL points and
    others don't).

source_type stays "OFFICIAL_WYNDHAM_BWS_API" (the only Wyndham value in
engine/provenance_gate.py's allow-list) even though this hits the
availability sub-path rather than the search sub-path the label was
originally written for -- both live under wyndhamhotels.com/BWSServices/.
The historical label "OFFICIAL_WYNDHAM_CRS" used by the pre-existing 10,759
records is no longer in the allow-list, so it cannot be reused for new
writes without editing the gate, which is out of scope here.

v3 fix: the Indonesia Wyndham catalog contains duplicate `hotels.id` rows for
the same physical property (same propertyId) -- e.g. 'ramada_sunset_road' and
'wynd_ramadabalisunsetroadkuta' are both propertyId 50061. v2 looped per
hotel_id, so duplicates re-fetched and overwrote the *same* evidence file
path multiple times per night; on nights where Wyndham's live response
drifted between those near-duplicate calls, `cli.py verify` caught 79
resulting SHA-256 hash mismatches (an earlier write's stored hash no longer
matched the file a later call had overwritten it with). v3 groups hotels by
(propertyId, brand_id) and fetches each physical property exactly once per
night; every duplicate hotel_id then writes from that single shared
response and evidence file, which both removes the collision and halves
the request volume for the affected properties. Re-running v3 repairs the
79 broken rows in place (same UNIQUE(room_id, stay_date) + INSERT OR
REPLACE path every write already uses).

Run this from the project root (where hotel_stays.db lives):
    python crawlers\\extract_wyndham_calendar_test.py
"""
import os
import sys
import time
import sqlite3
from datetime import date, timedelta
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from curl_cffi import requests
from engine.rate_writer import write_authentic_rate_record
from engine.provenance_gate import ProvenanceViolationError

DB_PATH = "hotel_stays.db"
EVIDENCE_DIR = os.path.join("evidence", "wyndham", "calendar")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.wyndhamhotels.com/",
}

TEST_COUNTRY_DB_VALUE = "Indonesia"
START_DATE = date(2026, 11, 30)  # one day past the last audited Wyndham stay_date (2026-11-29)
NUM_NIGHTS_TO_TEST = 7
REQUEST_DELAY_SEC = 1.5
SOURCE_TYPE = "OFFICIAL_WYNDHAM_BWS_API"


def load_hotels_with_known_property_id(conn, country: str):
    """For each catalogued Wyndham hotel in `country` that already has at least
    one OFFICIAL_WYNDHAM_CRS rate record, recover its real propertyId + brand_id
    from that record's own historical source_url. Conservative: hotels with no
    prior CRS history are skipped, never guessed."""
    c = conn.cursor()
    rows = c.execute(
        """
        SELECT h.id, h.name, rr.source_url, rr.stay_date
        FROM hotels h
        JOIN room_categories rc ON rc.hotel_id = h.id
        JOIN rate_records rr ON rr.room_id = rc.id
        WHERE h.brand = 'WYNDHAM' AND h.country = ? AND rr.source_type = 'OFFICIAL_WYNDHAM_CRS'
        ORDER BY h.id, rr.stay_date DESC
        """,
        (country,),
    ).fetchall()

    hotels = {}
    for hotel_id, name, source_url, stay_date_val in rows:
        if hotel_id in hotels:
            continue  # keep only the most recent source_url per hotel (rows sorted DESC)
        qs = parse_qs(urlparse(source_url).query)
        property_id = qs.get("propertyId", [None])[0]
        brand_id = qs.get("brand_id", [None])[0]
        if not property_id or not brand_id:
            continue
        hotels[hotel_id] = {
            "id": hotel_id,
            "name": name,
            "property_id": property_id,
            "brand_id": brand_id,
            "last_stay_date": stay_date_val,
        }
    return list(hotels.values())


def ensure_room_category(conn, hotel_id: str, room_type_code: str, description: str) -> str:
    room_id = f"{hotel_id}_{room_type_code}"
    c = conn.cursor()
    existing = c.execute("SELECT id FROM room_categories WHERE id = ?", (room_id,)).fetchone()
    if not existing:
        c.execute(
            """INSERT INTO room_categories (id, hotel_id, raw_name, standardized_type, max_occupancy)
               VALUES (?, ?, ?, ?, ?)""",
            (room_id, hotel_id, (description or room_type_code)[:255], "STANDARD", 2),
        )
        conn.commit()
    return room_id


def fetch_rooms_and_rates(property_id: str, brand_id: str, checkin: date, checkout: date):
    url = (
        "https://www.wyndhamhotels.com/BWSServices/services/hotels/availability/getRoomsAndRates"
        f"?brand_id={brand_id}"
        f"&checkout_date={checkout.strftime('%m-%d-%Y')}&checkin_date={checkin.strftime('%m-%d-%Y')}"
        "&adults=1&children=0&rooms=1"
        f"&propertyId={property_id}&isOrsId={property_id}&altPropId={property_id}"
        "&useWRPoints=true&language=en-us"
    )
    r = requests.get(url, headers=HEADERS, impersonate="chrome124", timeout=20)
    return url, r


def pick_cash_and_points(rates):
    """From a room's rate-plan list, pick the lowest genuine cash rate plan and
    (if one exists and is actually bookable) the lowest-points qualified
    redemption plan. Never guesses: returns (None, None, None) if no usable
    cash plan is present for this room on this date."""
    cash_plans = []
    redemption_points = []
    for rate in rates or []:
        amounts = rate.get("nightRatesAfterTax") or []
        amount = amounts[0] if amounts else None
        if rate.get("fnsRatePlan"):
            if rate.get("qualified"):
                pts = rate.get("fnsPoints") or rate.get("totalFnsPoints")
                if pts:
                    redemption_points.append(pts)
            continue
        if amount and amount > 0:
            cash_plans.append((amount, rate.get("currencyCode")))

    if not cash_plans:
        return None, None, None

    best_amount, best_currency = min(cash_plans, key=lambda x: x[0])
    best_points = min(redemption_points) if redemption_points else None
    return best_amount, best_currency, best_points


def group_hotels_by_property(hotels):
    """The catalog contains duplicate hotels.id rows for the same physical
    property (same propertyId) -- e.g. 'ramada_sunset_road' and
    'wynd_ramadabalisunsetroadkuta' are both propertyId 50061. Group them so
    each physical property is fetched exactly ONCE per night; every duplicate
    hotel_id then writes from that single shared response. Fetching per
    hotel_id instead (as v2 originally did) hits the *same* evidence file
    path multiple times per night; when Wyndham's live response drifted
    between those near-duplicate calls, the earlier write's stored SHA-256
    hash no longer matched the file a later call overwrote it with -- this
    is exactly what caused the 79 hash mismatches `cli.py verify` caught
    after the first v2 run. Grouping removes the collision at the source
    instead of papering over it."""
    groups = {}
    for h in hotels:
        key = (h["property_id"], h["brand_id"])
        groups.setdefault(key, []).append(h)
    return list(groups.values())


def run_test_batch():
    print("=" * 70)
    print(" WYNDHAM CALENDAR TEST BATCH v3 (Official BWS getRoomsAndRates, per-property, deduped) ")
    print("=" * 70)
    print(f"Date range  : {START_DATE} .. {START_DATE + timedelta(days=NUM_NIGHTS_TO_TEST - 1)} ({NUM_NIGHTS_TO_TEST} nights)")
    print(f"Evidence dir: {EVIDENCE_DIR}")
    print()

    os.makedirs(EVIDENCE_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    hotels = load_hotels_with_known_property_id(conn, TEST_COUNTRY_DB_VALUE)
    groups = group_hotels_by_property(hotels)
    print(f"[*] Recovered real propertyId/brand_id for {len(hotels)} catalogued {TEST_COUNTRY_DB_VALUE} Wyndham hotels with prior CRS history.")
    print(f"[*] Grouped into {len(groups)} distinct physical properties (catalog has duplicate hotel_id rows for some).")
    for group in groups:
        ids = ", ".join(h["id"] for h in group)
        print(f"    - propertyId={group[0]['property_id']} brand_id={group[0]['brand_id']}: {ids}")
    print()

    total_written = 0
    total_rooms_seen = 0
    total_rooms_no_cash = 0
    total_skipped_existing = 0
    total_request_failures = 0

    for group in groups:
        primary = group[0]
        for night_offset in range(NUM_NIGHTS_TO_TEST):
            checkin = START_DATE + timedelta(days=night_offset)
            checkout = checkin + timedelta(days=1)
            stay_date_str = checkin.strftime("%Y-%m-%d")

            try:
                url, r = fetch_rooms_and_rates(primary["property_id"], primary["brand_id"], checkin, checkout)
            except Exception as e:
                print(f"[!] propertyId={primary['property_id']} {stay_date_str}: request failed: {e}")
                total_request_failures += 1
                continue

            if r.status_code != 200:
                print(f"[!] propertyId={primary['property_id']} {stay_date_str}: HTTP {r.status_code}, skipping.")
                total_request_failures += 1
                continue

            raw_bytes = r.content
            evidence_path = os.path.join(
                EVIDENCE_DIR, f"wyndham_{primary['property_id']}_{checkin}_{checkout}.json"
            )
            with open(evidence_path, "wb") as f:
                f.write(raw_bytes)

            try:
                data = r.json()
            except Exception as e:
                print(f"[!] propertyId={primary['property_id']} {stay_date_str}: could not parse JSON ({e}), evidence saved but skipping ingestion.")
                continue

            if data.get("status") != "OK":
                print(f"[!] propertyId={primary['property_id']} {stay_date_str}: API status '{data.get('status')}', skipping.")
                continue

            rooms = data.get("roomsAndRates", {}).get("rooms", [])
            hotel_ids_str = ", ".join(h["id"] for h in group)
            print(f"[propertyId={primary['property_id']} {stay_date_str}] {len(rooms)} room types -> applies to {len(group)} catalog hotel(s): {hotel_ids_str}. Evidence: {evidence_path}")

            for room in rooms:
                total_rooms_seen += 1
                room_type_code = room.get("roomTypeCode")
                short_name = room.get("shortName") or room_type_code
                if not room_type_code:
                    continue

                amount, currency, points = pick_cash_and_points(room.get("rates"))
                if amount is None:
                    total_rooms_no_cash += 1
                    continue

                # Same physical property, same fetch -- but every duplicate catalog
                # hotel_id gets its own room_category + rate_record (they're distinct
                # rows in `hotels`), all pointing at this one shared evidence file.
                for hotel in group:
                    room_id = ensure_room_category(conn, hotel["id"], room_type_code, short_name)
                    try:
                        write_authentic_rate_record(
                            conn=conn,
                            room_id=room_id,
                            stay_date_str=stay_date_str,
                            raw_amount=float(amount),
                            raw_currency=currency or "IDR",
                            source_url=url,
                            source_type=SOURCE_TYPE,
                            evidence_file=evidence_path,
                            points_required=int(points) if points else None,
                            tax_inclusive=True,
                            notes="Official Wyndham BWS getRoomsAndRates (per-property availability) - Indonesia calendar extension; cash_rate is the lowest non-redemption rate plan for this room type and date",
                        )
                        total_written += 1
                    except ProvenanceViolationError as e:
                        print(f"    REJECTED by provenance gate for '{short_name}' ({hotel['id']}): {e}")
                    except sqlite3.IntegrityError as e:
                        total_skipped_existing += 1
                        print(f"    SKIP (already exists): '{short_name}' ({hotel['id']}) {stay_date_str}: {e}")
                pts_str = f" / {points:,} pts" if points else ""
                print(f"    OK: {short_name} -> {currency} {amount:,.0f}{pts_str} (written for {len(group)} hotel id(s))")

            time.sleep(REQUEST_DELAY_SEC)

    conn.close()

    print("\n" + "=" * 70)
    print(" TEST BATCH COMPLETE ")
    print("=" * 70)
    print(f"Hotels queried            : {len(hotels)} ({len(groups)} distinct physical properties)")
    print(f"Nights per hotel          : {NUM_NIGHTS_TO_TEST}")
    print(f"Room-type offers seen     : {total_rooms_seen}")
    print(f"Rate records written      : {total_written}")
    print(f"Rooms with no cash rate   : {total_rooms_no_cash}")
    print(f"Already existed (skipped) : {total_skipped_existing}")
    print(f"Request failures          : {total_request_failures}")
    print()
    print("Next steps:")
    print("  1. python cli.py verify   -- confirm 100% SHA-256 evidence parity still holds")
    print("  2. python cli.py audit    -- confirm 0 synthetic records")
    print("  3. python cli.py test     -- run the full integrity test suite")


if __name__ == "__main__":
    run_test_batch()
