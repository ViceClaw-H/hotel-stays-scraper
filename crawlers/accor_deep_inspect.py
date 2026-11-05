import httpx
import re
import json

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def inspect_accor():
    urls = [
        'https://all.accor.com/country-selection/index.en.shtml',
        'https://all.accor.com/en/destination/index.shtml',
        'https://all.accor.com/en/city/index.shtml',
        'https://all.accor.com/robots.txt'
    ]
    for url in urls:
        try:
            r = httpx.get(url, headers=headers, timeout=15.0, follow_redirects=True)
            print(f"=== URL: {url} | Status: {r.status_code} ===")
            if 'robots.txt' in url:
                print(r.text[:1000])
            else:
                # Look for country links
                country_links = re.findall(r'href="([^"]*(?:country|destination|city|hotel)[^"]*)"', r.text)
                print(f"Found {len(country_links)} relevant links")
                for cl in set(country_links)[:15]:
                    print("  -", cl)
        except Exception as e:
            print(f"Error {url}: {e}")

if __name__ == '__main__':
    inspect_accor()
