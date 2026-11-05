import json
import sys
from curl_cffi import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://reservations.brilliantbylangham.com/"
}

query = """query {
  content {
    hotels(first: 1000) {
      totalCount
      edges {
        node {
          name
          synxisHotelId
          taxExclusive
          isLive
          _contentInfo {
            id
          }
        }
      }
    }
  }
}"""

payload = {
    "query": query,
    "variables": None
}

url = "https://reservations.brilliantbylangham.com/en-US/graphql?HotelList"
print(f"[*] Sending GraphQL POST to: {url}")
r = requests.post(url, json=payload, headers=headers, impersonate="chrome124", timeout=15)
print(f"HTTP Status: {r.status_code}")

if r.status_code == 200:
    data = r.json()
    hotels = data.get("data", {}).get("content", {}).get("hotels", {}).get("edges", [])
    print(f"\n✅ Total Langham Global Properties: {len(hotels)}")
    
    catalog = []
    for h in hotels:
        node = h.get("node", {})
        name = node.get("name")
        synxis_id = node.get("synxisHotelId")
        is_live = node.get("isLive")
        print(f"• SynXis ID: {str(synxis_id):<6} | Live: {str(is_live):<5} | {name}")
        catalog.append({
            "name": name,
            "synxis_id": synxis_id,
            "is_live": is_live
        })

    with open("crawlers/langham_global_catalog.json", "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print("\nSaved 33 properties to crawlers/langham_global_catalog.json")
