import json
import sys
from curl_cffi import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.wyndhamhotels.com/wyndham/jakarta-indonesia/wyndham-casablanca-jakarta/rooms-rates"
}

# Wyndham Casablanca Jakarta (Property ID: 52111)
url = "https://www.wyndhamhotels.com/BWSServices/services/hotels/availability/getRoomsAndRates?brand_id=WY&checkout_date=10-16-2026&checkin_date=10-15-2026&adults=1&children=0&rooms=1&propertyId=52111&isOrsId=52111&altPropId=52111&useWRPoints=true&language=en-us"

print(f"[*] Querying live CRS endpoint: {url}\n")
r = requests.get(url, headers=headers, impersonate="chrome124", timeout=15)
print(f"HTTP Status: {r.status_code}")

if r.status_code == 200:
    data = r.json()
    rooms_data = data.get("roomsAndRates", {}).get("rooms", [])
    print(f"✅ Total Real Room Types Returned: {len(rooms_data)}\n")
    
    for idx, room in enumerate(rooms_data, 1):
        print(f"--- [KAMAR #{idx}] ---")
        print(f"Room Type Code : {room.get('roomTypeCode')}")
        print(f"Description    : {room.get('description')[:100]}...")
        print(f"Bed Type       : {room.get('bedType')}")
        
        rates = room.get("rates", [])
        print(f"Rates Available: {len(rates)} penawaran harga:")
        for rate in rates:
            rate_name = rate.get("rateDescription") or rate.get("ratePlanCode") or "Published Rate"
            base_amt = rate.get("baseAmount")
            tot_amt = rate.get("totalAmount")
            curr = rate.get("currency")
            pts = rate.get("points") or rate.get("pointsRequired")
            print(f"  • {rate_name}")
            print(f"    - Cash Base : {curr} {base_amt}")
            print(f"    - Cash Total: {curr} {tot_amt}")
            print(f"    - Points    : {pts} pts")
        print()
