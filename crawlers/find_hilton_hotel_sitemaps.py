import httpx
import re

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def find_hilton_hotel_sitemaps():
    url = "https://www.hilton.com/sitemap/en/sitemap-en.xml"
    r = httpx.get(url, headers=HEADERS, timeout=20.0)
    sub_sm = re.findall(r'<loc>([^<]+)</loc>', r.text)
    print(f"Total sub-sitemaps in Hilton English index: {len(sub_sm)}")

    categories = {}
    for sm in sub_sm:
        prefix = re.sub(r'-\d+\.xml', '', sm.split('/')[-1])
        categories[prefix] = categories.get(prefix, 0) + 1

    print("Sub-sitemap breakdown by type:")
    for k, v in sorted(categories.items()):
        print(f"  • {k}: {v} files")

if __name__ == '__main__':
    find_hilton_hotel_sitemaps()
