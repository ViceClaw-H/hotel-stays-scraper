import json
import sys
from curl_cffi import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://reservations.brilliantbylangham.com/"
}

url = "https://reservations.brilliantbylangham.com/en-US/graphql?HotelList"

print(f"[*] Querying Langham Official Global Directory: {url}")
r = requests.get(url, headers=headers, impersonate="chrome124", timeout=15)
print(f"HTTP Status: {r.status_code}")

if r.status_code == 200:
    data = r.json()
    hotels = data.get("data", {}).get("content", {}).get("hotels", {}).get("edges", [])
    print(f"\n✅ Total Langham Global Properties Found: {len(hotels)}")
    
    langham_catalog = []
    for h in hotels:
        node = h.get("node", {})
        name = node.get("name")
        synxis_id = node.get("synxisHotelId")
        loc = node.get("_location", {})
        code = node.get("hotelCode") or node.get("code")
        print(f"• SynXis ID: {synxis_id:<6} | Code: {str(code):<6} | Name: {name}")
        langham_catalog.append({
            "name": name,
            "synxis_id": synxis_id,
            "code": code
        })

    with open("crawlers/langham_synxis_catalog.json", "w", encoding="utf-8") as f:
        json.dump(langham_catalog, f, indent=2, ensure_ascii=False)
    print("\nSaved catalog to crawlers/langham_synxis_catalog.json")
