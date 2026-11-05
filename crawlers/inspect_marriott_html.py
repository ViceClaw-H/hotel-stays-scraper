import httpx
import re

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def inspect_marriott_html():
    url = "https://www.marriott.com/en-us/hotel-sitemap/indonesia-hotel-sitemap"
    r = httpx.get(url, headers=HEADERS, timeout=20.0, follow_redirects=True)
    all_links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text)
    print(f"Total <a> links found: {len(all_links)}")
    hotel_matches = []
    for href, text in all_links:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        if any(b in href for b in ["/marsha-", "-marriott-", "-hotel-", "-resort-", "-suites-", "-courtyard-", "-alof-", "-westin-", "-sheraton-", "-ritz-", "-st-regis-", "-autograph-", "-tribute-", "-le-meridien-", "-four-points-"]):
            hotel_matches.append((clean_text, href))
        elif "/hotels/" in href:
            hotel_matches.append((clean_text, href))

    print(f"Hotel matches in Indonesia: {len(hotel_matches)}")
    for name, href in hotel_matches[:15]:
        print(f"  • {name} -> {href}")

if __name__ == '__main__':
    inspect_marriott_html()
