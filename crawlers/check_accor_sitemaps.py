import httpx
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def check_sitemaps():
    sitemaps = [
        'https://all.accor.com/sitemap-fh.xml',
        'https://all.accor.com/a/sitemap.xml'
    ]
    for sm in sitemaps:
        try:
            r = httpx.get(sm, headers=headers, timeout=20.0, follow_redirects=True)
            print(f"=== SITEMAP: {sm} | Status: {r.status_code} | Length: {len(r.text)} ===")
            sub_sitemaps = re.findall(r'<loc>([^<]+)</loc>', r.text)
            print(f"Found {len(sub_sitemaps)} entries in {sm}")
            for entry in sub_sitemaps[:10]:
                print("  -", entry)
        except Exception as e:
            print(f"Error {sm}: {e}")

if __name__ == '__main__':
    check_sitemaps()
