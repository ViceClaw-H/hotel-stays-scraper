import json
import re
from curl_cffi import requests

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# 1. Inspect Shangri-La Jakarta rooms-suites page
url = "https://www.shangri-la.com/en/jakarta/shangrila/rooms-suites/"
print(f"[*] Fetching Shangri-La Jakarta rooms: {url}")
r = requests.get(url, headers=headers, impersonate="chrome124", timeout=15)
print("HTTP Status:", r.status_code)

if r.status_code == 200:
    # Check Next.js data or embedded json
    idx1 = r.text.find('__NEXT_DATA__')
    if idx1 != -1:
        s = r.text.find('{', idx1)
        e = r.text.find('</script>', s)
        try:
            data = json.loads(r.text[s:e])
            props = data.get("props", {}).get("pageProps", {})
            print("Next.js props keys:", list(props.keys()))
            rooms = props.get("rooms") or props.get("roomList") or props.get("content", {}).get("rooms") or []
            print(f"Found {len(rooms)} room categories in pageProps!")
            for rm in rooms[:5]:
                print("  Room:", rm.get("title") or rm.get("name") or rm.get("roomName"))
        except Exception as ex:
            print("JSON parse error:", ex)
