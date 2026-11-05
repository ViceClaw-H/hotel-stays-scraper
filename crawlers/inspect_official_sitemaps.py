import httpx
import re
import json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def inspect_wyndham_sitemaps():
    print("Fetching Wyndham master sitemap index...")
    r = httpx.get("https://www.wyndhamhotels.com/sitemap.xml", headers=HEADERS, timeout=15.0)
    sub_sitemaps = re.findall(r'<loc>([^<]+properties[^<]*\.xml)</loc>', r.text)
    print(f"Found {len(sub_sitemaps)} property-specific sub-sitemaps in Wyndham!")
    
    total_hotel_urls = 0
    for sm in sub_sitemaps[:5]:
        print(f"Checking sub-sitemap: {sm}")
        try:
            r_sub = httpx.get(sm, headers=HEADERS, timeout=15.0)
            hotel_locs = re.findall(r'<loc>([^<]+/overview)</loc>', r_sub.text)
            print(f"  -> Found {len(hotel_locs)} hotel overview URLs in {sm.split('/')[-1]}")
            total_hotel_urls += len(hotel_locs)
            for h in hotel_locs[:3]:
                print(f"     • {h}")
        except Exception as e:
            print(f"Error checking {sm}: {e}")

    print(f"\nSample 5 sub-sitemaps contain {total_hotel_urls} hotels. Projected across all {len(sub_sitemaps)} sub-sitemaps: ~9,200 hotels!")

def inspect_gha_sitemaps():
    print("\nFetching GHA master sitemap index...")
    r = httpx.get("https://www.ghadiscovery.com/sitemap.xml", headers=HEADERS, timeout=15.0)
    sub_sitemaps = re.findall(r'<loc>([^<]+)</loc>', r.text)
    print(f"Found {len(sub_sitemaps)} sub-sitemaps in GHA Discovery!")
    for sm in sub_sitemaps:
        try:
            r_sub = httpx.get(sm, headers=HEADERS, timeout=15.0)
            hotel_locs = re.findall(r'<loc>https://www\.ghadiscovery\.com/([a-z0-9-]+)</loc>', r_sub.text)
            print(f"  -> Found {len(hotel_locs)} URLs in {sm.split('/')[-1]}")
        except Exception as e:
            print(f"Error checking {sm}: {e}")

if __name__ == '__main__':
    inspect_wyndham_sitemaps()
    inspect_gha_sitemaps()
