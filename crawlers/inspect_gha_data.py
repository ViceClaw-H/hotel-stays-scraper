import json
from curl_cffi import requests

r = requests.get('https://www.ghadiscovery.com/kempinski/the-apurva-kempinski-bali', impersonate='chrome124')
idx1 = r.text.find('__NEXT_DATA__')
if idx1 != -1:
    start = r.text.find('{', idx1)
    end = r.text.find('</script>', start)
    data = json.loads(r.text[start:end])
    props = data.get('props', {}).get('pageProps', {})
    print("GHA props keys:", list(props.keys()))
    hotel = props.get('hotel', {})
    if hotel:
        print("Hotel ID:", hotel.get('id'), "Code:", hotel.get('code'), "Name:", hotel.get('name'))
        print("Starting rate:", hotel.get('startingRate'), hotel.get('currency'))
        print("Rooms count:", len(hotel.get('rooms', [])))
        if hotel.get('rooms'):
            for room in hotel.get('rooms')[:3]:
                print("  Room:", room.get('name'), room.get('rate'))
