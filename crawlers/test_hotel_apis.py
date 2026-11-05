import json
import re
from datetime import date, timedelta
from curl_cffi import requests

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

# 1. IHG API rate test
print("--- 1. IHG Pondok Indah (JKTHA) ---")
checkin = (date.today() + timedelta(days=14)).strftime("%Y-%m-%d")
checkout = (date.today() + timedelta(days=15)).strftime("%Y-%m-%d")

ihg_url = f"https://www.ihg.com/hotels/api/v1/search/rates?hotelCode=JKTHA&checkInDate={checkin}&checkOutDate={checkout}&numberOfAdults=1&numberOfRooms=1"
try:
    r_ihg = requests.get(ihg_url, headers=headers, impersonate="chrome124", timeout=10)
    print("IHG API Status:", r_ihg.status_code)
    if r_ihg.status_code == 200:
        print("IHG Sample:", r_ihg.text[:300])
except Exception as e:
    print("IHG Error:", e)

# 2. Shangri-La API / Web check
print("\n--- 2. Shangri-La Jakarta ---")
shang_url = "https://www.shangri-la.com/en/jakarta/shangrila/"
try:
    r_shang = requests.get(shang_url, headers=headers, impersonate="chrome124", timeout=10)
    print("Shangri-La Web Status:", r_shang.status_code)
    if "__NEXT_DATA__" in r_shang.text:
        print("Found __NEXT_DATA__ in Shangri-La!")
except Exception as e:
    print("Shangri-La Error:", e)

# 3. Langham Jakarta
print("\n--- 3. Langham Jakarta ---")
langham_url = "https://www.langhamhotels.com/en/the-langham/jakarta/"
try:
    r_lang = requests.get(langham_url, headers=headers, impersonate="chrome124", timeout=10)
    print("Langham Web Status:", r_lang.status_code)
except Exception as e:
    print("Langham Error:", e)

# 4. GHA Kempinski Bali
print("\n--- 4. GHA Kempinski Bali ---")
gha_url = "https://www.ghadiscovery.com/kempinski/the-apurva-kempinski-bali"
try:
    r_gha = requests.get(gha_url, headers=headers, impersonate="chrome124", timeout=10)
    print("GHA Web Status:", r_gha.status_code)
    if "__NEXT_DATA__" in r_gha.text:
        print("Found __NEXT_DATA__ in GHA!")
except Exception as e:
    print("GHA Error:", e)

# 5. Wyndham Casablanca Jakarta
print("\n--- 5. Wyndham Casablanca Jakarta ---")
wynd_url = "https://www.wyndhamhotels.com/wyndham/jakarta-indonesia/wyndham-casablanca-jakarta/overview"
try:
    r_wynd = requests.get(wynd_url, headers=headers, impersonate="chrome124", timeout=10)
    print("Wyndham Web Status:", r_wynd.status_code)
except Exception as e:
    print("Wyndham Error:", e)
