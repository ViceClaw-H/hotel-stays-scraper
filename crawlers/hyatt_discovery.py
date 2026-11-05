import httpx
import re
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hyatt_discovery")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def discover_hyatt_sitemaps():
    logger.info("Inspecting Hyatt robots.txt and sitemap index...")
    try:
        r = httpx.get("https://www.hyatt.com/robots.txt", headers=HEADERS, timeout=15.0, follow_redirects=True)
        print(f"=== HYATT ROBOTS.TXT (Status: {r.status_code}) ===")
        sitemaps = re.findall(r'Sitemap:\s*([^\r\n]+)', r.text, re.IGNORECASE)
        print(f"Found {len(sitemaps)} sitemaps in robots.txt:")
        for sm in sitemaps:
            print("  •", sm)
    except Exception as e:
        print("Error robots.txt:", e)

    # Check common Hyatt sitemaps
    candidates = [
        "https://www.hyatt.com/sitemap.xml",
        "https://www.hyatt.com/sitemaps/en-US/hotel-sitemap.xml",
        "https://www.hyatt.com/sitemap-index.xml",
        "https://www.hyatt.com/hotel-sitemap.xml"
    ]
    for c in candidates:
        try:
            r = httpx.get(c, headers=HEADERS, timeout=15.0, follow_redirects=True)
            print(f"=== Check: {c} | Status: {r.status_code} | Size: {len(r.text)} bytes ===")
            if r.status_code == 200:
                locs = re.findall(r'<loc>([^<]+)</loc>', r.text)
                print(f"  Found {len(locs)} sub-entries in {c}")
                for l in locs[:5]:
                    print("    -", l)
        except Exception as e:
            print(f"Error checking {c}: {e}")

if __name__ == '__main__':
    discover_hyatt_sitemaps()
