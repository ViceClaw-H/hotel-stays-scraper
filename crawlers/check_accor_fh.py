import httpx
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def check_fh_sitemap():
    url = 'https://all.accor.com/sitemap-fh.en.xml'
    r = httpx.get(url, headers=headers, timeout=30.0, follow_redirects=True)
    print(f"Status: {r.status_code} | Size: {len(r.text)} bytes")
    entries = re.findall(r'<loc>([^<]+)</loc>', r.text)
    print(f"Total hotel URLs in official sitemap: {len(entries)}")
    for e in entries[:20]:
        print("  -", e)
    
    # Save a sample of URLs to analyze
    with open('accor_urls_sample.txt', 'w', encoding='utf-8') as f:
        for e in entries:
            f.write(e + '\n')

if __name__ == '__main__':
    check_fh_sitemap()
