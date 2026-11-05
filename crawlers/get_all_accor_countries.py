import re
from curl_cffi import requests

def get_all_accor_countries():
    urls = [
        "https://all.accor.com/destinations/countries.en.shtml",
        "https://all.accor.com/destinations/index.en.shtml",
        "https://all.accor.com/sitemap.xml"
    ]
    countries = set()
    for u in urls:
        try:
            r = requests.get(u, impersonate="chrome124", timeout=15)
            if r.status_code == 200:
                # Find country slugs
                slugs = re.findall(r'/hotels/([a-z0-9\-]+)', r.text)
                for s in slugs:
                    if s not in ["index", "search", "all", "accor"]:
                        countries.add(s)
        except Exception as e:
            print(f"Error fetching {u}: {e}")

    print(f"Total Unique Accor Countries Found: {len(countries)}")
    print("Countries list:", sorted(list(countries)))

if __name__ == '__main__':
    get_all_accor_countries()
