import httpx
import re
import json

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def inspect_hotel_pages():
    sample_codes = ['0338', '6183', '9010', '1295', '3144', '2704', '8839']
    for code in sample_codes:
        url = f"https://all.accor.com/hotel/{code}/index.en.shtml"
        try:
            r = httpx.get(url, headers=headers, timeout=15.0, follow_redirects=True)
            print(f"=== Hotel {code} | Status: {r.status_code} ===")
            
            # Title
            title_m = re.search(r'<title>(.*?)</title>', r.text, re.IGNORECASE)
            title = title_m.group(1).strip() if title_m else 'No Title'
            print(f"  Title: {title}")
            
            # JSON-LD scripts
            json_ld_matches = re.findall(r'<script type="application/ld\+json">([\s\S]*?)</script>', r.text)
            for raw_json in json_ld_matches:
                try:
                    data = json.loads(raw_json)
                    if isinstance(data, dict):
                        name = data.get('name')
                        address = data.get('address', {})
                        country = address.get('addressCountry', '') if isinstance(address, dict) else ''
                        city = address.get('addressLocality', '') if isinstance(address, dict) else ''
                        if name:
                            print(f"  JSON-LD Hotel: {name} | City: {city} | Country: {country}")
                except Exception as e:
                    pass
        except Exception as e:
            print(f"Error {code}: {e}")

if __name__ == '__main__':
    inspect_hotel_pages()
