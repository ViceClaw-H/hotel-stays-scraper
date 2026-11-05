import httpx
import re
import json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def check_brand_sitemaps():
    targets = {
        "IHG": [
            "https://www.ihg.com/robots.txt",
            "https://www.ihg.com/hotels/gb/en/sitemap.xml",
            "https://www.ihg.com/sitemap.xml"
        ],
        "WYNDHAM": [
            "https://www.wyndhamhotels.com/robots.txt",
            "https://www.wyndhamhotels.com/sitemap.xml",
            "https://www.wyndhamhotels.com/locations"
        ],
        "SHANGRI_LA": [
            "https://www.shangri-la.com/robots.txt",
            "https://www.shangri-la.com/sitemap.xml"
        ],
        "LANGHAM": [
            "https://www.langhamhotels.com/robots.txt",
            "https://www.langhamhotels.com/sitemap.xml"
        ],
        "HILTON": [
            "https://www.hilton.com/robots.txt",
            "https://www.hilton.com/sitemap.xml"
        ],
        "MARRIOTT": [
            "https://www.marriott.com/robots.txt",
            "https://www.marriott.com/sitemap.xml"
        ],
        "GHA": [
            "https://www.ghadiscovery.com/robots.txt",
            "https://www.ghadiscovery.com/sitemap.xml"
        ]
    }

    for brand, urls in targets.items():
        print(f"\n==================== {brand} ====================")
        for u in urls:
            try:
                r = httpx.get(u, headers=HEADERS, timeout=12.0, follow_redirects=True)
                print(f"[{r.status_code}] {u} (Length: {len(r.text)} bytes)")
                if r.status_code == 200:
                    sitemaps = re.findall(r'Sitemap:\s*([^\r\n]+)', r.text, re.IGNORECASE)
                    if sitemaps:
                        print(f"  Found {len(sitemaps)} sitemaps in robots.txt:")
                        for sm in sitemaps[:3]:
                            print("    -", sm)
                    elif "<loc>" in r.text:
                        locs = re.findall(r'<loc>([^<]+)</loc>', r.text)
                        print(f"  Found {len(locs)} XML entries in sitemap:")
                        for l in locs[:5]:
                            print("    -", l)
            except Exception as e:
                print(f"Error checking {u}: {e}")

if __name__ == '__main__':
    check_brand_sitemaps()
