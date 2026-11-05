from curl_cffi import requests
import re
import json

url = 'https://all.accor.com/hotel/0338/index.en.shtml'
r = requests.get(url, impersonate='chrome124')
print('Status:', r.status_code)

matches = re.findall(r'<script[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', r.text, re.DOTALL)
print(f"JSON-LD count: {len(matches)}")
for idx, m in enumerate(matches):
    try:
        data = json.loads(m.strip())
        print(f"Match {idx+1}:")
        if isinstance(data, dict):
            print("  @type:", data.get('@type'))
            print("  name:", data.get('name'))
            print("  address:", data.get('address'))
            print("  currenciesAccepted:", data.get('currenciesAccepted'))
    except Exception as e:
        print("Error:", e)
