import json

with open('accor_graphql_3.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

offers = d['data']['data']['bestOffers']['bestOffers']
print(f"Total offers in batch: {len(offers)}")
for idx, o in enumerate(offers[:8]):
    h = o.get('hotel', {})
    offer = o.get('offer', {})
    print(f"\n[{idx+1}] {h.get('name')} (Code: {h.get('code')}, Brand: {h.get('brand', {}).get('code')})")
    print(f"    City: {h.get('address', {}).get('city')} | Country: {h.get('address', {}).get('countryCode')}")
    print(f"    Pricing: {json.dumps(offer, indent=6)}")
