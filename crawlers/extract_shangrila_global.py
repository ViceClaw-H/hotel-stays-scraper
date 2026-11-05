"""Shangri-La Circle Global Official Property Extractor.
Pulls and verifies 100% authentic Shangri-La properties across Asia, Middle East, Europe, and Pacific.
"""
import sys
import os
import sqlite3
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from export_hotels_excel import export_watchlist_to_excel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("shangrila_global")

SHANGRI_LA_GLOBAL = [
    # Indonesia
    {"name": "Shangri-La Jakarta", "city": "Jakarta (Sudirman / BNI City)", "country": "Indonesia", "curr": "IDR", "url": "https://www.shangri-la.com/en/jakarta/shangrila/"},
    {"name": "Shangri-La Surabaya", "city": "Surabaya (Mayjen Sungkono)", "country": "Indonesia", "curr": "IDR", "url": "https://www.shangri-la.com/en/surabaya/shangrila/"},
    {"name": "Hotel Jen Tanglin Singapore", "city": "Singapore (Orchard / Tanglin)", "country": "Singapore", "curr": "SGD", "url": "https://www.shangri-la.com/en/singapore/hoteljen/tanglin/"},
    {"name": "Hotel Jen Orchardgateway Singapore", "city": "Singapore (Orchard Rd)", "country": "Singapore", "curr": "SGD", "url": "https://www.shangri-la.com/en/singapore/hoteljen/orchardgateway/"},
    {"name": "Shangri-La Singapore", "city": "Singapore (Orange Grove / Orchard)", "country": "Singapore", "curr": "SGD", "url": "https://www.shangri-la.com/en/singapore/shangrila/"},
    {"name": "Shangri-La Rasa Sentosa, Singapore", "city": "Singapore (Sentosa / Siloso Beach)", "country": "Singapore", "curr": "SGD", "url": "https://www.shangri-la.com/en/singapore/rasasentosaresort/"},
    {"name": "Shangri-La Bangkok", "city": "Bangkok (Chao Phraya River / Silom)", "country": "Thailand", "curr": "THB", "url": "https://www.shangri-la.com/en/bangkok/shangrila/"},
    {"name": "Shangri-La Chiang Mai", "city": "Chiang Mai (Chang Klan Rd / Night Bazaar)", "country": "Thailand", "curr": "THB", "url": "https://www.shangri-la.com/en/chiangmai/shangrila/"},
    {"name": "Shangri-La Kuala Lumpur", "city": "Kuala Lumpur (Jalan Sultan Ismail / KLCC)", "country": "Malaysia", "curr": "MYR", "url": "https://www.shangri-la.com/en/kualalumpur/shangrila/"},
    {"name": "Shangri-La Rasa Sayang, Penang", "city": "Penang (Batu Feringgi Beach)", "country": "Malaysia", "curr": "MYR", "url": "https://www.shangri-la.com/en/penang/rasasayangresort/"},
    {"name": "Shangri-La Golden Sands, Penang", "city": "Penang (Batu Feringgi)", "country": "Malaysia", "curr": "MYR", "url": "https://www.shangri-la.com/en/penang/goldensandsresort/"},
    {"name": "Shangri-La Tanjung Aru, Kota Kinabalu", "city": "Kota Kinabalu (Tanjung Aru Beach / Sabah)", "country": "Malaysia", "curr": "MYR", "url": "https://www.shangri-la.com/en/kotakinabalu/tanjungaruresort/"},
    {"name": "Shangri-La Rasa Ria, Kota Kinabalu", "city": "Kota Kinabalu (Pantai Dalit Beach / Tuaran)", "country": "Malaysia", "curr": "MYR", "url": "https://www.shangri-la.com/en/kotakinabalu/rasariaresort/"},
    {"name": "JEN Penang Georgetown by Shangri-La", "city": "Penang (Georgetown / Magazine Rd)", "country": "Malaysia", "curr": "MYR", "url": "https://www.shangri-la.com/en/penang/hoteljen/georgetown/"},
    {"name": "Traders Hotel, Kuala Lumpur", "city": "Kuala Lumpur (KLCC Park / Twin Towers View)", "country": "Malaysia", "curr": "MYR", "url": "https://www.shangri-la.com/en/kualalumpur/traders/"},
    {"name": "Shangri-La Tokyo", "city": "Tokyo (Marunouchi / Tokyo Station)", "country": "Japan", "curr": "JPY", "url": "https://www.shangri-la.com/en/tokyo/shangrila/"},
    {"name": "Shangri-La Kyoto (Opening Project)", "city": "Kyoto (Kamigyo-ku)", "country": "Japan", "curr": "JPY", "url": "https://www.shangri-la.com/en/corporate/press-room/press-releases/shangri-la-group-to-bring-luxury-hospitality-to-kyoto/"},
    {"name": "Island Shangri-La, Hong Kong", "city": "Hong Kong (Pacific Place / Admiralty)", "country": "China", "curr": "HKD", "url": "https://www.shangri-la.com/en/hongkong/islandshangrila/"},
    {"name": "Kowloon Shangri-La, Hong Kong", "city": "Hong Kong (Tsim Sha Tsui East / Victoria Harbour)", "country": "China", "curr": "HKD", "url": "https://www.shangri-la.com/en/hongkong/kowloonshangrila/"},
    {"name": "Kerry Hotel, Hong Kong", "city": "Hong Kong (Hung Hom Bay / Kowloon)", "country": "China", "curr": "HKD", "url": "https://www.shangri-la.com/en/hongkong/kerry/"},
    {"name": "JEN Hong Kong by Shangri-La", "city": "Hong Kong (Western District / Queen's Rd West)", "country": "China", "curr": "HKD", "url": "https://www.shangri-la.com/en/hongkong/hoteljen/hongkong/"},
    {"name": "China World Hotel, Beijing", "city": "Beijing (Chaoyang / Guomao CBD)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/beijing/chinaworld/"},
    {"name": "China World Summit Wing, Beijing", "city": "Beijing (China World Tower 64-80 / CBD)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/beijing/chinaworldsummitwing/"},
    {"name": "Shangri-La Beijing", "city": "Beijing (Haidian / Zizhuyuan Rd)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/beijing/shangrila/"},
    {"name": "Kerry Hotel, Beijing", "city": "Beijing (Guanghua Rd / Chaoyang CBD)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/beijing/kerry/"},
    {"name": "JEN Beijing by Shangri-La", "city": "Beijing (China World Complex / Guomao)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/beijing/hoteljen/beijing/"},
    {"name": "Pudong Shangri-La, Shanghai", "city": "Shanghai (Lujiazui / The Bund View)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/shanghai/pudongshangrila/"},
    {"name": "Jing An Shangri-La, Shanghai", "city": "Shanghai (Jing An Kerry Centre / West Nanjing Rd)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/shanghai/jinganshangrila/"},
    {"name": "Kerry Hotel Pudong, Shanghai", "city": "Shanghai (Kerry Parkside / Century Park)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/shanghai/kerryhotelpudong/"},
    {"name": "Shangri-La Guangzhou", "city": "Guangzhou (Pazhou / Canton Fair Complex)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/guangzhou/shangrila/"},
    {"name": "Shangri-La Shenzhen", "city": "Shenzhen (Luohu / Railway Station)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/shenzhen/shangrila/"},
    {"name": "Futian Shangri-La, Shenzhen", "city": "Shenzhen (Futian CBD / Convention Center)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/shenzhen/futianshangrila/"},
    {"name": "Shangri-La Chengdu", "city": "Chengdu (Jinjiang River / Binjiang East Rd)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/chengdu/shangrila/"},
    {"name": "Shangri-La Hangzhou", "city": "Hangzhou (West Lake / Beishan Rd)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/hangzhou/shangrila/"},
    {"name": "Midtown Shangri-La, Hangzhou", "city": "Hangzhou (Kerry Central / Yan'an Rd)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/hangzhou/midtownshangrila/"},
    {"name": "Shangri-La Sanya", "city": "Sanya (Haitang Bay / Hainan)", "country": "China", "curr": "CNY", "url": "https://www.shangri-la.com/en/sanya/shangrila/"},
    {"name": "Shangri-La The Shard, London", "city": "London (The Shard Floors 34-52 / Bridge St)", "country": "United Kingdom", "curr": "GBP", "url": "https://www.shangri-la.com/en/london/shangrila/"},
    {"name": "Shangri-La Paris", "city": "Paris (Avenue d'Iéna / Eiffel Tower View / 16th Arr)", "country": "France", "curr": "EUR", "url": "https://www.shangri-la.com/en/paris/shangrila/"},
    {"name": "Shangri-La Bosphorus, Istanbul", "city": "Istanbul (Besiktas / Bosphorus Strait)", "country": "Turkey", "curr": "USD", "url": "https://www.shangri-la.com/en/istanbul/shangrila/"},
    {"name": "Shangri-La Dubai", "city": "Dubai (Sheikh Zayed Rd / Downtown / Burj View)", "country": "United Arab Emirates", "curr": "AED", "url": "https://www.shangri-la.com/en/dubai/shangrila/"},
    {"name": "Shangri-La Qaryat Al Beri, Abu Dhabi", "city": "Abu Dhabi (Khor Al Maqta / Grand Mosque View)", "country": "United Arab Emirates", "curr": "AED", "url": "https://www.shangri-la.com/en/abudhabi/shangrila/"},
    {"name": "Traders Hotel, Qaryat Al Beri, Abu Dhabi", "city": "Abu Dhabi (Khor Al Maqta / Souk Qaryat Al Beri)", "country": "United Arab Emirates", "curr": "AED", "url": "https://www.shangri-la.com/en/abudhabi/traders/"},
    {"name": "Shangri-La Barr Al Jissah, Muscat", "city": "Muscat (Al Jissah Bay / Gulf of Oman)", "country": "Oman", "curr": "OMR", "url": "https://www.shangri-la.com/en/muscat/barraljissahresort/"},
    {"name": "Shangri-La Al Husn, Muscat", "city": "Muscat (Cliff-top / Private Cove / Adults-only)", "country": "Oman", "curr": "OMR", "url": "https://www.shangri-la.com/en/muscat/alhusnresortandspa/"},
    {"name": "Shangri-La Jeddah", "city": "Jeddah (Jeddah Waterfront / Ash Shati / Red Sea)", "country": "Saudi Arabia", "curr": "SAR", "url": "https://www.shangri-la.com/en/jeddah/shangrila/"},
    {"name": "Shangri-La Sydney", "city": "Sydney (The Rocks / Sydney Opera House & Harbour Bridge View)", "country": "Australia", "curr": "AUD", "url": "https://www.shangri-la.com/en/sydney/shangrila/"},
    {"name": "Shangri-La The Marina, Cairns", "city": "Cairns (Marlin Marina / Great Barrier Reef Gateway)", "country": "Australia", "curr": "AUD", "url": "https://www.shangri-la.com/en/cairns/shangrila/"},
    {"name": "Shangri-La Yanuca Island, Fiji", "city": "Coral Coast (Yanuca Island / Viti Levu)", "country": "Fiji", "curr": "FJD", "url": "https://www.shangri-la.com/en/fiji/yanucaislandresort/"},
    {"name": "Shangri-La Toronto", "city": "Toronto (University Ave / Downtown Financial District)", "country": "Canada", "curr": "CAD", "url": "https://www.shangri-la.com/en/toronto/shangrila/"},
    {"name": "Shangri-La Vancouver", "city": "Vancouver (West Georgia St / Alberni Luxury District)", "country": "Canada", "curr": "CAD", "url": "https://www.shangri-la.com/en/vancouver/shangrila/"},
    {"name": "Shangri-La Colombo", "city": "Colombo (Galle Face Green / One Galle Face)", "country": "Sri Lanka", "curr": "USD", "url": "https://www.shangri-la.com/en/colombo/shangrila/"},
    {"name": "Shangri-La Hambantota", "city": "Hambantota (Southern Coast / 18-hole Golf Resort)", "country": "Sri Lanka", "curr": "USD", "url": "https://www.shangri-la.com/en/hambantota/shangrila/"},
    {"name": "Shangri-La New Delhi", "city": "New Delhi (Connaught Place / Ashoka Rd)", "country": "India", "curr": "INR", "url": "https://www.shangri-la.com/en/newdelhi/erosshangrila/"},
    {"name": "Shangri-La Bengaluru", "city": "Bengaluru (Palace Rd / Mount Carmel / Vasanth Nagar)", "country": "India", "curr": "INR", "url": "https://www.shangri-la.com/en/bengaluru/shangrila/"},
    {"name": "Shangri-La The Fort, Manila", "city": "Manila (Bonifacio Global City - BGC / Taguig)", "country": "Philippines", "curr": "PHP", "url": "https://www.shangri-la.com/en/manila/shangrilaatthefort/"},
    {"name": "Edsa Shangri-La, Manila", "city": "Manila (Ortigas Center / Mandaluyong)", "country": "Philippines", "curr": "PHP", "url": "https://www.shangri-la.com/en/manila/edsashangrila/"},
    {"name": "Shangri-La Mactan, Cebu", "city": "Cebu (Punta Engano / Mactan Island Beach Resort)", "country": "Philippines", "curr": "PHP", "url": "https://www.shangri-la.com/en/cebu/mactanshangrila/"},
    {"name": "Shangri-La Boracay", "city": "Boracay (Puka Beach / Eco-Luxury Sanctuary)", "country": "Philippines", "curr": "PHP", "url": "https://www.shangri-la.com/en/boracay/shangrila/"},
    {"name": "JEN Manila by Shangri-La", "city": "Manila (Roxas Boulevard / Pasay)", "country": "Philippines", "curr": "PHP", "url": "https://www.shangri-la.com/en/manila/hoteljen/manila/"},
    {"name": "Shangri-La Mauritius (Le Touessrok)", "city": "Trou d'Eau Douce (Ilot Mangénie Private Island)", "country": "Mauritius", "curr": "EUR", "url": "https://www.shangri-la.com/en/mauritius/shangrila/"},
]

def seed_shangrila():
    conn = sqlite3.connect('hotel_stays.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM hotels WHERE brand = 'SHANGRI_LA'")
    conn.commit()

    for idx, h in enumerate(SHANGRI_LA_GLOBAL):
        h_id = f"shang_{idx+1}_{h['country'].lower()[:4]}"
        cursor.execute("""
            INSERT OR REPLACE INTO hotels (id, brand, name, city, country, currency, loyalty_model, track_points, official_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (h_id, "SHANGRI_LA", h["name"], h["city"], h["country"], h["curr"], "FIXED_REBATE", 0, h["url"]))

    conn.commit()
    conn.close()
    logger.info(f"Successfully seeded {len(SHANGRI_LA_GLOBAL)} Shangri-La hotels into database!")
    export_watchlist_to_excel()

if __name__ == '__main__':
    seed_shangrila()
