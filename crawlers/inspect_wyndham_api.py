import json
import sys
from curl_cffi import requests

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.wyndhamhotels.com/wyndham/jakarta-indonesia/wyndham-casablanca-jakarta/rooms-rates"
}

# Wyndham Casablanca Jakarta Property ID: 52111
url = "https://www.wyndhamhotels.com/BWSServices/services/hotels/availability/getRoomsAndRates?brand_id=WY&hotel_id=52111&checkin_date=10-15-2026&checkout_date=10-16-2026&rooms=1&adults=1&children=0"

print(f"[*] Querying Wyndham REST API: {url}")
r = requests.get(url, headers=headers, impersonate="chrome124", timeout=15)
print("HTTP Status:", r.status_code)

if r.status_code == 200:
    data = r.json()
    print("Status in JSON:", data.get("status"))
    rooms_and_rates = data.get("roomsAndRates", {})
    rooms = rooms_and_rates.get("rooms", [])
    print(f"[*] Found {len(rooms)} REAL ROOM TYPES:")
    for room in rooms[:5]:
        print("\n--- ROOM TYPE ---")
        print("Room ID / Code:", room.get("roomTypeCode"))
        print("Room Name / Description:", room.get("description")[:80])
        rates = room.get("rates", [])
        print(f"Rates Count: {len(rates)}")
        for rate in rates[:2]:
            print("  Rate Name:", rate.get("rateDescription"))
            print("  Base Amount:", rate.get("baseAmount"), rate.get("currency"))
            print("  Total Amount (with Tax):", rate.get("totalAmount"))
            print("  Points Required:", rate.get("pointsRequired") or rate.get("points"))
