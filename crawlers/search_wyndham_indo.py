import json
import sys
from curl_cffi import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.wyndhamhotels.com/"
}

search_url = "https://www.wyndhamhotels.com/BWSServices/services/search/property/search?destination=Indonesia&radius=500&checkin_date=10-15-2026&checkout_date=10-16-2026&adults=1&rooms=1"
print(f"[*] Querying Wyndham Regional Search: {search_url}")
r = requests.get(search_url, headers=headers, impersonate="chrome124", timeout=15)
print(f"Search Status: {r.status_code}")

if r.status_code == 200:
    data = r.json()
    props = data.get("properties", [])
    print(f"\n✅ Ditemukan {len(props)} Properti Wyndham di Indonesia:")
    for p in props:
        pid = p.get("id")
        name = p.get("name")
        city = p.get("city")
        state = p.get("stateProv")
        min_price = p.get("minPrice")
        curr = p.get("currencyCode")
        pts = p.get("freeStayPoints") or 0
        print(f"• ID: {pid:<6} | {name:<45} | {city}, {state} | Tarif Min: {curr} {min_price} | Poin: {pts} pts")
