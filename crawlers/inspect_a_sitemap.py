import httpx
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def inspect_a_sitemap():
    url = 'https://all.accor.com/a/en.sitemap.xml'
    r = httpx.get(url, headers=headers, timeout=20.0, follow_redirects=True)
    print(f"Status: {r.status_code} | Size: {len(r.text)} bytes")
    entries = re.findall(r'<loc>([^<]+)</loc>', r.text)
    print(f"Found {len(entries)} URLs in a/en.sitemap.xml")
    for e in entries[:30]:
        print("  -", e)

if __name__ == '__main__':
    inspect_a_sitemap()
