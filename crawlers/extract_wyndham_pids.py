import re
import json
from curl_cffi import requests

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

urls = [
    ("wyndham_casablanca", "https://www.wyndhamhotels.com/wyndham/jakarta-indonesia/wyndham-casablanca-jakarta/overview"),
    ("wyndham_jivva_bali", "https://www.wyndhamhotels.com/wyndham/klungkung-bali-indonesia/wyndham-tamansari-jivva-resort-bali/overview"),
    ("wyndham_garden_kuta", "https://www.wyndhamhotels.com/wyndham-garden/bali-indonesia/wyndham-garden-kuta-beach-bali/overview"),
    ("ramada_sunset_road", "https://www.wyndhamhotels.com/ramada/kuta-indonesia/ramada-bali-sunset-road-kuta/overview"),
    ("wyndham_opi_palembang", "https://www.wyndhamhotels.com/wyndham/palembang-indonesia/wyndham-opi-hotel-palembang/overview"),
    ("days_hotel_airport", "https://www.wyndhamhotels.com/days-inn/tangerang-indonesia/days-hotel-and-suites-jakarta-airport/overview")
]

print("=== Extracting Live Wyndham Property IDs ===")
for hid, u in urls:
    r = requests.get(u, headers=headers, impersonate="chrome124", timeout=10)
    brand_match = re.search(r'brandId[\":\s]+([A-Z0-9]+)', r.text, re.I)
    prop_match = re.search(r'(?:propertyId|hotelId)[\":\s]+([0-9]{4,6})', r.text, re.I)
    
    brand = brand_match.group(1) if brand_match else "WY"
    pid = prop_match.group(1) if prop_match else None
    print(f"{hid:<24} -> Brand: {brand:<4} | Property ID: {pid} | URL Status: {r.status_code}")
