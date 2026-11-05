import json
import re

with open('our-brands.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

s = json.dumps(data, ensure_ascii=False)
# Find brand links like href="/anantara" or href="/kempinski"
brands = re.findall(r'href=\\"/([a-z0-9-]+)\\"', s) + re.findall(r'"brandSlug":"([a-z0-9-]+)"', s) + re.findall(r'"brandName":"([^"]+)"', s)
unique_brands = sorted(set([b for b in brands if b not in ['about-us', 'destinations-map', 'our-brands', 'experiences', 'search', 'terms', 'privacy', 'offers', 'login']]))
print(f"Found {len(unique_brands)} GHA member brands:")
for b in unique_brands:
    print("  •", b)

with open('destinations-by-region.json', 'r', encoding='utf-8') as f:
    d_data = json.load(f)

ds = json.dumps(d_data, ensure_ascii=False)
countries = re.findall(r'href=\\"/([a-z0-9-]+)\\"', ds)
print(f"\nFound {len(set(countries))} candidate destinations in destinations-by-region:")
for c in sorted(set(countries))[:25]:
    print("  -", c)
