import httpx
import re
import json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def inspect_marriott_json():
    url = "https://www.marriott.com/en-us/hotel-sitemap/indonesia-hotel-sitemap"
    r = httpx.get(url, headers=HEADERS, timeout=20.0, follow_redirects=True)
    
    # Check for __NEXT_DATA__ or json scripts
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', r.text, re.DOTALL)
    print(f"Found {len(scripts)} <script> tags.")
    for s in scripts:
        if "hotel" in s.lower() and ("name" in s or "marsha" in s.lower() or "title" in s):
            print(f"Script match ({len(s)} chars): {s[:300]}...")

    # Also search for direct marsha codes or hotel titles in HTML
    names = re.findall(r'"title":\s*"([^"]+Hotel[^"]*|[^"]*Resort[^"]*|[^"]*Suites[^"]*)"', r.text, re.IGNORECASE)
    print(f"Found {len(names)} hotel titles:")
    for n in names[:15]:
        print("  •", n)

if __name__ == '__main__':
    inspect_marriott_json()
