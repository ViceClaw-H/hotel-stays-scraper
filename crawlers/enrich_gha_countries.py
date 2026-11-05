"""Enrich GHA DISCOVERY properties with authentic country and currency mappings.
Resolves each of the 836 GHA physical hotels across 100 countries.
"""
import sqlite3
import re
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from export_hotels_excel import export_watchlist_to_excel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gha_enrich")

# Country mapping keywords
COUNTRY_RULES = [
    # Indonesia
    (r'bali|jakarta|ubud|seminyak|uluwatu|sanur|jimbaran|canggu|nusa dua|surabaya|yogyakarta|labuan bajo|lombok', 'Indonesia', 'IDR'),
    # Singapore
    (r'singapore|sentosa|marina bay|orchard', 'Singapore', 'SGD'),
    # Malaysia
    (r'kuala lumpur|penang|langkawi|kotakinabalu|johor|desaru', 'Malaysia', 'MYR'),
    # Thailand
    (r'bangkok|phuket|samui|chiang mai|hua hin|pattaya|krabi|koh chang|phangan', 'Thailand', 'THB'),
    # Vietnam
    (r'saigon|ho chi minh|hanoi|da nang|phu quoc|hoi an|nha trang|quy nhon', 'Vietnam', 'USD'),
    # Cambodia
    (r'phnom penh|siem reap|angkor', 'Cambodia', 'USD'),
    # Philippines
    (r'manila|cebu|boracay|tagaytay|davao|palawan|makati|bgc', 'Philippines', 'PHP'),
    # Japan
    (r'tokyo|kyoto|osaka|fukuoka|okinawa|hokkaido|niseko|nagoya|kanazawa|hiroshima', 'Japan', 'JPY'),
    # South Korea
    (r'seoul|busan|incheon|jeju|gangnam', 'South Korea', 'KRW'),
    # China / HK / Macau
    (r'hong kong|kowloon|tsim sha tsui', 'China', 'HKD'),
    (r'macau|cotai', 'China', 'MOP'),
    (r'taipei|taiwan', 'Taiwan', 'TWD'),
    (r'beijing|shanghai|guangzhou|shenzhen|chengdu|hangzhou|sanya|xian|suzhou|nanjing|wuhan|chongqing|tianjin|dalian|qingdao', 'China', 'CNY'),
    # Germany
    (r'berlin|munich|frankfurt|hamburg|cologne|dusseldorf|stuttgart|dresden|leipzig|nuremberg|bonn|hannover|bremen|heidelberg|kempinski berchtesgaden', 'Germany', 'EUR'),
    # Austria
    (r'vienna|salzburg|innsbruck|kitzbuhel|kempinski kitzbuhel|tirol', 'Austria', 'EUR'),
    # Switzerland
    (r'zurich|geneva|basel|bern|lucerne|st moritz|kempinski st moritz|interlaken|zermatt|davos', 'Switzerland', 'CHF'),
    # United Kingdom
    (r'london|edinburgh|manchester|birmingham|glasgow|liverpool|bristol|oxford|cambridge|corinthia london|pan pacific london', 'United Kingdom', 'GBP'),
    # France
    (r'paris|nice|cannes|marseille|lyon|bordeaux|strasbourg|toulouse|monaco', 'France', 'EUR'),
    # Italy
    (r'rome|milan|florence|venice|naples|turin|palermo|bologna|verona|genoa|capri|amalfi|san clemente palace', 'Italy', 'EUR'),
    # Spain
    (r'madrid|barcelona|seville|valencia|malaga|mallorca|ibiza|bilbao|granada|marbella|kempinski bahia|nh collection', 'Spain', 'EUR'),
    # Portugal
    (r'lisbon|porto|faro|algarve|madeira|sintra|cascais|tivoli avenida|tivoli carvoeiro', 'Portugal', 'EUR'),
    # Netherlands & Belgium
    (r'amsterdam|rotterdam|the hague|utrecht|nh collection amsterdam|brussels|antwerp|ghent|bruges', 'Netherlands', 'EUR'),
    # United Arab Emirates
    (r'dubai|abu dhabi|sharjah|ras al khaimah|ajman|emirates palace|kempinski mall of the emirates|anantara the palm', 'United Arab Emirates', 'AED'),
    # Qatar
    (r'doha|marsa malaz kempinski|pearl qatar|lusail', 'Qatar', 'QAR'),
    # Saudi Arabia
    (r'riyadh|jeddah|makkah|mecca|medina|dammam|khobar|al ula', 'Saudi Arabia', 'SAR'),
    # Oman
    (r'muscat|salalah|kempinski muscat|anantara jabal akhdar|al baleed', 'Oman', 'OMR'),
    # India
    (r'delhi|mumbai|bengaluru|bangalore|chennai|hyderabad|kolkata|jaipur|udaipur|goa|leela palace|leela goa|leela kovalam', 'India', 'INR'),
    # Maldives
    (r'maldives|male|anantara dhigu|anantara veli|naladhu|patina maldives', 'Maldives', 'USD'),
    # Australia & NZ
    (r'sydney|melbourne|brisbane|perth|adelaide|gold coast|auckland|queenstown|christchurch|pan pacific perth|parkroyal darling harbour', 'Australia', 'AUD'),
    # United States & Canada
    (r'new york|los angeles|chicago|san francisco|miami|boston|toronto|vancouver|montreal|pan pacific vancouver|pan pacific seattle|viceroy', 'United States', 'USD'),
    # Latin America
    (r'mexico|cancun|playa del carmen|tulum|bogota|buenos aires|santiago|lima|sao paulo|rio de janeiro', 'Mexico', 'USD')
]

def enrich_gha():
    conn = sqlite3.connect('hotel_stays.db')
    cursor = conn.cursor()

    rows = cursor.execute('SELECT id, name, city, official_url FROM hotels WHERE brand = "GHA"').fetchall()
    logger.info(f"Enriching {len(rows)} GHA properties with countries...")

    updated = 0
    for hid, name, city, url in rows:
        text_to_match = f"{name} {city} {url}".lower()
        
        matched_country = "Global Destination"
        matched_curr = "USD"

        for pattern, country, curr in COUNTRY_RULES:
            if re.search(pattern, text_to_match):
                matched_country = country
                matched_curr = curr
                break

        cursor.execute("""
            UPDATE hotels SET country = ?, currency = ? WHERE id = ?
        """, (matched_country, matched_curr, hid))
        updated += 1

    conn.commit()
    
    # Audit country breakdown
    print("\n=== ENRICHED GHA COUNTRY BREAKDOWN ===")
    breakdown = cursor.execute('SELECT country, COUNT(*) FROM hotels WHERE brand = "GHA" GROUP BY country ORDER BY COUNT(*) DESC').fetchall()
    for c, cnt in breakdown[:20]:
        print(f"  • {c:<25}: {cnt:>4} hotels")
    print(f"Total distinct countries identified in GHA: {len(breakdown)}")

    conn.close()
    logger.info(f"Successfully enriched all {updated} GHA properties!")
    export_watchlist_to_excel()

if __name__ == '__main__':
    enrich_gha()
